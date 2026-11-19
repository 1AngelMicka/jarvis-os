"""Routes du routeur par type de tâche (14 · B 11) : tableau des routes, choix par type, petit modèle de classement,
rétablissement d'une route rétrogradée, essai du classifieur et retours de l'utilisateur sur une réponse."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import routage
from .securite import audit
from .securite.appareils import Appareil

if TYPE_CHECKING:
    from .api import Contexte

routeur = APIRouter(prefix="/v1")


class Route(BaseModel):
    connecteur: str | None = Field(None, max_length=80)
    modele: str | None = Field(None, max_length=200)


class Classifieur(BaseModel):
    modele: str | None = Field(None, max_length=200)


class Retablir(BaseModel):
    connecteur: str = Field(min_length=1, max_length=80)


class Essai(BaseModel):
    texte: str = Field(min_length=1, max_length=8000)


class Retour(BaseModel):
    avis: Literal["positif", "negatif"] | None = None


def _ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


def _routeur(request: Request) -> routage.Routeur:
    r = _ctx(request).service.routeur
    if r is None:
        raise HTTPException(503, "Routeur indisponible (aucun connecteur)")
    return r


def _acteur(request: Request) -> str:
    a: Appareil = request.state.appareil
    return a.acteur


def _type(type_tache: str) -> str:
    if type_tache not in routage.TYPES:
        raise HTTPException(404, "Type de tâche inconnu : code, raisonnement, rapide ou prive")
    return type_tache


async def _modeles_ollama(r: routage.Routeur) -> tuple[bool, list[str]]:
    """Ollama tourne-t-il déjà (simple sonde, jamais de démarrage) et quels modèles a-t-il ?"""
    c = r.connecteurs
    d = c.definitions.get("ollama")
    if d is None or not c.actif("ollama") or not (await c.sante("ollama")).disponible:
        return False, []
    try:
        return True, [m.id for m in await d.moteur.list_models()]
    except Exception:  # liste indisponible : le choix reste possible à la main
        return True, []


async def decrire(r: routage.Routeur) -> dict[str, Any]:
    reglages, scores = await r.synchroniser()
    etats = await r.connecteurs.etats(tous=False)
    noms = {i: d.moteur.interne.nom for i, d in r.connecteurs.definitions.items()}
    utilisables = [e.id for e in etats if e.utilisable and not e.risque]
    types = []
    for t in routage.TYPES:
        route = reglages["routes"][t]
        prive = t == "prive"
        mesures = {c: s for (tt, c), s in scores.items() if tt == t}
        candidats = [c for c in utilisables if not prive or r.local(c)]
        for c in mesures:  # une IA mesurée reste visible même si elle n'est plus disponible
            if c not in candidats and (not prive or r.local(c)):
                candidats.append(c)
        retro = frozenset(c for c, s in mesures.items() if s.etat == "retrogradee")
        prefere = route["connecteur"] or r.connecteurs.prefere
        if prive and prefere and not r.local(prefere):
            prefere = None
        actuel = await r.connecteurs.router(local=prive, exclus=retro, prefere=prefere)
        types.append(
            {
                "type": t,
                "libelle": routage.LIBELLES[t],
                "description": routage.DESCRIPTIONS[t],
                "connecteur": route["connecteur"],
                "modele": route["modele"],
                "actuel": actuel,
                "candidats": [
                    {"nom": noms.get(c, c), "disponible": c in utilisables}
                    | (mesures[c].en_dict() if c in mesures else routage.Score(t, c).en_dict())
                    for c in candidats
                ],
            }
        )
    ollama, modeles = await _modeles_ollama(r)
    return {
        "types": types,
        "classifieur": {"modele": reglages["classifieur"], "ollama_disponible": ollama, "modeles": modeles},
        "historique": list(reversed(reglages["historique"])),
        "seuil": routage.SEUIL,
        "min_mesures": routage.MIN_MESURES,
        "fenetre_jours": routage.FENETRE.days,
        "connecteurs": [{"id": i, "nom": noms[i], "local": r.local(i)} for i in utilisables],
    }


@routeur.get("/routes")
async def lire(request: Request) -> dict[str, Any]:
    return await decrire(_routeur(request))


@routeur.put("/routes/classifieur")
async def regler_classifieur(request: Request, corps: Classifieur) -> dict[str, Any]:
    r = _routeur(request)
    reglages = await routage.lire_reglages(r.pool)
    reglages["classifieur"] = corps.modele or None
    await routage.ecrire_reglages(r.pool, reglages)
    await audit.journaliser(
        r.pool,
        acteur=_acteur(request),
        action="routage.classifieur",
        niveau="jaune",
        details={"modele": corps.modele},
    )
    return await decrire(r)


@routeur.put("/routes/{type_tache}")
async def regler_route(request: Request, type_tache: str, corps: Route) -> dict[str, Any]:
    r, t = _routeur(request), _type(type_tache)
    if corps.connecteur is not None:
        if corps.connecteur not in r.connecteurs.definitions:
            raise HTTPException(404, "Connecteur inconnu")
        if r.connecteurs.definitions[corps.connecteur].moteur.interne.risque:
            raise HTTPException(422, "Un connecteur « à risque » ne se choisit qu'à la main, jamais par le routeur")
        if t == "prive" and not r.local(corps.connecteur):
            raise HTTPException(
                422, "La route « Privé » ne part jamais vers un moteur externe : choisissez une IA du PC"
            )
    reglages = await routage.lire_reglages(r.pool)
    reglages["routes"][t] = {"connecteur": corps.connecteur, "modele": corps.modele if corps.connecteur else None}
    await routage.ecrire_reglages(r.pool, reglages)
    await audit.journaliser(
        r.pool,
        acteur=_acteur(request),
        action="routage.route",
        cible=t,
        niveau="jaune",
        details={"connecteur": corps.connecteur, "modele": corps.modele},
    )
    return await decrire(r)


@routeur.post("/routes/{type_tache}/retablir")
async def retablir(request: Request, type_tache: str, corps: Retablir) -> dict[str, Any]:
    r, t = _routeur(request), _type(type_tache)
    await r.retablir(t, corps.connecteur, _acteur(request))
    return await decrire(r)


@routeur.post("/routes/essai")
async def essayer(request: Request, corps: Essai) -> dict[str, Any]:
    """Classe une phrase sans rien envoyer à une IA externe (le petit modèle local seulement si les règles hésitent)."""
    service = _ctx(request).service
    r = _routeur(request)
    return (await r.classer(corps.texte, service.motif_prive)).en_dict()


@routeur.post("/messages/{message_id}/retour")
async def noter(request: Request, message_id: int, corps: Retour) -> dict[str, Any]:
    try:
        return await routage.noter_retour(_ctx(request).pool, message_id, corps.avis)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
