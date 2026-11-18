"""Routes des ateliers Claude Code : création, consignes, arrêt et reprise, autorisations en direct, fusion 🟡."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .ateliers.gestionnaire import ErreurAtelier, GestionnaireAteliers
from .securite import audit
from .securite.appareils import Appareil

if TYPE_CHECKING:
    from .api import Contexte

routeur = APIRouter(prefix="/v1")


def _ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


def _ateliers(request: Request) -> GestionnaireAteliers:
    g = _ctx(request).ateliers
    if g is None:
        raise HTTPException(404, "Ateliers indisponibles")
    return g


def _appareil(request: Request) -> Appareil:
    a: Appareil = request.state.appareil
    return a


def _propre(ligne: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v.isoformat() if isinstance(v, datetime) else str(v) if isinstance(v, UUID) else v for k, v in ligne.items()
    }


class Creation(BaseModel):
    projet: str = Field(min_length=1, max_length=40)
    nom: str = Field(min_length=1, max_length=120)


class Consigne(BaseModel):
    consigne: str = Field(min_length=1, max_length=50_000)
    reprendre: bool = False


class Reponse(BaseModel):
    accorde: bool


class DemandeOutil(BaseModel):
    tool_name: str = Field(max_length=200)
    input: dict[str, Any] = Field(default_factory=dict)


@routeur.get("/ateliers")
async def lister(request: Request) -> dict[str, Any]:
    g = _ateliers(request)
    return {
        "projets": [{"id": p.id, "nom": p.nom} for p in g.projets.values()],
        "ateliers": [{**_propre(a), "actif": a["id"] in g.processus} for a in await g.lister()],
        "attentes": g.en_attente(),
    }


@routeur.post("/ateliers")
async def creer(request: Request, corps: Creation) -> dict[str, Any]:
    g, a = _ateliers(request), _appareil(request)
    try:
        atelier = await g.creer(corps.projet, corps.nom, a.acteur)
    except ErreurAtelier as exc:
        raise HTTPException(409, str(exc)) from exc
    await audit.journaliser(_ctx(request).pool, acteur=a.acteur, action="atelier.cree", cible=str(atelier["id"]))
    return _propre(atelier)


@routeur.get("/ateliers/{ident}/evenements")
async def evenements(request: Request, ident: UUID, apres: int = 0) -> dict[str, Any]:
    g = _ateliers(request)
    return {"evenements": [_propre(e) for e in await g.evenements(ident, apres)], "attentes": g.en_attente(ident)}


@routeur.post("/ateliers/{ident}/consigne")
async def consigne(request: Request, ident: UUID, corps: Consigne) -> dict[str, Any]:
    g, a = _ateliers(request), _appareil(request)
    connecteurs = _ctx(request).connecteurs
    if connecteurs is not None and connecteurs.conditions_a_accepter("claude_code"):
        raise HTTPException(409, "Les ateliers utilisent votre abonnement Claude : acceptez d'abord l'avertissement Claude Code")
    try:
        await g.lancer(ident, corps.consigne, corps.reprendre)
    except ErreurAtelier as exc:
        raise HTTPException(409, str(exc)) from exc
    await audit.journaliser(_ctx(request).pool, acteur=a.acteur, action="atelier.consigne", cible=str(ident))
    return {"lance": True}


@routeur.post("/ateliers/{ident}/arreter")
async def arreter(request: Request, ident: UUID) -> dict[str, Any]:
    g, a = _ateliers(request), _appareil(request)
    arrete = await g.arreter(ident)
    await audit.journaliser(_ctx(request).pool, acteur=a.acteur, action="atelier.arrete", cible=str(ident))
    return {"arrete": arrete}


@routeur.post("/ateliers/{ident}/abandonner")
async def abandonner(request: Request, ident: UUID) -> dict[str, Any]:
    g, a = _ateliers(request), _appareil(request)
    try:
        await g.abandonner(ident)
    except ErreurAtelier as exc:
        raise HTTPException(409, str(exc)) from exc
    await audit.journaliser(_ctx(request).pool, acteur=a.acteur, action="atelier.abandonne", cible=str(ident))
    return {"abandonne": True}


@routeur.post("/ateliers/attentes/{attente}")
async def repondre(request: Request, attente: str, corps: Reponse) -> dict[str, Any]:
    g, a = _ateliers(request), _appareil(request)
    if not g.repondre(attente, corps.accorde):
        raise HTTPException(404, "Demande expirée ou déjà traitée")
    await audit.journaliser(
        _ctx(request).pool,
        acteur=a.acteur,
        action="atelier.outil_accorde" if corps.accorde else "atelier.outil_refuse",
        niveau="jaune" if corps.accorde else "vert",
        cible=attente,
    )
    return {"accorde": corps.accorde}


@routeur.post("/ateliers-autorisation")
async def autorisation(request: Request, corps: DemandeOutil) -> dict[str, Any]:
    """Appelée par l'outil d'autorisation de Claude Code (jeton propre à l'exécution, PC seulement)."""
    if not (request.client and request.client.host in ("127.0.0.1", "::1")):
        raise HTTPException(403, "Réservé au PC")
    jeton = request.headers.get("x-atelier-jeton", "")
    return await _ateliers(request).autoriser(jeton, corps.tool_name, corps.input)
