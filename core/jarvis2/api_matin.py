"""Routes de l'accueil du matin : carte du jour, « vu » par appareil, réglages (mode, lieu), géocodage."""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import TYPE_CHECKING, Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import matin
from .agents.recettes import FUSEAU
from .securite import audit
from .securite.appareils import Appareil

if TYPE_CHECKING:
    from .api import Contexte

routeur = APIRouter(prefix="/v1/matin")


def _ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


def _appareil(request: Request) -> Appareil:
    a: Appareil = request.state.appareil
    return a


async def lieu_maison(c: Contexte, etat: dict[str, Any]) -> matin.Lieu | None:
    """Lieu des réglages d'abord, sinon celui de la configuration locale (ville géocodée une fois)."""
    lieu = matin.Lieu.depuis(etat.get("localisation"))
    if lieu:
        return lieu
    locale = c.matin_locale
    lieu = matin.Lieu.depuis(locale, "configuration")
    if lieu:
        return lieu
    ville = locale.get("ville")
    if isinstance(ville, str) and ville.strip():
        try:
            lieu = await c.meteo.lieu_depuis_ville(ville.strip())
        except httpx.HTTPError:
            return None
        if lieu:  # gardé en mémoire vive : pas de nouveau géocodage à chaque accueil
            c.matin_locale = {**locale, "latitude": lieu.latitude, "longitude": lieu.longitude, "nom": ville}
        return lieu
    return None


@routeur.get("")
async def accueil_du_jour(request: Request, rejouer: bool = False) -> dict[str, Any]:
    """Carte du matin si c'est le premier lancement du jour sur cet appareil (ou « Rejouer l'accueil »)."""
    c, a = _ctx(request), _appareil(request)
    etat = await matin.lire_etat(c.pool)
    mode = etat["mode"]
    if c.urgence.actif:
        return {"afficher": False, "raison": "urgence", "mode": mode}
    maintenant = datetime.now(UTC)
    aujourd_hui = matin.jour_local(maintenant, FUSEAU)
    if not rejouer:
        if mode == "desactive":
            return {"afficher": False, "raison": "desactive", "mode": mode}
        if etat["vus"].get(str(a.id)) == aujourd_hui:
            return {"afficher": False, "raison": "deja_vu", "mode": mode}
    h = maintenant.astimezone(FUSEAU)
    debut_jour = datetime.combine(h.date(), time(0), FUSEAU).astimezone(UTC)
    lieu = await lieu_maison(c, etat)
    meteo = await c.meteo.meteo(lieu) if lieu else None
    noms: dict[str, str] = {}
    if c.planificateur is not None:
        noms = {r.id: r.nom for r in c.planificateur.recettes()[0]}
    recettes = await matin.recettes_du_jour(c.pool, noms, debut_jour)
    attention = matin.points_attention(recettes, await matin.demandes_en_attente(c.pool, maintenant))
    return {
        "afficher": True,
        "mode": mode,
        "jour": aujourd_hui,
        "lieu_connu": lieu is not None,
        **matin.composer(h, meteo, recettes, attention),
    }


@routeur.post("/vu")
async def marquer_vu(request: Request) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    etat = await matin.lire_etat(c.pool)
    jour = matin.jour_local(datetime.now(UTC), FUSEAU)
    etat["vus"][str(a.id)] = jour
    await matin.ecrire_etat(c.pool, etat)
    return {"vu": jour}


def _reglages(c: Contexte, etat: dict[str, Any]) -> dict[str, Any]:
    lieu = matin.Lieu.depuis(etat.get("localisation")) or matin.Lieu.depuis(c.matin_locale, "configuration")
    ville = c.matin_locale.get("ville")
    if lieu:
        localisation: dict[str, Any] | None = lieu.en_dict()
    elif ville:  # ville de la configuration pas encore géocodée : son nom seulement
        localisation = {"nom": str(ville), "source": "configuration"}
    else:
        localisation = None
    return {"mode": etat["mode"], "localisation": localisation}


@routeur.get("/reglages")
async def lire_reglages(request: Request) -> dict[str, Any]:
    c = _ctx(request)
    return _reglages(c, await matin.lire_etat(c.pool))


class Localisation(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    nom: str | None = Field(None, max_length=120)
    source: Literal["geocodage", "appareil"]


class Reglages(BaseModel):
    mode: Literal["parle", "texte", "desactive"] | None = None
    localisation: Localisation | None = None
    effacer_localisation: bool = False


@routeur.put("/reglages")
async def changer_reglages(request: Request, r: Reglages) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    etat = await matin.lire_etat(c.pool)
    details: dict[str, Any] = {}
    if r.mode is not None:
        etat["mode"] = details["mode"] = r.mode
    if r.effacer_localisation:
        etat.pop("localisation", None)
        details["localisation"] = "effacee"
    elif r.localisation is not None:
        etat["localisation"] = r.localisation.model_dump()
        details["localisation"] = r.localisation.source  # jamais le lieu lui-même dans l'audit
    await matin.ecrire_etat(c.pool, etat)
    await audit.journaliser(c.pool, acteur=a.acteur, action="matin.reglages", details=details)
    return _reglages(c, etat)


@routeur.get("/lieux")
async def chercher_lieux(request: Request, q: str) -> dict[str, Any]:
    """Géocodage Open-Meteo d'une ville (pour choisir « la maison » dans les réglages)."""
    q = q.strip()
    if not 2 <= len(q) <= 100:
        raise HTTPException(422, "Nom de ville de 2 à 100 caractères attendu")
    try:
        return {"lieux": await _ctx(request).meteo.geocoder(q)}
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Géocodage Open-Meteo indisponible") from exc
