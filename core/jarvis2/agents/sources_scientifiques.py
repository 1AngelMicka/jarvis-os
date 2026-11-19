"""Sources scientifiques des missions de recherche : OpenAlex, arXiv, PubMed, Europe PMC (API publiques, sans clé).

Chaque base reçoit les requêtes de la mission (rien d'autre : ni souvenir, ni nom, ni contexte) et renvoie des
DONNÉES (titres, adresses, résumés), jamais des instructions. Les délais et limites de débit publiés par chaque
service sont respectés : un intervalle minimal entre deux appels à la même base (arXiv : 3 s ; PubMed sans clé :
3 appels par seconde), un délai d'attente court, et une base en panne n'empêche jamais les autres de répondre.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from typing import Any

import httpx

from .recherche_web import Source

journal = logging.getLogger("jarvis2.sources_scientifiques")

AGENT = "JARVIS2 (assistant personnel open source ; recherche documentaire)"
TAILLE_EXTRAIT = 700
ATTENTE_MAX_429 = 5.0  # « Retry-After » plus long : la base est sautée pour cette requête
MOTS_VIDES_EN = frozenset(
    [
        "the",
        "and",
        "for",
        "with",
        "from",
        "into",
        "over",
        "under",
        "about",
        "that",
        "this",
        "what",
        "which",
        "how",
        "why",
        "are",
        "was",
        "were",
        "its",
    ]
)
_NON_ASCII = re.compile(r"[^\x00-\x7f]")
_MOT_EN = re.compile(r"[A-Za-z][A-Za-z0-9-]{2,}")
_ESPACES = re.compile(r"\s+")
_BALISES = re.compile(r"<[^>]{0,200}>")  # balises HTML / JATS dans les résumés (texte brut gardé, jamais rendu)


def propre(texte: Any, taille: int = TAILLE_EXTRAIT) -> str:
    """Texte d'une API : balises retirées, espaces réduits, longueur bornée."""
    return _ESPACES.sub(" ", _BALISES.sub(" ", str(texte or ""))).strip()[:taille]


def _secondes(valeur: str | None) -> float | None:
    try:
        return max(0.0, float(valeur)) if valeur is not None else None
    except ValueError:
        return None


def _adresse(url: Any) -> str | None:
    url = str(url or "").strip()
    return url if url.startswith(("http://", "https://")) else None


def _xml(texte: str) -> ET.Element:
    """Analyse un document XML d'une API ; un DOCTYPE ou une entité déclarée est refusé (expansion d'entités)."""
    if "<!DOCTYPE" in texte or "<!ENTITY" in texte:
        raise ValueError("document XML refusé (DOCTYPE)")
    return ET.fromstring(texte)  # noqa: S314


class Limiteur:
    """Intervalle minimal entre deux appels à un même service (partagé entre missions simultanées)."""

    def __init__(self, intervalle: float) -> None:
        self.intervalle = intervalle
        self._dernier = 0.0
        self._verrou = asyncio.Lock()

    async def attendre(self) -> None:
        async with self._verrou:
            reste = self._dernier + self.intervalle - time.monotonic()
            if reste > 0:
                await asyncio.sleep(reste)
            self._dernier = time.monotonic()


class Base:
    """Une base scientifique : `_chercher` interroge l'API ; `chercher` ajoute la limite de débit et la tolérance
    aux pannes."""

    nom = "base"
    intervalle = 1.0

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, delai: float = 15) -> None:
        self.transport = transport
        self.delai = delai
        self.limiteur = Limiteur(self.intervalle if transport is None else 0)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self.transport, timeout=self.delai, headers={"User-Agent": AGENT}, follow_redirects=True
        )

    async def get(self, client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> httpx.Response:
        await self.limiteur.attendre()
        reponse = await client.get(url, params=params)
        if reponse.status_code == 429:  # trop d'appels : une seule nouvelle tentative, si le service la permet vite
            attente = _secondes(reponse.headers.get("retry-after"))
            if attente is not None and attente <= ATTENTE_MAX_429:
                await asyncio.sleep(attente)
                await self.limiteur.attendre()
                reponse = await client.get(url, params=params)
        if reponse.status_code == 429:  # on n'insiste pas : la mission continue sans cette base
            raise httpx.HTTPStatusError("limite de débit atteinte", request=reponse.request, response=reponse)
        reponse.raise_for_status()
        return reponse

    async def chercher(self, requete: str, nombre: int = 3) -> list[Source]:
        try:
            async with self.client() as client:
                return (await self._chercher(client, requete.strip()[:300], nombre))[:nombre]
        except Exception as exc:  # une base en panne ne bloque jamais la mission
            journal.warning("%s indisponible pour « %s » : %s", self.nom, requete[:80], exc)
            return []

    async def _chercher(self, client: httpx.AsyncClient, requete: str, nombre: int) -> list[Source]:
        raise NotImplementedError


class OpenAlex(Base):
    nom = "OpenAlex"
    intervalle = 0.2  # 10 appels par seconde au plus ; on reste bien en dessous

    async def _chercher(self, client: httpx.AsyncClient, requete: str, nombre: int) -> list[Source]:
        params = {
            "search": requete,
            "per-page": nombre,
            "select": "id,doi,display_name,publication_year,abstract_inverted_index,primary_location",
        }
        donnees: Any = (await self.get(client, "https://api.openalex.org/works", params)).json()
        sources = []
        for r in donnees.get("results") or []:
            url = _adresse(r.get("doi")) or _adresse((r.get("primary_location") or {}).get("landing_page_url"))
            url = url or _adresse(r.get("id"))
            if url is None:
                continue
            resume = resume_inverse(r.get("abstract_inverted_index"))
            annee = r.get("publication_year")
            titre = propre(r.get("display_name") or url, 200)
            sources.append(Source(f"{titre} ({annee}, OpenAlex)" if annee else f"{titre} (OpenAlex)", url, resume))
        return sources


def resume_inverse(index: Any) -> str:
    """OpenAlex publie le résumé en index inversé {mot: [positions]} : on le remet dans l'ordre."""
    if not isinstance(index, dict):
        return ""
    positions: dict[int, str] = {}
    for mot, places in index.items():
        if isinstance(places, list):
            for p in places:
                if isinstance(p, int) and 0 <= p < 5000:
                    positions[p] = str(mot)
    return propre(" ".join(positions[i] for i in sorted(positions)))


class ArXiv(Base):
    nom = "arXiv"
    intervalle = 3.0  # consigne d'arXiv : un appel toutes les 3 secondes

    async def _chercher(self, client: httpx.AsyncClient, requete: str, nombre: int) -> list[Source]:
        # arXiv est en anglais et relie les mots par OU : seules les requêtes anglaises partent, tous mots exigés
        if _NON_ASCII.search(requete):
            return []
        mots = [m for m in _MOT_EN.findall(requete) if m.lower() not in MOTS_VIDES_EN][:6]
        if not mots:
            return []
        params = {"search_query": " AND ".join(f"all:{m}" for m in mots), "start": 0, "max_results": nombre}
        racine = _xml((await self.get(client, "https://export.arxiv.org/api/query", params)).text)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        sources = []
        for entree in racine.findall("a:entry", ns):
            url = _adresse(entree.findtext("a:id", default="", namespaces=ns))
            if url is None:
                continue
            titre = propre(entree.findtext("a:title", default=url, namespaces=ns), 200)
            annee = (entree.findtext("a:published", default="", namespaces=ns) or "")[:4]
            resume = propre(entree.findtext("a:summary", default="", namespaces=ns))
            sources.append(Source(f"{titre} ({annee}, arXiv)" if annee else f"{titre} (arXiv)", url, resume))
        return sources


class PubMed(Base):
    nom = "PubMed"
    intervalle = 0.4  # sans clé NCBI : 3 appels par seconde au plus
    EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    async def _chercher(self, client: httpx.AsyncClient, requete: str, nombre: int) -> list[Source]:
        commun = {"db": "pubmed", "retmode": "json", "tool": "jarvis2"}
        trouve: Any = (
            await self.get(client, f"{self.EUTILS}/esearch.fcgi", {**commun, "term": requete, "retmax": nombre})
        ).json()
        ids = [str(i) for i in (trouve.get("esearchresult") or {}).get("idlist") or [] if str(i).isdigit()]
        if not ids:
            return []
        resume: Any = (await self.get(client, f"{self.EUTILS}/esummary.fcgi", {**commun, "id": ",".join(ids)})).json()
        resultat = resume.get("result") or {}
        sources = []
        for pmid in ids:
            r = resultat.get(pmid) or {}
            titre = propre(r.get("title") or f"PubMed {pmid}", 200)
            revue = propre(r.get("fulljournalname") or r.get("source"), 120)
            date = propre(r.get("pubdate"), 20)
            auteurs = ", ".join(propre(a.get("name"), 60) for a in (r.get("authors") or [])[:3] if isinstance(a, dict))
            extrait = " · ".join(x for x in (revue, date, auteurs) if x)
            sources.append(Source(f"{titre} (PubMed)", f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", extrait))
        return sources


class EuropePMC(Base):
    nom = "Europe PMC"
    intervalle = 0.2

    async def _chercher(self, client: httpx.AsyncClient, requete: str, nombre: int) -> list[Source]:
        params = {"query": requete, "format": "json", "pageSize": nombre, "resultType": "core"}
        donnees: Any = (
            await self.get(client, "https://www.ebi.ac.uk/europepmc/webservices/rest/search", params)
        ).json()
        sources = []
        for r in (donnees.get("resultList") or {}).get("result") or []:
            source, ident = str(r.get("source") or ""), str(r.get("id") or "")
            url = f"https://doi.org/{r['doi']}" if r.get("doi") else None
            if url is None and re.fullmatch(r"[A-Z]{2,6}", source) and re.fullmatch(r"[\w.]{1,40}", ident):
                url = f"https://europepmc.org/article/{source}/{ident}"
            if url is None:
                continue
            titre = propre(r.get("title") or url, 200)
            annee = propre(r.get("pubYear"), 4)
            sources.append(
                Source(
                    f"{titre} ({annee}, Europe PMC)" if annee else f"{titre} (Europe PMC)",
                    url,
                    propre(r.get("abstractText")),
                )
            )
        return sources


class SourcesScientifiques:
    """Les quatre bases interrogées ensemble ; résultats entrelacés, sans doublon d'adresse."""

    def __init__(self, bases: Sequence[Base] | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.bases = (
            list(bases)
            if bases is not None
            else [
                OpenAlex(transport),
                ArXiv(transport),
                PubMed(transport),
                EuropePMC(transport),
            ]
        )

    @property
    def disponible(self) -> bool:
        return bool(self.bases)

    @property
    def noms(self) -> list[str]:
        return [b.nom for b in self.bases]

    async def chercher(self, requete: str, par_base: int = 3) -> list[Source]:
        lots = await asyncio.gather(*(b.chercher(requete, par_base) for b in self.bases))
        vues: set[str] = set()
        sources: list[Source] = []
        for rang in range(max((len(lot) for lot in lots), default=0)):
            for lot in lots:
                if rang < len(lot) and lot[rang].url not in vues:
                    vues.add(lot[rang].url)
                    sources.append(lot[rang])
        return sources
