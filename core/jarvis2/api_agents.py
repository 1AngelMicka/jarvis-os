"""Routes des agents : recettes planifiées, missions, outils MCP."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .agents.mcp import ErreurMCP
from .securite import audit
from .securite.appareils import Appareil

if TYPE_CHECKING:
    from .api import Contexte

routeur = APIRouter(prefix="/v1")


def _ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


def _appareil(request: Request) -> Appareil:
    a: Appareil = request.state.appareil
    return a


def _iso(valeur: Any) -> Any:
    return valeur.isoformat() if isinstance(valeur, datetime) else str(valeur) if isinstance(valeur, UUID) else valeur


def _propre(ligne: dict[str, Any]) -> dict[str, Any]:
    return {k: _iso(v) for k, v in ligne.items()}


# --- Recettes -----------------------------------------------------------------------------------------------


@routeur.get("/recettes")
async def recettes(request: Request) -> dict[str, Any]:
    c = _ctx(request)
    if c.planificateur is None:
        return {"dossier": None, "recettes": [], "erreurs": []}
    liste, erreurs = c.planificateur.recettes()
    maintenant = datetime.now(UTC)
    cartes = []
    for r in liste:
        derniere = await c.planificateur.derniere(r.id)
        reference = derniere["debut"] if derniere else c.planificateur.depart
        cartes.append(
            {
                **r.en_dict(),
                "prochaine": r.prochaine(max(reference, maintenant)).isoformat() if r.active else None,
                "en_cours": r.id in c.planificateur.en_cours,
                "derniere": _propre(derniere) if derniere else None,
            }
        )
    return {"dossier": str(c.planificateur.dossier), "recettes": cartes, "erreurs": erreurs}


@routeur.post("/recettes/{ident}/lancer")
async def lancer_recette(request: Request, ident: str) -> dict[str, Any]:
    """🟢 : une recette ne fait que demander une réponse ; elle tourne en tâche de fond."""
    c, a = _ctx(request), _appareil(request)
    if c.planificateur is None:
        raise HTTPException(404, "Aucun dossier de recettes")
    recette = next((r for r in c.planificateur.recettes()[0] if r.id == ident), None)
    if recette is None:
        raise HTTPException(404, f"Recette inconnue : « {ident} »")
    if ident in c.planificateur.en_cours:
        raise HTTPException(409, "Cette recette est déjà en cours")
    await audit.journaliser(c.pool, acteur=a.acteur, action="recette.lancee", cible=ident)
    asyncio.get_running_loop().create_task(c.planificateur.executer(recette, "manuel"))
    return {"lancee": ident}


# --- Missions -----------------------------------------------------------------------------------------------


class DemandeMission(BaseModel):
    type: Literal["recherche", "brainstorm", "revue"]
    objectif: str = Field(min_length=3, max_length=4000)
    scientifique: bool = True  # recherche : bases scientifiques en plus du web
    domaine_id: UUID | None = None  # domaine de connaissance (revue : sa révision ; recherche : l'enrichit)


@routeur.get("/missions")
async def missions(request: Request) -> dict[str, Any]:
    c = _ctx(request)
    return {
        "missions": [_propre(m) for m in await c.missions.lister()],
        "recherche_web": c.recherche.disponible,
        "scientifique": c.scientifique.noms if c.scientifique is not None else [],
    }


@routeur.get("/missions/{ident}")
async def mission(request: Request, ident: UUID) -> dict[str, Any]:
    m = await _ctx(request).missions.obtenir(ident)
    if m is None:
        raise HTTPException(404, "Mission introuvable")
    return _propre(m)


@routeur.post("/missions")
async def lancer_mission(request: Request, corps: DemandeMission) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    parametres: dict[str, Any] = {"scientifique": corps.scientifique}
    if corps.domaine_id is not None:
        from .connaissances import obtenir

        if await obtenir(c.pool, corps.domaine_id) is None:
            raise HTTPException(404, "Domaine introuvable")
        parametres["domaine_id"] = str(corps.domaine_id)
    ident = await c.missions.lancer(corps.type, corps.objectif, a.acteur, parametres=parametres)
    await audit.journaliser(
        c.pool, acteur=a.acteur, action="mission.lancee", cible=str(ident), details={"type": corps.type}
    )
    return {"id": str(ident)}


# --- Outils MCP ---------------------------------------------------------------------------------------------


class Activation(BaseModel):
    actif: bool


@routeur.get("/mcp/outils")
async def outils_mcp(request: Request) -> dict[str, Any]:
    c = _ctx(request)
    if c.mcp is None:
        return {"serveurs": []}
    return {"serveurs": await c.mcp.lister(c.pool)}


@routeur.post("/mcp/outils/{serveur}/{outil}/actif")
async def activer_outil(request: Request, serveur: str, outil: str, corps: Activation) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    if c.mcp is None:
        raise HTTPException(404, "Aucun serveur MCP")
    try:
        await c.mcp.activer(c.pool, serveur, outil, corps.actif)
    except ErreurMCP as exc:
        raise HTTPException(404, str(exc)) from exc
    await audit.journaliser(
        c.pool,
        acteur=a.acteur,
        action="mcp.outil_active" if corps.actif else "mcp.outil_desactive",
        niveau="jaune" if corps.actif else "vert",
        cible=f"{serveur}/{outil}",
    )
    return {"serveur": serveur, "outil": outil, "actif": corps.actif}
