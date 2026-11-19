"""Routes des connaissances : domaines (carte, fiches, questions, niveau, journal), extraction, révision.

🟢 partout : rien ne sort du PC sans passer par le routeur (IA locale pour un domaine privé), rien n'est détruit
(une fiche remplacée par une extraction reste dans les anciennes versions de la mémoire).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import connaissances
from .securite import audit
from .securite.appareils import Appareil

if TYPE_CHECKING:
    from .api import Contexte

routeur = APIRouter(prefix="/v1/connaissances")


def _ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


def _appareil(request: Request) -> Appareil:
    a: Appareil = request.state.appareil
    return a


def _propre(valeur: Any) -> Any:
    if isinstance(valeur, dict):
        return {k: _propre(v) for k, v in valeur.items()}
    if isinstance(valeur, list):
        return [_propre(v) for v in valeur]
    if isinstance(valeur, datetime):
        return valeur.isoformat()
    if isinstance(valeur, UUID):
        return str(valeur)
    return valeur


class NouveauDomaine(BaseModel):
    nom: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=1000)
    mots_cles: list[str] = Field(default_factory=list, max_length=20)
    prive: bool = False


class ModificationDomaine(BaseModel):
    nom: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    mots_cles: list[str] | None = Field(default=None, max_length=20)
    prive: bool | None = None


@routeur.get("")
async def domaines(request: Request) -> dict[str, Any]:
    c = _ctx(request)
    liste = await connaissances.lister(c.pool)
    for d in liste:
        d["en_cours"] = c.connaissances.en_cours(d["id"])
        d.pop("carte", None)  # la carte vient avec le détail
    return {"domaines": _propre(liste), "scientifique": c.scientifique is not None}


@routeur.post("")
async def creer(request: Request, corps: NouveauDomaine) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    try:
        ident = await connaissances.creer(c.pool, corps.nom, corps.description, corps.mots_cles, corps.prive)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await audit.journaliser(c.pool, acteur=a.acteur, action="connaissances.domaine_cree", cible=str(ident))
    # Les missions déjà faites sur ce sujet sont rattachées (l'extraction attend le bouton « Extraire »)
    await c.connaissances.rattacher(ident)
    return {"id": str(ident)}


@routeur.get("/evoques")
async def evoques(request: Request, q: str) -> dict[str, Any]:
    """Domaines nommés dans un texte (dialogue : proposer une révision)."""
    trouves = await connaissances.evoques(_ctx(request).pool, q[:4000])
    return {"domaines": [{"id": str(d["id"]), "nom": d["nom"], "niveau": d["niveau"]} for d in trouves]}


@routeur.get("/{ident}")
async def domaine(request: Request, ident: UUID) -> dict[str, Any]:
    c = _ctx(request)
    d = await connaissances.detail(c.pool, ident)
    if d is None:
        raise HTTPException(404, "Domaine introuvable")
    d["en_cours"] = c.connaissances.en_cours(ident)
    return _propre(d)  # type: ignore[no-any-return]


@routeur.patch("/{ident}")
async def modifier(request: Request, ident: UUID, corps: ModificationDomaine) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    try:
        d = await connaissances.modifier(
            c.pool, ident, nom=corps.nom, description=corps.description, mots_cles=corps.mots_cles, prive=corps.prive
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await audit.journaliser(c.pool, acteur=a.acteur, action="connaissances.domaine_modifie", cible=str(ident))
    return _propre(d)  # type: ignore[no-any-return]


@routeur.post("/{ident}/extraire")
async def extraire(request: Request, ident: UUID) -> dict[str, Any]:
    """Rattache les missions de recherche du domaine pas encore versées, puis extrait en arrière-plan."""
    c, a = _ctx(request), _appareil(request)
    if c.urgence.actif:
        raise HTTPException(423, "Arrêt d'urgence actif")
    try:
        ajoutees = await c.connaissances.lancer_extraction(ident)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    await audit.journaliser(c.pool, acteur=a.acteur, action="connaissances.extraction", cible=str(ident))
    return {"lancee": True, "rattachees": ajoutees}


@routeur.post("/{ident}/reviser")
async def reviser(request: Request, ident: UUID) -> dict[str, Any]:
    """Mission « revue » sur le domaine : questions de contrôle, score, lacunes, missions suggérées."""
    c, a = _ctx(request), _appareil(request)
    d = await connaissances.obtenir(c.pool, ident)
    if d is None:
        raise HTTPException(404, "Domaine introuvable")
    mission = await c.missions.lancer(
        "revue", f"Révision du domaine « {d['nom']} »", a.acteur, parametres={"domaine_id": str(ident)}
    )
    await audit.journaliser(
        c.pool,
        acteur=a.acteur,
        action="mission.lancee",
        cible=str(mission),
        details={"type": "revue", "domaine": str(ident)},
    )
    return {"id": str(mission)}
