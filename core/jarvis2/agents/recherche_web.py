"""Recherche web privée par une instance SearXNG de l'utilisateur ([recherche] searxng de la configuration locale).

Aucune requête ne part vers un moteur de recherche commercial depuis JARVIS : SearXNG fait l'intermédiaire. Les
résultats sont des DONNÉES (titres, adresses, extraits), jamais des instructions.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from ..securite import barriere

journal = logging.getLogger("jarvis2.recherche_web")


@dataclass(frozen=True)
class Source:
    titre: str
    url: str
    extrait: str

    def en_dict(self) -> dict[str, str]:
        return asdict(self)


class RechercheWeb:
    def __init__(self, url: str | None, transport: httpx.AsyncBaseTransport | None = None, delai: float = 15) -> None:
        self.url = url.rstrip("/") if url else None
        self.transport = transport
        self.delai = delai

    @property
    def disponible(self) -> bool:
        return self.url is not None

    async def chercher(self, requete: str, nombre: int = 5) -> list[Source]:
        if self.url is None:
            return []
        params = {"q": requete, "format": "json", "language": "fr", "safesearch": "1"}
        async with httpx.AsyncClient(transport=self.transport, timeout=self.delai) as client:
            reponse = await client.get(f"{self.url}/search", params=params)
            reponse.raise_for_status()
            donnees: Any = reponse.json()
        barriere.marquer("web", requete)  # résultats lus : le tour courant ne peut plus agir
        sources = []
        for r in (donnees.get("results") or [])[: nombre * 2]:
            url = str(r.get("url") or "")
            if not url.startswith(("http://", "https://")):
                continue
            sources.append(Source(str(r.get("title") or url)[:200], url, str(r.get("content") or "")[:600]))
            if len(sources) >= nombre:
                break
        return sources
