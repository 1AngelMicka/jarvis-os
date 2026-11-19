"""Connecteurs « compatibles OpenAI » (`/chat/completions` en flux SSE) : une classe, plusieurs instances.

- API avec clé : OpenAI, OpenRouter, Google Gemini (point d'accès compatible OpenAI), tout point d'accès déclaré ;
- serveurs LOCAUX : LM Studio, serveur llama.cpp, vLLM (sans clé, les données ne quittent pas le PC).

La clé est lue dans le coffre au moment de l'appel (jamais gardée dans l'objet, jamais journalisée). Le coût est
celui que renvoie le fournisseur (OpenRouter), sinon calculé avec les tarifs de la configuration locale.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from typing import Any

import httpx

from ..registre import MoteurRegistry
from .base import (
    Delta,
    ErreurMoteur,
    EtatSante,
    Evenement,
    Famille,
    Fin,
    InfoModele,
    Message,
    Moteur,
    Options,
    Reponse,
    Usage,
)

journal = logging.getLogger("jarvis2.moteurs.compatible_openai")

ROLES = {"systeme": "system", "utilisateur": "user", "assistant": "assistant"}
FournisseurCle = Callable[[], str | None]
Tarifs = Mapping[str, tuple[float, float]]  # modèle -> ($ / million de jetons en entrée, en sortie)


def contenu_openai(m: Message) -> str | list[dict[str, Any]]:
    """Texte seul, ou parties texte + images (format vision de `/chat/completions`)."""
    if not m.images:
        return m.contenu
    parties: list[dict[str, Any]] = [{"type": "text", "text": m.contenu}]
    parties += [{"type": "image_url", "image_url": {"url": i.data_url()}} for i in m.images]
    return parties


def cout(tarifs: Tarifs, modele: str, usage: Usage) -> float | None:
    prix = tarifs.get(modele)
    if prix is None:
        return None
    return round(((usage.jetons_entree or 0) * prix[0] + (usage.jetons_sortie or 0) * prix[1]) / 1_000_000, 6)


def message_erreur(statut: int, corps: str) -> str:
    try:
        donnees = json.loads(corps)
        detail = donnees.get("error", {})
        texte = detail.get("message") if isinstance(detail, dict) else str(detail)
    except (ValueError, AttributeError):
        texte = corps[:200]
    if statut in (401, 403):
        return f"clé refusée ({statut}) : vérifiez-la dans Connecteurs"
    if statut == 429:
        return "limite d'usage atteinte (429) : réessayez plus tard"
    return f"erreur {statut} : {str(texte)[:200]}"


@MoteurRegistry.register("compatible_openai")
class MoteurCompatibleOpenAI(Moteur):
    def __init__(
        self,
        id: str,
        nom: str,
        url: str,
        famille: Famille = "api",
        cle: FournisseurCle | None = None,
        modele: str | None = None,
        modeles: Sequence[str] = (),
        tarifs: Tarifs | None = None,
        installation_url: str | None = None,
        conditions_url: str | None = None,
        entetes: Mapping[str, str] | None = None,
        cout_fourni: bool = False,
        actif_par_defaut: bool = True,
        vision: bool = True,
        delai: float = 300.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.id, self.nom, self.famille = id, nom, famille
        self.actif_par_defaut = actif_par_defaut
        self.vision = vision  # selon le modèle : un modèle sans vision fait répondre une erreur claire au fournisseur
        self.externe = famille != "local"
        self.url = url.rstrip("/")
        self._cle = cle
        self.modele = modele
        self.modeles_fixes = tuple(modeles)
        self.tarifs = dict(tarifs or {})
        self.installation_url, self.conditions_url = installation_url, conditions_url
        self.entetes = dict(entetes or {})
        self.cout_fourni = cout_fourni
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(delai, connect=3.0), transport=transport)
        self._modeles: tuple[float, list[InfoModele]] | None = None

    def _entetes(self) -> dict[str, str]:
        entetes = dict(self.entetes)
        cle = self._cle() if self._cle else None
        if self._cle and not cle:
            raise ErreurMoteur(f"{self.nom} : aucune clé d'API enregistrée (Connecteurs)")
        if cle:
            entetes["Authorization"] = f"Bearer {cle}"
        return entetes

    def __repr__(self) -> str:  # jamais la clé dans une trace
        return f"MoteurCompatibleOpenAI(id={self.id!r}, url={self.url!r})"

    async def _modele(self, options: Options | None) -> str:
        if options and options.modele:
            return options.modele
        if self.modele:
            return self.modele
        modeles = await self.list_models()
        if not modeles or not modeles[0].id:
            raise ErreurMoteur(f"{self.nom} : aucun modèle disponible")
        return modeles[0].id

    async def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        modele = await self._modele(options)
        corps: dict[str, Any] = {
            "model": modele,
            "messages": [{"role": ROLES[m.role], "content": contenu_openai(m)} for m in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if self.cout_fourni:
            corps["usage"] = {"include": True}  # OpenRouter : coût réel dans `usage.cost`
        if options and options.temperature is not None:
            corps["temperature"] = options.temperature
        morceaux: list[str] = []
        usage, cout_reel, modele_reel = Usage(), None, modele
        try:
            async with self.client.stream(
                "POST", f"{self.url}/chat/completions", json=corps, headers=self._entetes()
            ) as rep:
                if rep.status_code != 200:
                    corps_erreur = (await rep.aread()).decode("utf-8", "replace")
                    if rep.status_code in (400, 404, 422) and any(m.images for m in messages):
                        raise ErreurMoteur(
                            f"{self.nom} : le modèle « {modele} » refuse les images "
                            f"({message_erreur(rep.status_code, corps_erreur)}) : choisissez un modèle de vision"
                        )
                    raise ErreurMoteur(f"{self.nom} : {message_erreur(rep.status_code, corps_erreur)}")
                async for ligne in rep.aiter_lines():
                    if not ligne.startswith("data:"):
                        continue
                    donnees = ligne[5:].strip()
                    if donnees == "[DONE]":
                        break
                    try:
                        ev = json.loads(donnees)
                    except ValueError:
                        continue
                    if ev.get("error"):
                        raise ErreurMoteur(f"{self.nom} : {ev['error'].get('message', ev['error'])}")
                    modele_reel = ev.get("model") or modele_reel
                    for choix in ev.get("choices") or []:
                        texte = (choix.get("delta") or {}).get("content")
                        if texte:
                            morceaux.append(texte)
                            yield Delta(texte)
                    if isinstance(ev.get("usage"), dict):
                        u = ev["usage"]
                        usage = Usage(u.get("prompt_tokens"), u.get("completion_tokens"))
                        if isinstance(u.get("cost"), int | float):
                            cout_reel = float(u["cost"])
        except httpx.ConnectError as exc:
            raise ErreurMoteur(f"{self.nom} injoignable ({self.url})") from exc
        except httpx.TimeoutException as exc:
            raise ErreurMoteur(f"{self.nom} n'a pas répondu à temps") from exc
        texte = "".join(morceaux).strip()
        if not texte:
            raise ErreurMoteur(f"Réponse vide de {self.nom}")
        calcule = cout_reel if cout_reel is not None else cout(self.tarifs, modele, usage)
        meta: dict[str, Any] = {"source_auth": "cle_api" if self._cle else "local"}
        if calcule is None and self.externe:
            meta["cout_inconnu"] = True
        elif cout_reel is None and calcule is not None:
            meta["cout_estime"] = True  # calculé avec les tarifs de la configuration locale
        yield Fin(Reponse(texte, modele_reel, usage, calcule or 0.0, meta))

    async def list_models(self) -> list[InfoModele]:
        if self.modeles_fixes:
            return [InfoModele(m, m, m == (self.modele or self.modeles_fixes[0])) for m in self.modeles_fixes]
        maintenant = time.monotonic()
        if self._modeles and maintenant - self._modeles[0] < 300:
            return self._modeles[1]
        try:
            rep = await self.client.get(f"{self.url}/models", headers=self._entetes(), timeout=4.0)
            rep.raise_for_status()
            ids = sorted(str(m["id"]) for m in rep.json().get("data", []) if isinstance(m, dict) and m.get("id"))
        except (httpx.HTTPError, ValueError, ErreurMoteur, AttributeError):
            return []
        modeles = [InfoModele(i, i, i == self.modele) for i in ids]
        self._modeles = (maintenant, modeles)
        return modeles

    async def health(self) -> EtatSante:
        """Local : le serveur répond-il ? API : la clé existe-t-elle et est-elle acceptée ? (aucun coût)"""
        if self._cle and not self._cle():
            return EtatSante(False, "aucune clé enregistrée", installe=True, connecte=False)
        try:
            rep = await self.client.get(f"{self.url}/models", headers=self._entetes(), timeout=2.0)
        except httpx.HTTPError:
            if self.famille == "local":
                return EtatSante(False, "serveur local arrêté ou absent", installe=False)
            return EtatSante(False, "injoignable", connecte=None)
        if rep.status_code in (401, 403):
            return EtatSante(False, "clé refusée", connecte=False)
        try:
            ok = rep.status_code == 200 and isinstance(rep.json().get("data"), list)
        except (ValueError, AttributeError):
            ok = False
        if not ok:  # un autre service occupe ce port (ex. une page web) : pas un serveur compatible
            return EtatSante(False, "aucun serveur compatible OpenAI à cette adresse", installe=False)
        if self._cle:
            return EtatSante(True, "clé valide", connecte=True)
        # Un port local peut être occupé par n'importe quel programme compatible : on dit ce qu'on voit, sans deviner
        nb = len(rep.json().get("data") or [])
        return EtatSante(True, f"serveur compatible OpenAI détecté sur {self.url} ({nb} modèle{'s' if nb > 1 else ''})")

    async def fermer(self) -> None:
        await self.client.aclose()
