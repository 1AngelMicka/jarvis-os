"""Connecteur « anthropic_api » : API Anthropic Messages avec une clé (facturée à l'appel, coûts suivis).

Distinct du connecteur `claude_code` (abonnement). La clé vit dans le coffre local, lue au moment de l'appel.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncGenerator, Sequence
from typing import Any

import httpx

from ..registre import MoteurRegistry
from .base import Delta, ErreurMoteur, EtatSante, Evenement, Fin, InfoModele, Message, Moteur, Options, Reponse, Usage
from .compatible_openai import FournisseurCle, Tarifs, cout, message_erreur

URL = "https://api.anthropic.com/v1"
VERSION = "2023-06-01"


def preparer(messages: Sequence[Message]) -> tuple[str, list[dict[str, Any]]]:
    """Consignes système à part ; rôles alternés, en commençant par l'utilisateur (exigence de l'API).
    Un message avec images devient une liste de blocs : images d'abord, puis le texte (ordre conseillé)."""
    systeme = "\n\n".join(m.contenu for m in messages if m.role == "systeme")
    suite: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "systeme":
            continue
        role = "user" if m.role == "utilisateur" else "assistant"
        blocs: list[dict[str, Any]] = [
            {"type": "image", "source": {"type": "base64", "media_type": i.type_mime, "data": i.base64()}}
            for i in m.images
        ]
        blocs.append({"type": "text", "text": m.contenu})
        if suite and suite[-1]["role"] == role:
            suite[-1]["content"] += blocs
        else:
            suite.append({"role": role, "content": blocs})
    while suite and suite[0]["role"] != "user":
        suite.pop(0)
    for envoi in suite:  # sans image : texte simple, comme avant
        if all(b["type"] == "text" for b in envoi["content"]):
            envoi["content"] = "\n\n".join(b["text"] for b in envoi["content"])
    return systeme, suite


@MoteurRegistry.register("anthropic_api")
class MoteurAnthropic(Moteur):
    id = "anthropic_api"
    nom = "Anthropic (clé d'API)"
    famille = "api"
    externe = True
    installation_url = "https://console.anthropic.com/settings/keys"
    conditions_url = "https://www.anthropic.com/legal/commercial-terms"
    vision = True

    def __init__(
        self,
        cle: FournisseurCle,
        modele: str = "claude-sonnet-5-5",
        tarifs: Tarifs | None = None,
        url: str = URL,
        delai: float = 300.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._cle = cle
        self.modele = modele
        self.tarifs = dict(tarifs or {})
        self.url = url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(delai, connect=3.0), transport=transport)
        self._modeles: tuple[float, list[InfoModele]] | None = None

    def __repr__(self) -> str:
        return "MoteurAnthropic()"

    def _entetes(self) -> dict[str, str]:
        cle = self._cle()
        if not cle:
            raise ErreurMoteur("Anthropic : aucune clé d'API enregistrée (Connecteurs)")
        return {"x-api-key": cle, "anthropic-version": VERSION}

    async def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        modele = (options.modele if options else None) or self.modele
        systeme, suite = preparer(messages)
        corps: dict[str, Any] = {"model": modele, "max_tokens": 4096, "messages": suite, "stream": True}
        if systeme:
            corps["system"] = systeme
        morceaux: list[str] = []
        entree = sortie = 0
        try:
            async with self.client.stream("POST", f"{self.url}/messages", json=corps, headers=self._entetes()) as rep:
                if rep.status_code != 200:
                    corps_erreur = (await rep.aread()).decode("utf-8", "replace")
                    raise ErreurMoteur(f"Anthropic : {message_erreur(rep.status_code, corps_erreur)}")
                async for ligne in rep.aiter_lines():
                    if not ligne.startswith("data:"):
                        continue
                    try:
                        ev = json.loads(ligne[5:])
                    except ValueError:
                        continue
                    type_ = ev.get("type")
                    if type_ == "content_block_delta" and (ev.get("delta") or {}).get("type") == "text_delta":
                        texte = ev["delta"].get("text") or ""
                        if texte:
                            morceaux.append(texte)
                            yield Delta(texte)
                    elif type_ == "message_start":
                        entree = int(((ev.get("message") or {}).get("usage") or {}).get("input_tokens") or 0)
                    elif type_ == "message_delta":
                        sortie = int((ev.get("usage") or {}).get("output_tokens") or sortie)
                    elif type_ == "error":
                        raise ErreurMoteur(f"Anthropic : {(ev.get('error') or {}).get('message', 'erreur')}")
        except httpx.ConnectError as exc:
            raise ErreurMoteur("Anthropic injoignable") from exc
        except httpx.TimeoutException as exc:
            raise ErreurMoteur("Anthropic n'a pas répondu à temps") from exc
        texte = "".join(morceaux).strip()
        if not texte:
            raise ErreurMoteur("Réponse vide d'Anthropic")
        usage = Usage(entree or None, sortie or None)
        calcule = cout(self.tarifs, modele, usage)
        meta: dict[str, Any] = {"source_auth": "cle_api"}
        if calcule is None:
            meta["cout_inconnu"] = True
        else:
            meta["cout_estime"] = True  # calculé avec les tarifs de la configuration locale
        yield Fin(Reponse(texte, modele, usage, calcule or 0.0, meta))

    async def list_models(self) -> list[InfoModele]:
        maintenant = time.monotonic()
        if self._modeles and maintenant - self._modeles[0] < 600:
            return self._modeles[1]
        try:
            rep = await self.client.get(f"{self.url}/models", headers=self._entetes(), timeout=4.0)
            rep.raise_for_status()
            ids = [str(m["id"]) for m in rep.json().get("data", []) if m.get("id")]
        except (httpx.HTTPError, ValueError, ErreurMoteur):
            return [InfoModele(self.modele, self.modele, True)]
        modeles = [InfoModele(i, i, i == self.modele) for i in ids] or [InfoModele(self.modele, self.modele, True)]
        self._modeles = (maintenant, modeles)
        return modeles

    async def health(self) -> EtatSante:
        if not self._cle():
            return EtatSante(False, "aucune clé enregistrée", connecte=False)
        try:
            rep = await self.client.get(f"{self.url}/models", headers=self._entetes(), timeout=4.0)
        except httpx.HTTPError:
            return EtatSante(False, "injoignable")
        if rep.status_code in (401, 403):
            return EtatSante(False, "clé refusée", connecte=False)
        return EtatSante(
            rep.status_code == 200,
            "clé valide" if rep.status_code == 200 else f"erreur {rep.status_code}",
            connecte=rep.status_code == 200,
        )

    async def fermer(self) -> None:
        await self.client.aclose()
