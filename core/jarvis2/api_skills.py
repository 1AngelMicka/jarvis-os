"""Routes des skills SKILL.md (import, revue, approbation, empreinte) et des réglages du client MCP.

- `GET  /v1/skills`                         : skills importés (statut, confiance, capacités, empreintes)
- `GET  /v1/skills/{id}`                    : détail pour la revue (fichiers, détections, empreinte actuelle)
- `GET  /v1/skills/{id}/fichier?chemin=`    : texte d'un fichier du skill (revue ; jamais exécuté)
- `POST /v1/skills/importer/dossier`        : copie d'un dossier local choisi par l'utilisateur
- `POST /v1/skills/importer/archive?nom=`   : archive .zip envoyée par l'utilisateur (corps brut)
- `POST /v1/skills/{id}/approuver`          : demande 🟡 `skill.approuver` (empreinte revue + capacités cochées)
- `POST /v1/skills/{id}/executer`           : demande 🟡 `skill.executer`
- `POST /v1/skills/{id}/retirer`            : demande 🟡 `skill.retirer`
- `GET/PUT /v1/mcp/reglages`, `GET /v1/mcp/sessions`, `POST /v1/mcp/serveurs/{id}/relancer`,
  `GET /v1/mcp/outils/chercher?q=`, `GET /v1/mcp/outils/choix?q=` (outils qu'un message ferait proposer)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .agents.mcp import OUTILS_PAR_TOUR_MAX, ErreurMCP
from .agents.skills import DANGEREUSES, TAILLE_TOTALE_MAX, ErreurSkill, ServiceSkills
from .securite import audit
from .securite.appareils import Appareil
from .securite.permissions import ErreurAction

if TYPE_CHECKING:
    from .api import Contexte

routeur = APIRouter(prefix="/v1")
LECTURE_MAX = 200_000


def _ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


def _appareil(request: Request) -> Appareil:
    a: Appareil = request.state.appareil
    return a


def _skills(request: Request) -> ServiceSkills:
    s = _ctx(request).skills
    if s is None:
        raise HTTPException(404, "Skills indisponibles (aucun dossier des données)")
    return s


def _erreur(exc: Exception) -> HTTPException:
    message = str(exc)
    return HTTPException(404 if "introuvable" in message.lower() else 422, message)


# --- Skills -------------------------------------------------------------------------------------------------


class ImportDossier(BaseModel):
    chemin: str = Field(min_length=1, max_length=1000)


class Revue(BaseModel):
    capacites: list[str] = Field(default_factory=list, max_length=3)


class Execution(BaseModel):
    script: str = Field(min_length=1, max_length=300)
    arguments: list[str] = Field(default_factory=list, max_length=20)


@routeur.get("/skills")
async def lister_skills(request: Request) -> dict[str, Any]:
    c = _ctx(request)
    if c.skills is None:
        return {"skills": [], "capacites": DANGEREUSES}
    return {"skills": await c.skills.lister(), "capacites": DANGEREUSES}


@routeur.get("/skills/{ident}")
async def skill(request: Request, ident: UUID) -> dict[str, Any]:
    try:
        return await _skills(request).obtenir(ident)
    except ErreurSkill as exc:
        raise _erreur(exc) from exc


@routeur.get("/skills/{ident}/fichier")
async def fichier_skill(request: Request, ident: UUID, chemin: str) -> dict[str, Any]:
    """Lecture d'un fichier copié, pour la revue : texte seulement, borné, jamais interprété."""
    s = _skills(request)
    try:
        detail = await s.obtenir(ident)
    except ErreurSkill as exc:
        raise _erreur(exc) from exc
    connus = {f["chemin"] for f in detail["fichiers"]}
    if chemin not in connus:
        raise HTTPException(404, "Fichier inconnu dans ce skill")
    ligne = await s.pool.fetchrow("SELECT dossier FROM skills WHERE id = $1", ident)
    assert ligne is not None
    racine = Path(ligne["dossier"]).resolve()  # noqa: ASYNC240
    cible = (racine / chemin).resolve()
    if racine not in cible.parents or not cible.is_file():
        raise HTTPException(404, "Fichier absent")
    octets = cible.read_bytes()[:LECTURE_MAX]
    return {
        "chemin": chemin,
        "texte": octets.decode("utf-8", errors="replace"),
        "tronque": cible.stat().st_size > LECTURE_MAX,
    }


@routeur.post("/skills/importer/dossier")
async def importer_dossier(request: Request, corps: ImportDossier) -> dict[str, Any]:
    """🟢 : une copie inutilisable tant qu'elle n'est pas revue et approuvée (la source n'est que lue)."""
    try:
        return await _skills(request).importer_dossier(corps.chemin, _appareil(request).acteur)
    except ErreurSkill as exc:
        raise HTTPException(422, str(exc)) from exc


@routeur.post("/skills/importer/archive")
async def importer_archive(request: Request, nom: str = "archive.zip") -> dict[str, Any]:
    s = _skills(request)
    octets = b""
    async for morceau in request.stream():
        octets += morceau
        if len(octets) > 2 * TAILLE_TOTALE_MAX:
            raise HTTPException(413, "Archive trop grosse")
    if not octets:
        raise HTTPException(422, "Archive vide")
    try:
        return await s.importer_archive(octets, nom, _appareil(request).acteur)
    except ErreurSkill as exc:
        raise HTTPException(422, str(exc)) from exc


async def _demander(request: Request, action: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        return await _ctx(request).approbations.demander(action, params, _appareil(request))
    except ErreurAction as exc:
        raise HTTPException(422, str(exc)) from exc


@routeur.post("/skills/{ident}/approuver")
async def approuver_skill(request: Request, ident: UUID, corps: Revue) -> dict[str, Any]:
    """La demande porte l'empreinte exacte revue : un fichier changé avant le clic fait échouer l'approbation."""
    try:
        params = await _skills(request).preparer_approbation(ident, corps.capacites)
    except ErreurSkill as exc:
        raise _erreur(exc) from exc
    return await _demander(request, "skill.approuver", params)


@routeur.post("/skills/{ident}/executer")
async def executer_skill(request: Request, ident: UUID, corps: Execution) -> dict[str, Any]:
    try:
        detail = await _skills(request).obtenir(ident)
    except ErreurSkill as exc:
        raise _erreur(exc) from exc
    params = {"skill_id": str(ident), "nom": detail["nom"], "script": corps.script, "arguments": corps.arguments}
    return await _demander(request, "skill.executer", params)


@routeur.post("/skills/{ident}/retirer")
async def retirer_skill(request: Request, ident: UUID) -> dict[str, Any]:
    try:
        detail = await _skills(request).obtenir(ident)
    except ErreurSkill as exc:
        raise _erreur(exc) from exc
    return await _demander(request, "skill.retirer", {"skill_id": str(ident), "nom": detail["nom"]})


# --- Réglages et sessions MCP -------------------------------------------------------------------------------


class ReglagesMCP(BaseModel):
    max_outils: int | None = Field(default=None, ge=1, le=OUTILS_PAR_TOUR_MAX)
    par_le_sens: bool | None = None
    relance_auto: bool | None = None


@routeur.get("/mcp/reglages")
async def reglages_mcp(request: Request) -> dict[str, Any]:
    c = _ctx(request)
    return {"reglages": await c.outils_tour.reglages(), "max_par_tour": OUTILS_PAR_TOUR_MAX}


@routeur.put("/mcp/reglages")
async def regler_mcp(request: Request, corps: ReglagesMCP) -> dict[str, Any]:
    """🟢 : réglage local, journalisé."""
    c = _ctx(request)
    if c.mcp is None:
        raise HTTPException(404, "Aucun serveur MCP")
    changement = corps.model_dump(exclude_none=True)
    reglages = await c.mcp.regler(c.pool, changement)
    await audit.journaliser(c.pool, acteur=_appareil(request).acteur, action="mcp.regle", details=changement)
    return {"reglages": reglages, "max_par_tour": OUTILS_PAR_TOUR_MAX}


@routeur.get("/mcp/sessions")
async def sessions_mcp(request: Request) -> dict[str, Any]:
    c = _ctx(request)
    return {"sessions": c.mcp.sessions() if c.mcp is not None else []}


@routeur.post("/mcp/serveurs/{serveur}/relancer")
async def relancer_mcp(request: Request, serveur: str) -> dict[str, Any]:
    """🟢 : relance d'un serveur déclaré par l'utilisateur (lève l'état « en panne »)."""
    c = _ctx(request)
    if c.mcp is None:
        raise HTTPException(404, "Aucun serveur MCP")
    try:
        etat = await c.mcp.relancer(serveur)
    except ErreurMCP as exc:
        raise HTTPException(404 if "inconnu" in str(exc) else 502, str(exc)) from exc
    await audit.journaliser(c.pool, acteur=_appareil(request).acteur, action="mcp.relance", cible=serveur)
    return etat


@routeur.get("/mcp/outils/chercher")
async def chercher_outils(request: Request, q: str) -> dict[str, Any]:
    if len(q.strip()) < 2:
        raise HTTPException(422, "Requête trop courte")
    return {"outils": await _ctx(request).outils_tour.chercher(q[:300])}


@routeur.get("/mcp/outils/choix")
async def choix_outils(request: Request, q: str) -> dict[str, Any]:
    """Aperçu : outils qu'un message ferait proposer au modèle (moins de 12)."""
    return await _ctx(request).outils_tour.choisir(q[:2000])
