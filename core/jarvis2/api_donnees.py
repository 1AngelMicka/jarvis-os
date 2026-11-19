"""Route « Où partent mes données » : la carte des flux, générée depuis la configuration réelle."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request

from . import flux_donnees

if TYPE_CHECKING:
    from .api import Contexte
    from .config import Parametres

routeur = APIRouter(prefix="/v1/donnees")


@routeur.get("/flux")
async def lire_flux(request: Request) -> dict[str, Any]:
    """Fonction → service contacté, ce qui part, local ou non, où le désactiver. Aucun secret, adresse ni lieu."""
    c: Contexte = request.app.state.ctx
    p: Parametres = request.app.state.parametres
    return await flux_donnees.decrire(c, p)
