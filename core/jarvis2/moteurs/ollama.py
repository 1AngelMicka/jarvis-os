"""Moteur `ollama` : modèles locaux sur la carte graphique du PC.

Règle : Ollama n'est **jamais démarré** par JARVIS. S'il est arrêté, `health` le dit et rien ne se lance.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncGenerator, Sequence
from typing import Any

import httpx

from ..registre import MoteurRegistry
from .base import Delta, ErreurMoteur, EtatSante, Evenement, Fin, InfoModele, Message, Moteur, Options, Reponse, Usage

journal = logging.getLogger("jarvis2.moteurs.ollama")

ROLES = {"systeme": "system", "utilisateur": "user", "assistant": "assistant"}


@MoteurRegistry.register("ollama")
class MoteurOllama(Moteur):
    id = "ollama"
    nom = "Ollama (local)"
    externe = False
    famille = "local"
    installation_url = "https://ollama.com/download"
    vision = True  # selon le modèle : vérifié à l'envoi (capacité « vision » d'Ollama, sinon `modele_vision`)

    def __init__(
        self,
        url: str = "http://127.0.0.1:11434",
        modele: str | None = None,
        modele_vision: str | None = None,
        delai: float = 300.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.modele = modele
        self.modele_vision = modele_vision
        self._capacites: dict[str, frozenset[str] | None] = {}
        self.client = httpx.AsyncClient(
            base_url=self.url, timeout=httpx.Timeout(delai, connect=3.0), transport=transport
        )
        self._modeles: tuple[float, list[InfoModele]] | None = None

    async def _modele_par_defaut(self) -> str:
        if self.modele:
            return self.modele
        modeles = await self.list_models()
        if not modeles:
            raise ErreurMoteur("Aucun modèle installé dans Ollama")
        return modeles[0].id

    async def capacites(self, modele: str) -> frozenset[str] | None:
        """Capacités annoncées par Ollama (« vision »…) ; None si cette version ne les donne pas."""
        if modele in self._capacites:
            return self._capacites[modele]
        try:
            rep = await self.client.post("/api/show", json={"model": modele}, timeout=5.0)
            rep.raise_for_status()
            brut = rep.json().get("capabilities")
        except (httpx.HTTPError, ValueError):
            return None
        capacites = frozenset(str(c) for c in brut) if isinstance(brut, list) else None
        self._capacites[modele] = capacites
        return capacites

    async def modele_pour_images(self, modele: str) -> str:
        """Le modèle choisi s'il voit les images, sinon le modèle de vision de la configuration locale."""
        capacites = await self.capacites(modele)
        if capacites is None or "vision" in capacites:
            return modele
        if self.modele_vision and self.modele_vision != modele:
            return self.modele_vision
        raise ErreurMoteur(
            f"Le modèle local « {modele} » ne lit pas les images : choisissez un modèle de vision (ex. qwen3.5:2b), "
            "ou ajoutez [connecteurs.ollama] modele_vision à la configuration locale"
        )

    async def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        options = options or Options()
        modele = options.modele or await self._modele_par_defaut()
        if any(m.images for m in messages):
            modele = await self.modele_pour_images(modele)
        envois: list[dict[str, Any]] = []
        for m in messages:
            envoi: dict[str, Any] = {"role": ROLES[m.role], "content": m.contenu}
            if m.images:
                envoi["images"] = [i.base64() for i in m.images]
            envois.append(envoi)
        corps: dict[str, Any] = {"model": modele, "messages": envois, "stream": True}
        if options.temperature is not None:
            corps["options"] = {"temperature": options.temperature}
        if options.rapide:
            corps["think"] = False  # modèle « qui réfléchit » : pas de raisonnement pour une petite tâche
        morceaux: list[str] = []
        final: dict[str, Any] = {}
        try:
            async with self.client.stream("POST", "/api/chat", json=corps) as rep:
                if rep.status_code == 404:
                    raise ErreurMoteur(f"Modèle Ollama « {modele} » introuvable")
                if rep.status_code != 200:
                    detail = (await rep.aread()).decode("utf-8", "replace")[:300]
                    raise ErreurMoteur(f"Ollama a répondu {rep.status_code} : {detail}")
                async for ligne in rep.aiter_lines():
                    if not ligne.strip():
                        continue
                    try:
                        donnees = json.loads(ligne)
                    except ValueError:
                        continue
                    if donnees.get("error"):
                        raise ErreurMoteur(f"Ollama : {donnees['error']}")
                    texte = (donnees.get("message") or {}).get("content") or ""
                    if texte:
                        morceaux.append(texte)
                        yield Delta(texte)
                    if donnees.get("done"):
                        final = donnees
                        break
        except httpx.ConnectError as exc:
            raise ErreurMoteur("Ollama est arrêté : démarrez-le à la main pour utiliser les IA locales") from exc
        except httpx.TimeoutException as exc:
            raise ErreurMoteur("Ollama n'a pas répondu à temps") from exc
        texte_complet = "".join(morceaux).strip()
        if not texte_complet:
            raise ErreurMoteur("Réponse vide d'Ollama")
        yield Fin(
            Reponse(
                texte=texte_complet,
                modele=modele,
                usage=Usage(jetons_entree=final.get("prompt_eval_count"), jetons_sortie=final.get("eval_count")),
                cout_usd=0.0,
            )
        )

    async def list_models(self) -> list[InfoModele]:
        maintenant = time.monotonic()
        if self._modeles and maintenant - self._modeles[0] < 30:
            return self._modeles[1]
        try:
            rep = await self.client.get("/api/tags", timeout=3.0)
            rep.raise_for_status()
            noms = sorted(str(m["name"]) for m in rep.json().get("models", []) if m.get("name"))
        except (httpx.HTTPError, ValueError):
            return []
        modeles = [InfoModele(id=n, nom=n, defaut=n == self.modele) for n in noms]
        self._modeles = (maintenant, modeles)
        return modeles

    async def health(self) -> EtatSante:
        try:
            rep = await self.client.get("/api/version", timeout=1.5)
            rep.raise_for_status()
            return EtatSante(True, f"Ollama {rep.json().get('version', '?')}")
        except (httpx.HTTPError, ValueError):
            return EtatSante(False, "Ollama arrêté (jamais démarré automatiquement)")

    async def fermer(self) -> None:
        await self.client.aclose()
