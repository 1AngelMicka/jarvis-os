"""Routes de l'indicateur « nouvelle version » (Réglages › Appareils › Version et mises à jour).

- `GET /v1/mises-a-jour` : version installée, dernière publiée, nouvelle ou non, notes (texte brut), page de la
  version, date de vérification, vérification active. Interroge GitHub au plus une fois par jour, si c'est actif.
- `PUT /v1/mises-a-jour` : activer ou désactiver la vérification quotidienne (journalisé).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from .securite import audit

if TYPE_CHECKING:
    from .api import Contexte

routeur = APIRouter(prefix="/v1")


class Reglage(BaseModel):
    verifier: bool


def _ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


@routeur.get("/mises-a-jour")
async def lire(request: Request) -> dict[str, Any]:
    return await _ctx(request).mises_a_jour.decrire()


@routeur.put("/mises-a-jour")
async def regler(request: Request, corps: Reglage) -> dict[str, Any]:
    c = _ctx(request)
    avant = await c.mises_a_jour.actif()
    etat = await c.mises_a_jour.regler(corps.verifier)
    if corps.verifier != avant:
        await audit.journaliser(
            c.pool,
            acteur=request.state.appareil.acteur,
            action="mises_a_jour.activees" if corps.verifier else "mises_a_jour.desactivees",
        )
    return etat
