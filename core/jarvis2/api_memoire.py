"""Routes de la mémoire v2 : blocs éditables, état de la bascule de modèle, tâches de nuit."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import blocs, memoire
from .memoire_v2 import manquants
from .securite import audit
from .securite.appareils import Appareil

if TYPE_CHECKING:
    from .api import Contexte

routeur = APIRouter(prefix="/v1/memoire")


def _ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


def _appareil(request: Request) -> Appareil:
    a: Appareil = request.state.appareil
    return a


class Ecriture(BaseModel):
    contenu: str = Field(max_length=blocs.LIMITE_MAX)
    confidentialite: Literal["normal", "local_uniquement"] | None = None


@routeur.get("/etat")
async def etat(request: Request) -> dict[str, Any]:
    c = _ctx(request)
    bascule = c.etat_bascule
    taches = []
    if c.planificateur is not None:
        for t in c.planificateur.taches:
            derniere = await c.planificateur.derniere(f"systeme:{t.id}")
            taches.append(
                {
                    "id": t.id,
                    "nom": t.nom,
                    "planification": t.planification,
                    "derniere": {
                        "debut": derniere["debut"].isoformat(),
                        "statut": derniere["statut"],
                        "resultat": derniere["resultat"],
                        "erreur": derniere["erreur"],
                    }
                    if derniere
                    else None,
                }
            )
    compte = await memoire.compter(c.pool)
    modele = c.memoire.encodeur.nom_modele if c.memoire else None
    return {
        "souvenirs": compte,
        "modele_actif": bascule.actif if bascule else modele,
        "bascule": {
            "cible": bascule.cible,
            "faits": bascule.faits,
            "restants": bascule.restants,
            "erreur": bascule.erreur,
        }
        if bascule and (bascule.cible or bascule.erreur)
        else None,
        "sans_vecteur": await manquants(c.pool, modele) if modele else 0,
        "taches": taches,
    }


@routeur.get("/blocs")
async def lister_blocs(request: Request) -> dict[str, Any]:
    return {"blocs": [b.en_dict() for b in await blocs.lister(_ctx(request).pool, vides=True)]}


@routeur.put("/blocs/{label}")
async def ecrire_bloc(request: Request, label: str, corps: Ecriture) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    try:
        bloc = await blocs.ecrire(c.pool, label, corps.contenu, a.acteur, corps.confidentialite)
    except blocs.ErreurBloc as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit.journaliser(
        c.pool, acteur=a.acteur, action="memoire.bloc_modifie", cible=label, details={"version": bloc.version}
    )
    return bloc.en_dict()


@routeur.get("/blocs/{label}/historique")
async def historique_bloc(request: Request, label: str) -> dict[str, Any]:
    return {"versions": await blocs.historique(_ctx(request).pool, label)}


@routeur.post("/noyau-en-blocs")
async def noyau_en_blocs(request: Request) -> dict[str, Any]:
    """Réversible : les souvenirs du noyau restent, avec le tag « noyau-converti »."""
    c, a = _ctx(request), _appareil(request)
    comptes = await blocs.noyau_en_blocs(c.pool, a.acteur)
    await audit.journaliser(c.pool, acteur=a.acteur, action="memoire.noyau_en_blocs", niveau="jaune", details=comptes)
    return {"convertis": comptes}


@routeur.post("/taches/{ident}/lancer")
async def lancer_tache(request: Request, ident: str) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    if c.planificateur is None:
        raise HTTPException(404, "Aucun planificateur")
    tache = next((t for t in c.planificateur.taches if t.id == ident), None)
    if tache is None:
        raise HTTPException(404, f"Tâche inconnue : « {ident} »")
    await audit.journaliser(c.pool, acteur=a.acteur, action="memoire.tache_lancee", cible=ident)
    asyncio.get_running_loop().create_task(c.planificateur.executer_tache(tache, "manuel"))
    return {"lancee": ident}
