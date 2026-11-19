"""Routes du lot F : mode de pilotage, règles de protection, « toujours autoriser », commandes rapides."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .commandes_rapides import ACTIONS_INTERFACE, ErreurCommande
from .pilotage import VUES, ErreurPilotage
from .securite import audit, regles
from .securite.appareils import Appareil
from .securite.jokers import ErreurMotif, compiler
from .securite.permissions import ErreurAction

if TYPE_CHECKING:
    from .api import Contexte

routeur = APIRouter(prefix="/v1")


def _ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


def _appareil(request: Request) -> Appareil:
    a: Appareil = request.state.appareil
    return a


# --- Mode de pilotage ---------------------------------------------------------------------------------------


class ModePilotage(BaseModel):
    mode: Literal["oui", "demander", "non"]


@routeur.get("/pilotage")
async def lire_pilotage(request: Request) -> dict[str, Any]:
    c = _ctx(request)
    return {
        "mode": await c.pilotage.mode(),
        "vues": VUES,
        "actions_interface": list(ACTIONS_INTERFACE),
        "actions_declarees": [
            {
                "nom": a.nom,
                "niveau": a.niveau,
                "description": a.description,
                "toujours_possible": a.peut_etre_toujours_autorisee,
            }
            for a in c.approbations.registre.actions.values()
            if not a.nom.startswith("regle.")
        ],
    }


@routeur.put("/pilotage")
async def regler_pilotage(request: Request, corps: ModePilotage) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    mode = await c.pilotage.regler_mode(corps.mode)
    await audit.journaliser(c.pool, acteur=a.acteur, action="pilotage.mode", details={"mode": mode})
    return {"mode": mode}


# --- Règles de protection -----------------------------------------------------------------------------------


class NouvelleRegle(BaseModel):
    genre: Literal["interdire", "demander"]
    motif: str = Field(min_length=2, max_length=200)
    libelle: str = Field(default="", max_length=200)
    origine: Literal["utilisateur", "jarvis"] = "utilisateur"


class EssaiMotif(BaseModel):
    motif: str = Field(min_length=1, max_length=200)
    texte: str = Field(max_length=2000)
    contient: bool = False


@routeur.get("/regles")
async def lister_regles(request: Request) -> dict[str, Any]:
    return {"regles": [r.en_dict() for r in await regles.lister(_ctx(request).pool)]}


@routeur.post("/regles")
async def ajouter_regle(request: Request, corps: NouvelleRegle) -> dict[str, Any]:
    """🟢 : ajouter une protection est libre (journalisé). `origine` « jarvis » : proposée par JARVIS, cliquée ici."""
    c, a = _ctx(request), _appareil(request)
    try:
        regle = await regles.ajouter(c.pool, corps.genre, corps.motif, corps.libelle, a.acteur, corps.origine)
    except ErreurMotif as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit.journaliser(
        c.pool,
        acteur=a.acteur,
        action="regle.ajoutee",
        cible=str(regle.id),
        details={"genre": regle.genre, "origine": regle.origine},  # jamais le motif : il peut nommer un sujet exclu
    )
    return {"regle": regle.en_dict()}


@routeur.post("/regles/{regle_id}/retirer")
async def retirer_regle(request: Request, regle_id: UUID) -> dict[str, Any]:
    """🟡 : retirer une protection passe par la file d'approbations."""
    c = _ctx(request)
    regle = await regles.obtenir(c.pool, regle_id)
    if regle is None:
        raise HTTPException(404, "Règle introuvable")
    try:
        return await c.approbations.demander(
            "regle.supprimer", {"regle_id": str(regle.id), "libelle": regle.libelle}, _appareil(request)
        )
    except ErreurAction as exc:
        raise HTTPException(422, str(exc)) from exc


@routeur.post("/motifs/tester")
async def tester_motif(corps: EssaiMotif) -> dict[str, Any]:
    """🟢 : un motif correspond-il à ce texte ? (règles : `contient`, commandes rapides : phrase entière)."""
    try:
        motif = compiler(corps.motif)
    except ErreurMotif as exc:
        return {"valide": False, "erreur": str(exc), "correspond": False}
    captures = motif.correspond(corps.texte, contient=corps.contient)
    return {"valide": True, "correspond": captures is not None, "captures": captures or {}}


# --- « Toujours autoriser » ---------------------------------------------------------------------------------


@routeur.get("/autorisations")
async def lister_autorisations(request: Request) -> dict[str, Any]:
    return {"autorisations": await _ctx(request).approbations.autorisations()}


@routeur.post("/autorisations/{action}/retirer")
async def retirer_autorisation(request: Request, action: str) -> dict[str, Any]:
    """🟢 : retirer une autorisation protège : chaque usage redemandera votre accord."""
    if not await _ctx(request).approbations.retirer_autorisation(action, _appareil(request)):
        raise HTTPException(404, "Aucune autorisation permanente pour cette action")
    return {"retiree": True}


# --- Commandes rapides --------------------------------------------------------------------------------------


class CommandeRapide(BaseModel):
    motif: str = Field(min_length=2, max_length=200)
    cible: Literal["interface", "core"]
    action: str = Field(min_length=1, max_length=80)
    parametres: dict[str, Any] = Field(default_factory=dict)
    priorite: int = Field(default=0, ge=-100, le=100)
    phrase_test: str = Field(min_length=1, max_length=200)
    actif: bool = True


class Phrase(BaseModel):
    phrase: str = Field(max_length=2000)


def _avec_niveau(c: Contexte, d: dict[str, Any]) -> dict[str, Any]:
    return {**d, "niveau": c.commandes.niveau(d["cible"], d["action"])}


async def _conflits(c: Contexte, phrase: str, sauf: UUID | None) -> list[dict[str, Any]]:
    return [
        {"id": str(t.commande.id), "motif": t.commande.motif, "priorite": t.commande.priorite}
        for t in await c.commandes.trouver(phrase, sauf=sauf)
    ]


@routeur.get("/commandes-rapides")
async def lister_commandes(request: Request) -> dict[str, Any]:
    c = _ctx(request)
    return {"commandes": [_avec_niveau(c, x.en_dict()) for x in await c.commandes.lister()]}


@routeur.post("/commandes-rapides/verifier")
async def verifier_commande(request: Request, corps: CommandeRapide) -> dict[str, Any]:
    """Sans rien enregistrer : la phrase de test passe-t-elle, et quelles autres commandes la captent ?"""
    c = _ctx(request)
    try:
        action = await c.commandes.verifier(corps.motif, corps.cible, corps.action, corps.parametres, corps.phrase_test)
    except ErreurCommande as exc:
        return {"valide": False, "erreur": str(exc)}
    return {"valide": True, "action": action, "conflits": await _conflits(c, corps.phrase_test, None)}


@routeur.post("/commandes-rapides")
async def creer_commande(request: Request, corps: CommandeRapide) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    conflits = await _conflits(c, corps.phrase_test, None)
    try:
        commande = await c.commandes.creer(corps.model_dump())
    except ErreurCommande as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit.journaliser(
        c.pool,
        acteur=a.acteur,
        action="commande_rapide.creee",
        cible=str(commande.id),
        details={"action": corps.action},
    )
    return {"commande": _avec_niveau(c, commande.en_dict()), "conflits": conflits}


@routeur.put("/commandes-rapides/{ident}")
async def modifier_commande(request: Request, ident: UUID, corps: CommandeRapide) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    try:
        commande = await c.commandes.modifier(ident, corps.model_dump())
    except ErreurCommande as exc:
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    await audit.journaliser(
        c.pool, acteur=a.acteur, action="commande_rapide.modifiee", cible=str(ident), details={"action": corps.action}
    )
    return {"commande": _avec_niveau(c, commande.en_dict()), "conflits": await _conflits(c, corps.phrase_test, ident)}


@routeur.delete("/commandes-rapides/{ident}")
async def supprimer_commande(request: Request, ident: UUID) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    commande = await c.commandes.supprimer(ident)
    if commande is None:
        raise HTTPException(404, "Commande rapide introuvable")
    await audit.journaliser(c.pool, acteur=a.acteur, action="commande_rapide.supprimee", cible=str(ident))
    return {"supprimee": True}


@routeur.post("/commandes-rapides/executer")
async def executer_commande(request: Request, corps: Phrase) -> dict[str, Any]:
    """Une phrase de l'utilisateur, avant l'IA. Aucune commande : `trouvee` faux, la phrase part à l'IA.
    Action d'interface : renvoyée validée, l'interface l'applique. Action du Core : file d'approbations."""
    c, a = _ctx(request), _appareil(request)
    trouvees = await c.commandes.trouver(corps.phrase)
    if not trouvees:
        return {"trouvee": False}
    t = trouvees[0]
    try:
        action = await c.commandes.resoudre(t.commande.cible, t.commande.action, t.parametres)
    except ErreurCommande as exc:
        return {"trouvee": True, "commande": t.commande.en_dict(), "erreur": str(exc)}
    await c.commandes.noter_utilisation(t.commande.id)
    await audit.journaliser(
        c.pool,
        acteur=a.acteur,
        action="commande_rapide.utilisee",
        cible=str(t.commande.id),
        details={"action": t.commande.action},
    )
    reponse: dict[str, Any] = {"trouvee": True, "commande": t.commande.en_dict(), "action": action}
    if t.commande.cible == "core":
        try:
            reponse["resultat"] = await c.approbations.demander(t.commande.action, t.parametres, a)
        except ErreurAction as exc:
            reponse["erreur"] = str(exc)
    return reponse


@routeur.post("/pilotage/valider")
async def valider_action(request: Request, corps: dict[str, Any]) -> dict[str, Any]:
    """Revalide une action d'interface (bouton « Rouvrir » d'une ancienne réponse : l'élément existe-t-il encore ?)."""
    try:
        return {"action": await _ctx(request).pilotage.valider(corps)}
    except ErreurPilotage as exc:
        raise HTTPException(422, str(exc)) from exc
