"""Routes du profil guidé : sections, questions, réponses (versées en mémoire), progression et reprise."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import profil
from .securite import audit
from .securite.appareils import Appareil

if TYPE_CHECKING:
    from .api import Contexte

routeur = APIRouter(prefix="/v1/profil")


def _ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


def _appareil(request: Request) -> Appareil:
    a: Appareil = request.state.appareil
    return a


class Ecriture(BaseModel):
    texte: str = Field(max_length=profil.LONGUEUR_MAX)
    prive: bool | None = None
    commentaire: str | None = Field(default=None, max_length=profil.COMMENTAIRE_MAX)


def _question(q: profil.Question, s: profil.Section, reponses: dict[str, profil.Reponse]) -> dict[str, Any]:
    r = reponses.get(q.id)
    return {
        "id": q.id,
        "section": s.id,
        "texte": q.texte,
        "aide": q.aide,
        "reponse": r.en_dict() if r and r.texte.strip() else None,
    }


@routeur.get("")
async def etat(request: Request) -> dict[str, Any]:
    """Progression par section et point de reprise."""
    return profil.progression(await profil.lister(_ctx(request).pool))


@routeur.get("/sections")
async def sections(request: Request) -> dict[str, Any]:
    return {"sections": profil.progression(await profil.lister(_ctx(request).pool))["sections"]}


@routeur.get("/sections/{ident}")
async def section(request: Request, ident: str) -> dict[str, Any]:
    s = profil.PAR_SECTION.get(ident)
    if s is None:
        raise HTTPException(404, f"Section inconnue : « {ident} »")
    reponses = await profil.lister(_ctx(request).pool)
    return {**s.en_dict(), "questions": [_question(q, s, reponses) for q in s.questions]}


@routeur.get("/questions")
async def questions(request: Request) -> dict[str, Any]:
    reponses = await profil.lister(_ctx(request).pool)
    return {"questions": [_question(q, s, reponses) for s in profil.SECTIONS for q in s.questions]}


@routeur.get("/reponses")
async def reponses(request: Request) -> dict[str, Any]:
    """Toutes les réponses, y compris celles héritées de JARVIS v1 (questions qui ne sont plus posées)."""
    liste = await profil.lister(_ctx(request).pool)
    return {
        "reponses": [
            {**r.en_dict(), "heritee": qid not in profil.PAR_QUESTION}
            for qid, r in sorted(liste.items())
            if r.texte.strip()
        ]
    }


@routeur.put("/reponses/{question_id}")
async def repondre(request: Request, question_id: str, corps: Ecriture) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    try:
        r, change = await profil.repondre(
            c.pool,
            question_id,
            corps.texte,
            prive=corps.prive,
            commentaire=corps.commentaire,
            encodeur=c.memoire.encodeur if c.memoire else None,
        )
    except profil.ErreurProfil as exc:
        code = 404 if question_id not in profil.PAR_QUESTION else 422
        raise HTTPException(code, str(exc)) from exc
    if change:
        # Jamais le contenu dans le journal : seulement la question et la confidentialité.
        await audit.journaliser(
            c.pool, acteur=a.acteur, action="profil.reponse", cible=question_id, details={"prive": r.prive}
        )
    return {"reponse": r.en_dict(), "modifiee": change}


@routeur.delete("/reponses/{question_id}")
async def retirer(request: Request, question_id: str) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    if not await profil.retirer(c.pool, question_id):
        raise HTTPException(404, "Aucune réponse à cette question")
    await audit.journaliser(c.pool, acteur=a.acteur, action="profil.reponse_retiree", cible=question_id)
    return {"retiree": question_id}


@routeur.get("/reponses/{question_id}/historique")
async def historique(request: Request, question_id: str) -> dict[str, Any]:
    return {"versions": await profil.historique(_ctx(request).pool, question_id)}
