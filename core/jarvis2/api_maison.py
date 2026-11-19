"""Routes des connecteurs maison facultatifs (Philips Hue, OBS) : réglages faits par l'utilisateur.

Les commandes elles-mêmes (lumières, scènes, enregistrement, direct) passent par `/v1/actions` : file
d'approbations 🟡🔴, journal d'audit, arrêt d'urgence (écritures refusées en 423 par l'intergiciel).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .api_securite import appareil_courant
from .securite.permissions import ErreurAction

if TYPE_CHECKING:
    from .api import Contexte
    from .maison import GestionnaireMaison

routeur = APIRouter(prefix="/v1/maison")


def gestion(request: Request) -> GestionnaireMaison:
    c: Contexte = request.app.state.ctx
    if c.maison is None:
        raise HTTPException(503, "Connecteurs maison indisponibles")
    return c.maison


class Activation(BaseModel):
    actif: bool


class Decouverte(BaseModel):
    en_ligne: bool = False  # accord explicite : interroger le service de découverte de Signify


class Adresse(BaseModel):
    adresse: str = Field(min_length=3, max_length=60)


class ReglagesOBS(BaseModel):
    adresse: str = Field(min_length=3, max_length=60)
    mot_de_passe: str | None = Field(default=None, max_length=200)  # None : inchangé ; "" : retiré du coffre


async def _agir(appel: Any) -> Any:
    try:
        return await appel
    except ErreurAction as exc:
        raise HTTPException(422, str(exc)) from exc


@routeur.get("")
async def lister(request: Request) -> dict[str, Any]:
    g = gestion(request)
    return {"connecteurs": g.decrire(), "outils_actifs": g.outils_actifs()}


@routeur.post("/{ident}/activer")
async def activer(request: Request, ident: str, corps: Activation) -> dict[str, Any]:
    await _agir(gestion(request).activer(ident, corps.actif, appareil_courant(request)))
    return {"ok": True}


@routeur.post("/{ident}/tester")
async def tester(request: Request, ident: str) -> dict[str, Any]:
    resultat: dict[str, Any] = await _agir(gestion(request).tester(ident))
    return resultat


@routeur.delete("/{ident}")
async def oublier(request: Request, ident: str) -> dict[str, Any]:
    await _agir(gestion(request).oublier(ident, appareil_courant(request)))
    return {"ok": True}


@routeur.post("/hue/decouvrir")
async def decouvrir(request: Request, corps: Decouverte) -> dict[str, Any]:
    return {"ponts": await _agir(gestion(request).decouvrir_hue(corps.en_ligne, appareil_courant(request)))}


@routeur.post("/hue/appairer")
async def appairer(request: Request, corps: Adresse) -> dict[str, Any]:
    """Le bouton du pont vient d'être pressé : la clé obtenue va dans le coffre, jamais dans la réponse."""
    await _agir(gestion(request).appairer_hue(corps.adresse, appareil_courant(request)))
    return {"ok": True}


@routeur.put("/obs")
async def configurer_obs(request: Request, corps: ReglagesOBS) -> dict[str, Any]:
    await _agir(gestion(request).configurer_obs(corps.adresse, corps.mot_de_passe, appareil_courant(request)))
    return {"ok": True}
