"""Routes des chantiers (tâches suivies, sans doublon, « C'est fait ») et du panneau Activité (ce qui tourne)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import chantiers, creations
from .securite import audit
from .securite.appareils import Appareil

if TYPE_CHECKING:
    from .api import Contexte

routeur = APIRouter(prefix="/v1")

StatutModifiable = Literal["propose", "a_faire", "en_cours", "en_attente_utilisateur", "bloque"]


def _ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


def _appareil(request: Request) -> Appareil:
    a: Appareil = request.state.appareil
    return a


def _propre(ligne: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v.isoformat() if isinstance(v, datetime) else str(v) if isinstance(v, UUID) else v for k, v in ligne.items()
    }


class Etape(BaseModel):
    titre: str = Field(min_length=1, max_length=300)
    fait: bool = False


class NouveauChantier(BaseModel):
    titre: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    categorie: str = Field(default="general", min_length=1, max_length=60)
    etapes: list[Etape] = Field(default_factory=list, max_length=100)
    priorite: int = Field(default=2, ge=1, le=3)


class ModifChantier(BaseModel):
    titre: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    progression: int | None = Field(default=None, ge=0, le=100)
    etapes: list[Etape] | None = Field(default=None, max_length=100)
    statut: StatutModifiable | None = None
    priorite: int | None = Field(default=None, ge=1, le=3)


def _erreur(exc: chantiers.ErreurChantier) -> HTTPException:
    return HTTPException(404 if "introuvable" in str(exc) else 409, str(exc))


@routeur.get("/chantiers")
async def lister(request: Request, statut: str = "ouverts", limite: int = 100) -> dict[str, Any]:
    try:
        liste = await chantiers.lister(_ctx(request).pool, statut, limite)
    except chantiers.ErreurChantier as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"chantiers": liste}


@routeur.get("/chantiers/{ident}")
async def obtenir(request: Request, ident: UUID) -> dict[str, Any]:
    c = await chantiers.obtenir(_ctx(request).pool, ident)
    if c is None:
        raise HTTPException(404, "Chantier introuvable")
    return c


@routeur.post("/chantiers")
async def creer(request: Request, corps: NouveauChantier) -> dict[str, Any]:
    """Crée un chantier, ou renvoie (`cree: false`) le chantier ouvert qui a déjà le même sens."""
    c, a = _ctx(request), _appareil(request)
    try:
        chantier, cree = await chantiers.creer(
            c.pool,
            corps.titre,
            a.acteur,
            description=corps.description,
            categorie=corps.categorie,
            etapes=[e.model_dump() for e in corps.etapes],
            priorite=corps.priorite,
        )
    except chantiers.ErreurChantier as exc:
        raise _erreur(exc) from exc
    if cree:
        await audit.journaliser(c.pool, acteur=a.acteur, action="chantier.cree", cible=chantier["id"])
    return {"chantier": chantier, "cree": cree}


@routeur.patch("/chantiers/{ident}")
async def modifier(request: Request, ident: UUID, corps: ModifChantier) -> dict[str, Any]:
    c = _ctx(request)
    try:
        chantier = await chantiers.modifier(
            c.pool,
            ident,
            titre=corps.titre,
            description=corps.description,
            progression=corps.progression,
            etapes=[e.model_dump() for e in corps.etapes] if corps.etapes is not None else None,
            statut=corps.statut,
            priorite=corps.priorite,
        )
    except chantiers.ErreurChantier as exc:
        raise _erreur(exc) from exc
    return chantier


@routeur.post("/chantiers/{ident}/terminer")
async def terminer(request: Request, ident: UUID) -> dict[str, Any]:
    """« C'est fait » : les jumeaux encore ouverts sont abandonnés (« Doublon de … »)."""
    c, a = _ctx(request), _appareil(request)
    try:
        chantier, doublons = await chantiers.terminer(c.pool, ident)
    except chantiers.ErreurChantier as exc:
        raise _erreur(exc) from exc
    await audit.journaliser(
        c.pool,
        acteur=a.acteur,
        action="chantier.termine",
        cible=str(ident),
        details={"doublons_abandonnes": [d["id"] for d in doublons]},
    )
    return {"chantier": chantier, "doublons_abandonnes": len(doublons)}


@routeur.post("/chantiers/{ident}/rouvrir")
async def rouvrir(request: Request, ident: UUID) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    try:
        chantier = await chantiers.rouvrir(c.pool, ident)
    except chantiers.ErreurChantier as exc:
        raise _erreur(exc) from exc
    await audit.journaliser(c.pool, acteur=a.acteur, action="chantier.rouvert", cible=str(ident))
    return chantier


# --- Activité -------------------------------------------------------------------------------------------------


@routeur.get("/activite")
async def activite(request: Request) -> dict[str, Any]:
    """Ce qui tourne, en un appel léger : chantiers ouverts, missions en cours ou récentes, ateliers ouverts,
    dernières créations."""
    c = _ctx(request)
    limite_recente = datetime.now(UTC) - timedelta(hours=24)

    def recente(m: dict[str, Any]) -> bool:
        fin = m.get("termine_le")
        if isinstance(fin, str):
            fin = datetime.fromisoformat(fin)
        return isinstance(fin, datetime) and (fin if fin.tzinfo else fin.replace(tzinfo=UTC)) >= limite_recente

    missions = [m for m in await c.missions.lister(20) if m["statut"] in ("en_file", "en_cours") or recente(m)][:8]
    ateliers: list[dict[str, Any]] = []
    attentes = 0
    if c.ateliers is not None:
        g = c.ateliers
        ateliers = [
            {**a, "actif": a["id"] in g.processus}
            for a in await g.lister()
            if a["statut"] in ("pret", "en_cours", "arrete", "erreur")
        ][:8]
        attentes = len(g.en_attente())
    ouverts = await chantiers.lister(c.pool, "ouverts", 30)
    recentes = (await creations.lister(c.pool))[:5]
    return {
        "chantiers": ouverts,
        "missions": [
            _propre({k: m[k] for k in ("id", "type", "objectif", "statut", "progression", "cree_le", "termine_le")})
            for m in missions
        ],
        "ateliers": [
            _propre({k: a[k] for k in ("id", "projet", "nom", "statut", "actif", "maj_le")}) for a in ateliers
        ],
        "attentes_ateliers": attentes,
        "creations": [_propre({k: x[k] for k in ("id", "titre", "version_courante", "maj_le")}) for x in recentes],
        "en_cours": sum(1 for m in missions if m["statut"] in ("en_file", "en_cours"))
        + sum(1 for a in ateliers if a["actif"]),
    }
