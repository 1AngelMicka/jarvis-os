"""Routes des ressources et du contrôle du PC (lot J) : lecture seulement.

- `GET /v1/pc/ressources` : CPU, RAM, GPU, VRAM, courbe sur 10 min, alertes, Ollama (modèles chargés), mode jeu.
- `GET /v1/pc/etat`       : volume, luminosité, média en cours, fenêtres, mode Windows (refusé sans écran).

Tout ce qui AGIT (volume, fenêtres, verrouillage, extinction, modes, Ollama, mode jeu) passe par `/v1/actions` :
file d'approbations 🟡🔴, journal d'audit, arrêt d'urgence (écritures refusées en 423 par l'intergiciel).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from .ecran import garde_ecran
from .securite.permissions import ErreurAction

if TYPE_CHECKING:
    from .api import Contexte
    from .pc import ServicePC

routeur = APIRouter(prefix="/v1/pc")


def service(request: Request) -> ServicePC:
    c: Contexte = request.app.state.ctx
    if c.pc is None:
        raise HTTPException(503, "Ressources et contrôle du PC indisponibles")
    return c.pc


@routeur.get("/ressources")
async def ressources(request: Request) -> dict[str, Any]:
    pc = service(request)
    return {**await pc.ressources(), "controle": pc.controle_possible}


@routeur.get("/etat", dependencies=[Depends(garde_ecran)])  # regarde l'écran (fenêtres) : refusé sans écran
async def etat(request: Request, fenetres: bool = True) -> dict[str, Any]:
    try:
        return await service(request).etat_pc(fenetres)
    except ErreurAction as exc:
        raise HTTPException(409, str(exc)) from exc
