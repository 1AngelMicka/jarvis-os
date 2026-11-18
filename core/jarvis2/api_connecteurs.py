"""Routes des connecteurs d'IA et du conseil multi-IA."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import materiel
from .api_securite import appareil_courant
from .moteurs.base import ErreurMoteur
from .securite.permissions import ErreurAction

if TYPE_CHECKING:
    from .api import Contexte
    from .connecteurs import Connecteurs

routeur = APIRouter(prefix="/v1")


def gestion(request: Request) -> Connecteurs:
    c: Contexte = request.app.state.ctx
    if c.connecteurs is None:
        raise HTTPException(503, "Connecteurs indisponibles")
    return c.connecteurs


class Activation(BaseModel):
    accepte: bool = False  # case cochée par l'utilisateur (connecteurs à risque)
    version: str | None = Field(default=None, max_length=40)


class Cle(BaseModel):
    cle: str = Field(min_length=8, max_length=500)


class Inclusion(BaseModel):
    inclus: bool


class DemandeConseil(BaseModel):
    question: str = Field(min_length=1, max_length=50_000)
    conversation_id: UUID | None = None
    experts: list[str] | None = Field(default=None, max_length=6)
    synthese: str | None = Field(default=None, max_length=40)


async def _agir(appel: Any) -> dict[str, Any]:
    try:
        await appel
    except ErreurAction as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True}


@routeur.get("/connecteurs")
async def lister(request: Request) -> dict[str, Any]:
    return {"connecteurs": await gestion(request).decrire()}


@routeur.post("/connecteurs/{ident}/tester")
async def tester(request: Request, ident: str) -> dict[str, Any]:
    try:
        return await gestion(request).tester(ident)
    except ErreurAction as exc:
        raise HTTPException(404, str(exc)) from exc


@routeur.post("/connecteurs/{ident}/activer")
async def activer(request: Request, ident: str, corps: Activation) -> dict[str, Any]:
    return await _agir(gestion(request).activer(ident, appareil_courant(request), corps.accepte, corps.version))


@routeur.post("/connecteurs/{ident}/desactiver")
async def desactiver(request: Request, ident: str) -> dict[str, Any]:
    return await _agir(gestion(request).desactiver(ident, appareil_courant(request)))


@routeur.post("/connecteurs/{ident}/conseil")
async def conseil(request: Request, ident: str, corps: Inclusion) -> dict[str, Any]:
    return await _agir(gestion(request).conseil(ident, corps.inclus, appareil_courant(request)))


@routeur.put("/connecteurs/{ident}/cle")
async def definir_cle(request: Request, ident: str, corps: Cle) -> dict[str, Any]:
    """La clé va dans le coffre local ; elle n'est jamais renvoyée, journalisée ni stockée en base."""
    return await _agir(gestion(request).definir_cle(ident, corps.cle, appareil_courant(request)))


@routeur.delete("/connecteurs/{ident}/cle")
async def supprimer_cle(request: Request, ident: str) -> dict[str, Any]:
    return await _agir(gestion(request).supprimer_cle(ident, appareil_courant(request)))


@routeur.get("/materiel")
async def lire_materiel() -> dict[str, Any]:
    """RAM, mémoire vidéo et tailles de modèles locaux conseillées."""
    return await asyncio.to_thread(materiel.decrire)


@routeur.post("/conseil")
async def demander_conseil(request: Request, demande: DemandeConseil) -> StreamingResponse:
    from .api import sse

    c: Contexte = request.app.state.ctx
    if c.conseil is None:
        raise HTTPException(503, "Conseil indisponible")
    service = c.conseil

    async def flux() -> AsyncIterator[bytes]:
        with c.urgence.suivre():
            try:
                async for ev in service.repondre(
                    demande.question, demande.conversation_id, demande.experts, demande.synthese
                ):
                    yield sse(ev.type, ev.donnees)
            except (ErreurMoteur, ValueError, LookupError) as exc:
                yield sse("erreur", {"message": str(exc)})

    return StreamingResponse(flux(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
