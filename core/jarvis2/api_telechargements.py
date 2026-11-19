"""Routes des gros téléchargements : état (progression, échec et raison) et lancement sur accord de l'utilisateur."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request

from . import telechargements
from .config import Parametres
from .securite import audit
from .securite.appareils import Appareil

if TYPE_CHECKING:
    from .api import Contexte

routeur = APIRouter(prefix="/v1")


def _ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


def _parametres(request: Request) -> Parametres:
    p: Parametres = request.app.state.parametres
    return p


def modeles(p: Parametres) -> dict[str, telechargements.Modele]:
    """Modèles téléchargeables de cette installation (ceux de la configuration)."""
    return {
        "embeddings": telechargements.modele_embeddings(p.dossier_modeles, p.modele_embeddings),
        "voix": telechargements.modele_whisper(p.dossier_modeles, p.modele_voix),
    }


def etats(c: Contexte, p: Parametres) -> list[dict[str, Any]]:
    return [c.telechargeur.etat(m).en_dict() for m in modeles(p).values()]


def lancer(c: Contexte, p: Parametres, ident: str) -> telechargements.Etat:
    """Démarre le téléchargement en tâche de fond. Seulement sur un geste de l'utilisateur (bouton, réparation)."""
    modele = modeles(p).get(ident)
    if modele is None:
        raise HTTPException(404, f"Téléchargement inconnu : « {ident} »")
    if telechargements.est_pret(modele) and not c.telechargeur.actif(modele):
        return c.telechargeur.etat(modele)

    async def apres(etat: telechargements.Etat) -> None:
        if ident == "embeddings" and etat.statut == "pret":
            from .api import precharger_modele

            await precharger_modele(c)

    c.telechargeur.lancer(modele, apres)
    return c.telechargeur.etat(modele)


@routeur.get("/telechargements")
async def lire(request: Request) -> dict[str, Any]:
    return {"telechargements": etats(_ctx(request), _parametres(request))}


@routeur.post("/telechargements/{ident}")
async def demarrer(request: Request, ident: str) -> dict[str, Any]:
    """Le clic de l'utilisateur vaut accord ; un échec se réessaie par le même appel (reprise si possible)."""
    c, p = _ctx(request), _parametres(request)
    lancer(c, p, ident)
    a: Appareil = request.state.appareil
    await audit.journaliser(c.pool, acteur=a.acteur, action="telechargement.lancer", details={"modele": ident})
    return {"telechargements": etats(c, p)}
