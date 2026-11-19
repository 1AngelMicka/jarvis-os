"""Accueil du matin : au premier lancement du jour sur chaque appareil, une salutation courte.

Contenu : date et heure, météo « à la maison » (Open-Meteo, sans clé), recettes lancées ce matin ou en échec,
au plus deux points d'attention. Le lieu est PRIVÉ : il vient de la configuration locale (`[matin]` : ville,
ou latitude et longitude) ou des réglages (géocodage Open-Meteo, position de l'appareil), n'apparaît jamais dans
le texte lu à voix haute, ni dans l'audit, ni dans les journaux. Jamais d'accueil pendant l'arrêt d'urgence.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from .db import Base

journal = logging.getLogger("jarvis2.matin")


def _sans_lieu(enregistrement: logging.LogRecord) -> bool:
    """httpx journalise chaque URL en INFO : celles d'Open-Meteo portent le lieu (ville, coordonnées), privé."""
    return "open-meteo.com" not in enregistrement.getMessage()


logging.getLogger("httpx").addFilter(_sans_lieu)

Mode = Literal["parle", "texte", "desactive"]
MODES: tuple[Mode, ...] = ("parle", "texte", "desactive")
URL_PREVISIONS = "https://api.open-meteo.com/v1/forecast"
URL_GEOCODAGE = "https://geocoding-api.open-meteo.com/v1/search"
DUREE_CACHE = 30 * 60  # secondes
MAX_ATTENTION = 2

JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MOIS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)  # fmt: skip

# Codes météo de l'OMM (WMO) renvoyés par Open-Meteo
CIEL = {
    0: "ciel dégagé",
    1: "plutôt dégagé",
    2: "partiellement nuageux",
    3: "ciel couvert",
    45: "brouillard",
    48: "brouillard givrant",
    51: "bruine légère",
    53: "bruine",
    55: "bruine forte",
    56: "bruine verglaçante",
    57: "bruine verglaçante",
    61: "pluie faible",
    63: "pluie",
    65: "forte pluie",
    66: "pluie verglaçante",
    67: "pluie verglaçante",
    71: "neige faible",
    73: "neige",
    75: "forte neige",
    77: "grains de neige",
    80: "averses",
    81: "averses",
    82: "fortes averses",
    85: "averses de neige",
    86: "averses de neige",
    95: "orage",
    96: "orage avec grêle",
    99: "orage avec grêle",
}


@dataclass(frozen=True)
class Lieu:
    latitude: float
    longitude: float
    nom: str | None = None  # privé : affiché dans les réglages seulement
    source: str = "configuration"  # « configuration », « geocodage » ou « appareil »

    def en_dict(self) -> dict[str, Any]:
        return {"latitude": self.latitude, "longitude": self.longitude, "nom": self.nom, "source": self.source}

    @staticmethod
    def depuis(donnees: Any, source: str | None = None) -> Lieu | None:
        if not isinstance(donnees, dict):
            return None
        try:
            lat, lon = float(donnees["latitude"]), float(donnees["longitude"])
        except (KeyError, TypeError, ValueError):
            return None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        nom = donnees.get("nom") or donnees.get("ville")
        return Lieu(lat, lon, str(nom) if nom else None, source or str(donnees.get("source") or "configuration"))


class ServiceMeteo:
    """Client Open-Meteo (prévisions, géocodage) avec cache de 30 min ; `transport` remplaçable en test."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, delai: float = 8.0) -> None:
        self.transport = transport
        self.delai = delai
        self._cache: dict[tuple[float, float], tuple[float, dict[str, Any]]] = {}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport, timeout=self.delai, headers={"User-Agent": "JARVIS2"})

    async def lieu_depuis_ville(self, ville: str) -> Lieu | None:
        lieux = await self.geocoder(ville, 1)
        return Lieu(lieux[0]["latitude"], lieux[0]["longitude"], ville, "configuration") if lieux else None

    async def geocoder(self, recherche: str, nombre: int = 5) -> list[dict[str, Any]]:
        async with self._client() as client:
            rep = await client.get(
                URL_GEOCODAGE, params={"name": recherche, "count": nombre, "language": "fr", "format": "json"}
            )
            rep.raise_for_status()
        return [
            {
                "nom": r.get("name"),
                "region": r.get("admin1"),
                "pays": r.get("country"),
                "latitude": r["latitude"],
                "longitude": r["longitude"],
            }
            for r in rep.json().get("results") or []
            if "latitude" in r and "longitude" in r
        ]

    async def meteo(self, lieu: Lieu) -> dict[str, Any] | None:
        """Météo du jour, ou None si Open-Meteo ne répond pas (l'accueil continue sans)."""
        cle = (round(lieu.latitude, 2), round(lieu.longitude, 2))
        en_cache = self._cache.get(cle)
        if en_cache and time.monotonic() - en_cache[0] < DUREE_CACHE:
            return en_cache[1]
        params: dict[str, str | int | float] = {
            "latitude": cle[0],
            "longitude": cle[1],
            "current": "temperature_2m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": 1,
        }
        try:
            async with self._client() as client:
                rep = await client.get(URL_PREVISIONS, params=params)
                rep.raise_for_status()
            d = rep.json()
            actuel, jour = d.get("current") or {}, d.get("daily") or {}

            def premier(cle_jour: str) -> float | None:
                v = (jour.get(cle_jour) or [None])[0]
                return float(v) if isinstance(v, int | float) else None

            code = actuel.get("weather_code")
            meteo = {
                "temperature": actuel.get("temperature_2m"),
                "ciel": CIEL.get(code, "temps incertain") if isinstance(code, int) else None,
                "code": code,
                "min": premier("temperature_2m_min"),
                "max": premier("temperature_2m_max"),
                "pluie": premier("precipitation_probability_max"),
            }
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            journal.warning("Météo indisponible : %s", type(exc).__name__)  # jamais le lieu dans le journal
            return None
        self._cache[cle] = (time.monotonic(), meteo)
        return meteo


# --- État enregistré (etat_systeme, clé « matin ») ---------------------------------------------------------


async def lire_etat(base: Base) -> dict[str, Any]:
    valeur = await base.fetchval("SELECT valeur FROM etat_systeme WHERE cle = 'matin'")
    etat = valeur if isinstance(valeur, dict) else json.loads(valeur or "{}")
    etat.setdefault("mode", "parle")
    etat.setdefault("vus", {})
    return etat


async def ecrire_etat(base: Base, etat: dict[str, Any]) -> None:
    await base.execute(
        "UPDATE etat_systeme SET valeur = $1::text::jsonb, maj_le = now() WHERE cle = 'matin'", json.dumps(etat)
    )


def jour_local(maintenant: datetime, fuseau: Any) -> str:
    return maintenant.astimezone(fuseau).date().isoformat()


# --- Contenu de l'accueil ------------------------------------------------------------------------------------


def _heure(h: datetime) -> str:
    return f"{h.hour} h" if h.minute == 0 else f"{h.hour} h {h.minute:02d}"


def _degres(v: float | None) -> str:
    return f"{round(v)} degré{'s' if abs(round(v)) > 1 else ''}" if v is not None else ""


def salutation(h: datetime) -> str:
    return "Bonsoir" if h.hour >= 18 or h.hour < 4 else "Bonjour"


def texte_meteo(m: dict[str, Any]) -> str:
    morceaux = []
    if m.get("temperature") is not None:
        morceaux.append(_degres(m["temperature"]))
    if m.get("ciel"):
        morceaux.append(m["ciel"])
    phrase = ", ".join(morceaux)
    if m.get("min") is not None and m.get("max") is not None:
        phrase += f" ; entre {round(m['min'])} et {round(m['max'])} aujourd'hui"
    if m.get("pluie") is not None and m["pluie"] >= 50:
        phrase += f", {round(m['pluie'])} % de risque de pluie"
    return phrase


async def recettes_du_jour(base: Base, noms: dict[str, str], debut_jour: datetime) -> list[dict[str, Any]]:
    """Dernière exécution du jour de chaque recette de l'utilisateur (les tâches système sont écartées)."""
    lignes = await base.fetch(
        "SELECT recette, debut, statut, erreur FROM executions_recettes ORDER BY id DESC LIMIT 200"
    )
    vues: dict[str, dict[str, Any]] = {}
    for ligne in lignes:
        ident, debut = ligne["recette"], ligne["debut"]
        if ident.startswith("systeme:") or ident in vues or not isinstance(debut, datetime):
            continue
        if (debut if debut.tzinfo else debut.replace(tzinfo=UTC)) < debut_jour:
            continue
        vues[ident] = {"id": ident, "nom": noms.get(ident, ident), "statut": ligne["statut"]}
    return list(vues.values())


async def demandes_en_attente(base: Base, maintenant: datetime) -> int:
    lignes = await base.fetch("SELECT expire_le FROM demandes WHERE statut = 'en_attente'")
    total = 0
    for ligne in lignes:
        e = ligne["expire_le"]
        if not isinstance(e, datetime) or (e if e.tzinfo else e.replace(tzinfo=UTC)) > maintenant:
            total += 1
    return total


def points_attention(recettes: list[dict[str, Any]], demandes: int) -> list[str]:
    points = []
    echecs = [r["nom"] for r in recettes if r["statut"] == "erreur"]
    if echecs:
        points.append(
            f"La recette « {echecs[0]} » a échoué ce matin."
            if len(echecs) == 1
            else f"{len(echecs)} recettes ont échoué ce matin."
        )
    if demandes:
        points.append(
            "Une demande attend votre approbation."
            if demandes == 1
            else f"{demandes} demandes attendent votre approbation."
        )
    return points[:MAX_ATTENTION]


def composer(
    h: datetime, meteo: dict[str, Any] | None, recettes: list[dict[str, Any]], attention: list[str]
) -> dict[str, Any]:
    """Assemble la carte et le texte parlé. Le lieu n'y figure jamais : seulement « à la maison »."""
    date = f"{JOURS[h.weekday()]} {h.day if h.day > 1 else '1er'} {MOIS[h.month - 1]}"
    bonjour = salutation(h)
    phrases = [f"{bonjour}. Nous sommes {date}, il est {_heure(h)}."]
    if meteo:
        phrases.append(f"À la maison : {texte_meteo(meteo)}.")
    lancees = [r for r in recettes if r["statut"] in ("ok", "en_cours")]
    if lancees:
        noms = ", ".join(r["nom"] for r in lancees[:3])
        phrases.append(f"Ce matin : {noms}." if len(lancees) <= 3 else f"Ce matin : {noms} et d'autres.")
    phrases.extend(attention)
    return {
        "salutation": bonjour,
        "date": date,
        "heure": _heure(h),
        "meteo": {**meteo, "texte": texte_meteo(meteo)} if meteo else None,
        "recettes": recettes,
        "attention": attention,
        "texte_parle": " ".join(phrases),
    }
