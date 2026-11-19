"""Routes de la mémoire v2 : souvenirs (parcourir, chercher, nouveautés, niveau, remplacement, versions), blocs
éditables, état de la bascule de modèle, tâches de nuit."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

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
    niveau: memoire.Niveau | None = None  # prioritaire sur `confidentialite`


class ChangementNiveau(BaseModel):
    niveau: memoire.Niveau


class Remplacement(BaseModel):
    contenu: str = Field(min_length=1, max_length=memoire.TAILLE_MAX_SOUVENIR * 10)


@routeur.get("/souvenirs")
async def souvenirs(
    request: Request,
    origine: str | None = None,
    avant: datetime | None = None,
    q: str = "",
    limite: int = 40,
) -> dict[str, Any]:
    """Vue Mémoire : du plus récent au plus ancien (page suivante : `avant`), ou recherche hybride (`q`). Les
    souvenirs privés sont montrés à l'utilisateur sur ses appareils, marqués comme tels."""
    c = _ctx(request)
    limite = max(1, min(limite, 100))
    texte = q.strip()[:300]
    if texte:
        if c.memoire is None:
            raise HTTPException(503, "Mémoire indisponible")
        from dataclasses import replace

        reglages = replace(c.memoire.reglages, limite=limite)
        resultats = await memoire.rechercher_multi(
            c.pool, c.memoire.encodeur, texte, exclure_local=False, reglages=reglages
        )
        liste = [r.souvenir for r in resultats if not origine or r.souvenir.origine == origine]
        liste = await memoire.marquer_remplaces(c.pool, liste)
        return {"souvenirs": [s.en_dict() for s in liste], "suite": False}
    liste = await memoire.parcourir(c.pool, origine=origine or None, avant=avant, limite=limite)
    marques = await memoire.marquer_remplaces(c.pool, liste)
    return {"souvenirs": [s.en_dict() for s in marques], "suite": len(liste) == limite}


@routeur.put("/souvenirs/{ident}/niveau")
async def niveau_souvenir(request: Request, ident: UUID, corps: ChangementNiveau) -> dict[str, Any]:
    """Change le niveau d'un souvenir vivant (confidentialité synchronisée : « prive » ⇔ local uniquement)."""
    c, a = _ctx(request), _appareil(request)
    avant = await memoire.lire(c.pool, str(ident))
    souvenir = await memoire.changer_niveau(c.pool, str(ident), corps.niveau)
    if souvenir is None or avant is None:
        raise HTTPException(404, "Souvenir introuvable ou déjà remplacé")
    await audit.journaliser(
        c.pool,
        acteur=a.acteur,
        action="memoire.niveau",
        cible=str(ident),
        details={"avant": avant.niveau, "apres": souvenir.niveau},
    )
    return {"souvenir": souvenir.en_dict()}


@routeur.post("/souvenirs/{ident}/remplacer")
async def remplacer_souvenir(request: Request, ident: UUID, corps: Remplacement) -> dict[str, Any]:
    """Changement d'avis : un nouveau souvenir remplace l'ancien, gardé dans l'historique (rien n'est effacé)."""
    c, a = _ctx(request), _appareil(request)
    contenu = corps.contenu.strip()
    if not contenu:
        raise HTTPException(422, "Contenu vide")
    vecteur = modele = None
    if c.memoire is not None:
        vecteur = await c.memoire.encodeur.encoder(contenu)
        modele = c.memoire.encodeur.nom_modele
    try:
        nouveau_id = await memoire.remplacer(
            c.pool, str(ident), contenu, vecteur=vecteur, modele=modele, raison=f"remplacé par {a.acteur}"
        )
    except memoire.SouvenirAbsent as exc:
        raise HTTPException(404, "Souvenir introuvable") from exc
    except memoire.DejaRemplace as exc:
        raise HTTPException(409, str(exc)) from exc
    ancien, nouveau = await memoire.lire(c.pool, str(ident)), await memoire.lire(c.pool, nouveau_id)
    assert ancien is not None and nouveau is not None
    await audit.journaliser(
        c.pool, acteur=a.acteur, action="memoire.remplacer", cible=str(ident), details={"nouveau": nouveau_id}
    )
    return {"ancien": ancien.en_dict(), "nouveau": nouveau.en_dict()}


@routeur.get("/souvenirs/{ident}/versions")
async def versions_souvenir(request: Request, ident: UUID) -> dict[str, Any]:
    """Historique d'un fait, de la plus ancienne version à l'actuelle."""
    liste = await memoire.versions(_ctx(request).pool, str(ident))
    if not liste:
        raise HTTPException(404, "Souvenir introuvable")
    return {"versions": [v.en_dict() for v in liste]}


@routeur.get("/origines")
async def origines(request: Request) -> dict[str, Any]:
    comptes = await memoire.par_origine(_ctx(request).pool)
    return {
        "origines": [
            {"id": o, "nom": memoire.LIBELLES_ORIGINE.get(o, o), "nombre": n}
            for o, n in sorted(comptes.items(), key=lambda x: -x[1])
        ]
    }


@routeur.get("/nouveautes")
async def nouveautes(request: Request, depuis: datetime) -> dict[str, Any]:
    """Ce que JARVIS a appris depuis `depuis` (notification « JARVIS a appris »)."""
    c = _ctx(request)
    recents = await memoire.parcourir(c.pool, depuis=depuis, limite=20)
    premiers = await memoire.marquer_remplaces(c.pool, recents[:5])
    return {"nombre": len(recents), "souvenirs": [s.en_dict() for s in premiers]}


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
        "niveaux": memoire.niveaux_de(compte),
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
        bloc = await blocs.ecrire(c.pool, label, corps.contenu, a.acteur, corps.confidentialite, niveau=corps.niveau)
    except blocs.ErreurBloc as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit.journaliser(
        c.pool,
        acteur=a.acteur,
        action="memoire.bloc_modifie",
        cible=label,
        details={"version": bloc.version, "niveau": bloc.niveau},
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
