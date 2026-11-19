"""Routes de l'amélioration continue : suggestions, atelier, aperçu, tests, demandes de mise en service et de retour
arrière (🟡, exécutées par la file d'approbations). Tout est journalisé ; l'arrêt d'urgence refuse toute écriture."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .ameliorations import ErreurAmelioration, ServiceAmeliorations
from .securite import audit
from .securite.appareils import Appareil
from .securite.permissions import ErreurAction

if TYPE_CHECKING:
    from .api import Contexte

routeur = APIRouter(prefix="/v1/ameliorations")


def _ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


def _service(request: Request) -> ServiceAmeliorations:
    return _ctx(request).ameliorations


def _appareil(request: Request) -> Appareil:
    a: Appareil = request.state.appareil
    return a


def _propre(ligne: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v.isoformat() if isinstance(v, datetime) else str(v) if isinstance(v, UUID) else v for k, v in ligne.items()
    }


class Suggestion(BaseModel):
    projet: str = Field(min_length=1, max_length=40)
    titre: str = Field(min_length=1, max_length=200)
    raison: str = Field(min_length=1, max_length=2000)
    description: str = Field(default="", max_length=10_000)
    # « jarvis » : suggestion proposée par JARVIS sous une réponse, validée d'un clic par l'utilisateur
    origine: Literal["jarvis", "utilisateur"] = "utilisateur"


class OuvertureAtelier(BaseModel):
    lancer: bool = True  # envoyer tout de suite la consigne à Claude Code


async def _journaliser(request: Request, action: str, cible: UUID, details: dict[str, Any] | None = None) -> None:
    await audit.journaliser(
        _ctx(request).pool, acteur=_appareil(request).acteur, action=action, cible=str(cible), details=details
    )


@routeur.get("")
async def lister(request: Request) -> dict[str, Any]:
    s = _service(request)
    return {
        "disponible": s.ateliers is not None,
        "projets": s.projets(),
        "ameliorations": [_propre(a) for a in await s.lister()],
    }


@routeur.post("")
async def proposer(request: Request, corps: Suggestion) -> dict[str, Any]:
    s, a = _service(request), _appareil(request)
    try:
        amelioration = await s.proposer(
            corps.projet, corps.titre, corps.raison, corps.description, corps.origine, a.acteur
        )
    except ErreurAmelioration as exc:
        raise HTTPException(409, str(exc)) from exc
    await _journaliser(request, "amelioration.proposee", amelioration["id"], {"origine": corps.origine})
    return _propre(amelioration)


@routeur.get("/{ident}")
async def obtenir(request: Request, ident: UUID) -> dict[str, Any]:
    a = await _service(request).obtenir(ident)
    if a is None:
        raise HTTPException(404, "Amélioration introuvable")
    return _propre(a)


@routeur.post("/{ident}/atelier")
async def ouvrir_atelier(request: Request, ident: UUID, corps: OuvertureAtelier) -> dict[str, Any]:
    s = _service(request)
    connecteurs = _ctx(request).connecteurs
    if corps.lancer and connecteurs is not None and connecteurs.conditions_a_accepter("claude_code"):
        raise HTTPException(
            409, "Les ateliers utilisent votre abonnement Claude : acceptez d'abord l'avertissement Claude Code"
        )
    try:
        amelioration = await s.ouvrir_atelier(ident, _appareil(request).acteur, corps.lancer)
    except ErreurAmelioration as exc:
        raise HTTPException(409, str(exc)) from exc
    await _journaliser(request, "amelioration.atelier", ident, {"atelier": str(amelioration["atelier_id"])})
    return _propre(amelioration)


@routeur.get("/{ident}/apercu")
async def apercu(request: Request, ident: UUID) -> dict[str, Any]:
    try:
        return await _service(request).apercu(ident)
    except ErreurAmelioration as exc:
        raise HTTPException(409, str(exc)) from exc


@routeur.post("/{ident}/tests")
async def tester(request: Request, ident: UUID) -> dict[str, Any]:
    try:
        await _service(request).tester(ident)
    except ErreurAmelioration as exc:
        raise HTTPException(409, str(exc)) from exc
    await _journaliser(request, "amelioration.tests", ident)
    return {"lance": True}


@routeur.post("/{ident}/rejeter")
async def rejeter(request: Request, ident: UUID) -> dict[str, Any]:
    try:
        amelioration = await _service(request).rejeter(ident)
    except ErreurAmelioration as exc:
        raise HTTPException(409, str(exc)) from exc
    await _journaliser(request, "amelioration.rejetee", ident)
    return _propre(amelioration)


@routeur.post("/{ident}/mise-en-service")
async def demander_mise_en_service(request: Request, ident: UUID) -> dict[str, Any]:
    """Crée la demande 🟡 (paramètres et empreinte calculés par le Core, jamais par le client ni par le modèle)."""
    c = _ctx(request)
    try:
        parametres = await c.ameliorations.parametres_mise_en_service(ident)
        return await c.approbations.demander("amelioration.mettre_en_service", parametres, _appareil(request))
    except (ErreurAmelioration, ErreurAction) as exc:
        raise HTTPException(409, str(exc)) from exc


@routeur.post("/{ident}/retour")
async def demander_retour(request: Request, ident: UUID) -> dict[str, Any]:
    c = _ctx(request)
    a = await c.ameliorations.obtenir(ident)
    if a is None:
        raise HTTPException(404, "Amélioration introuvable")
    if a["statut"] != "en_service":
        raise HTTPException(409, "Seule une amélioration en service peut être retirée")
    parametres = {"amelioration_id": str(ident), "titre": a["titre"], "projet": a["projet"]}
    try:
        return await c.approbations.demander("amelioration.revenir", parametres, _appareil(request))
    except ErreurAction as exc:
        raise HTTPException(409, str(exc)) from exc
