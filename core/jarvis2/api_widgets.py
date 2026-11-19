"""Routes des widgets épinglés dans le HUD (phase 14, D 16) : lister, épingler (fragment validé de nouveau), retirer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import widgets
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


class NouveauWidget(BaseModel):
    titre: str = Field(default="", max_length=200)
    html: str = Field(min_length=1, max_length=2 * widgets.TAILLE_MAX_FRAGMENT)


@routeur.get("/widgets")
async def lister(request: Request) -> dict[str, Any]:
    return {"widgets": await widgets.lister(_ctx(request).pool)}


@routeur.post("/widgets")
async def epingler(request: Request, corps: NouveauWidget) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    try:
        carte, nouveau = await widgets.epingler(c.pool, corps.titre, corps.html)
    except widgets.ErreurWidget as exc:
        raise HTTPException(422, str(exc)) from exc
    if nouveau:  # le titre seulement : le contenu peut être personnel
        await audit.journaliser(c.pool, acteur=a.acteur, action="widgets.epingler", details={"titre": carte["titre"]})
    return {"widget": carte, "nouveau": nouveau}


@routeur.delete("/widgets/{ident}")
async def retirer(request: Request, ident: UUID) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    titre = await widgets.retirer(c.pool, ident)
    if titre is None:
        raise HTTPException(404, "Widget introuvable")
    await audit.journaliser(c.pool, acteur=a.acteur, action="widgets.retirer", details={"titre": titre})
    return {"retire": str(ident)}
