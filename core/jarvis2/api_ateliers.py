"""Routes des ateliers Claude Code : création, consignes, pause, arrêt et reprise, relance, modèle, clôture,
conflits de fichiers, autorisations en direct, fusion 🟡 ; veille (lecture seule) des sessions Claude Code."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .ateliers.gestionnaire import MODELES, ErreurAtelier, GestionnaireAteliers
from .ateliers.veille import VeilleClaudeCode
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
    modele: str | None = Field(default=None, max_length=80)


class ChoixModele(BaseModel):
    modele: str | None = Field(default=None, max_length=80)


class Cloture(BaseModel):
    notes: str = Field(default="", max_length=10_000)


class ReglagesVeille(BaseModel):
    actif: bool | None = None
    voix: bool | None = None
    notification: bool | None = None


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
    conflits = await g.conflits()
    return {
        "projets": [{"id": p.id, "nom": p.nom} for p in g.projets.values()],
        "modeles": [{"id": i, "nom": n} for i, n in MODELES],
        "ateliers": [
            {
                **_propre(a),
                "actif": a["id"] in g.processus or a["id"] in g.taches,
                "en_pause": g.en_pause(a["id"]),
                "conflits": conflits.get(str(a["id"]), []),
            }
            for a in await g.lister()
        ],
        "attentes": g.en_attente(),
    }


@routeur.post("/ateliers")
async def creer(request: Request, corps: Creation) -> dict[str, Any]:
    g, a = _ateliers(request), _appareil(request)
    try:
        atelier = await g.creer(corps.projet, corps.nom, a.acteur, corps.modele)
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
        raise HTTPException(
            409, "Les ateliers utilisent votre abonnement Claude : acceptez d'abord l'avertissement Claude Code"
        )
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


async def _piloter(request: Request, ident: UUID, action: str) -> dict[str, Any]:
    g, a = _ateliers(request), _appareil(request)
    try:
        if action == "pause":
            fait = await g.mettre_en_pause(ident)
        elif action == "reprise":
            fait = await g.reprendre(ident)
        else:
            connecteurs = _ctx(request).connecteurs
            if connecteurs is not None and connecteurs.conditions_a_accepter("claude_code"):
                raise HTTPException(409, "Acceptez d'abord l'avertissement Claude Code")
            await g.relancer(ident)
            fait = True
    except ErreurAtelier as exc:
        raise HTTPException(409, str(exc)) from exc
    if fait:
        await audit.journaliser(_ctx(request).pool, acteur=a.acteur, action=f"atelier.{action}", cible=str(ident))
    return {"fait": fait}


@routeur.post("/ateliers/{ident}/pause")
async def pause(request: Request, ident: UUID) -> dict[str, Any]:
    return await _piloter(request, ident, "pause")


@routeur.post("/ateliers/{ident}/reprendre")
async def reprendre(request: Request, ident: UUID) -> dict[str, Any]:
    return await _piloter(request, ident, "reprise")


@routeur.post("/ateliers/{ident}/relancer")
async def relancer(request: Request, ident: UUID) -> dict[str, Any]:
    return await _piloter(request, ident, "relance")


@routeur.put("/ateliers/{ident}/modele")
async def modele(request: Request, ident: UUID, corps: ChoixModele) -> dict[str, Any]:
    g, a = _ateliers(request), _appareil(request)
    try:
        atelier = await g.choisir_modele(ident, corps.modele)
    except ErreurAtelier as exc:
        raise HTTPException(409, str(exc)) from exc
    await audit.journaliser(
        _ctx(request).pool, acteur=a.acteur, action="atelier.modele", cible=str(ident), details={"modele": corps.modele}
    )
    return _propre(atelier)


@routeur.post("/ateliers/{ident}/cloturer")
async def cloturer(request: Request, ident: UUID, corps: Cloture) -> dict[str, Any]:
    g, a = _ateliers(request), _appareil(request)
    try:
        atelier = await g.cloturer(ident, corps.notes)
    except ErreurAtelier as exc:
        raise HTTPException(409, str(exc)) from exc
    await audit.journaliser(_ctx(request).pool, acteur=a.acteur, action="atelier.cloture", cible=str(ident))
    return _propre(atelier)


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


# --- Veille des sessions Claude Code de l'utilisateur (lecture seule) ------------------------------------------


def _veille(request: Request) -> VeilleClaudeCode:
    v = _ctx(request).veille
    if v is None:
        raise HTTPException(404, "Veille indisponible")
    return v


@routeur.get("/veille-claude")
async def veille(request: Request, apres: int = 0) -> dict[str, Any]:
    v = _veille(request)
    disponible = getattr(v.source, "disponible", None)
    return {
        "reglages": dict(v.reglages),
        "disponible": bool(disponible()) if callable(disponible) else True,
        "sessions": [s.en_dict() for s in v.sessions] if v.actif else [],
        "alertes": v.alertes_apres(apres) if v.actif else [],
        "dernier": v.dernier_id,  # le Core redémarré recompte à partir de 0
        "maj_le": v.maj_le.isoformat() if v.maj_le else None,
    }


@routeur.put("/veille-claude")
async def regler_veille(request: Request, corps: ReglagesVeille) -> dict[str, Any]:
    v, a = _veille(request), _appareil(request)
    avant = v.actif
    reglages = await v.regler(actif=corps.actif, voix=corps.voix, notification=corps.notification)
    if reglages["actif"] != avant:
        await audit.journaliser(
            _ctx(request).pool,
            acteur=a.acteur,
            action="veille_claude.activee" if reglages["actif"] else "veille_claude.desactivee",
        )
    if reglages["actif"] and not avant:
        await v.sonder()  # premier état tout de suite
    return {"reglages": reglages}
