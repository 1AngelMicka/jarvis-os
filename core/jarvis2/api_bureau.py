"""Routes du bureau et du téléphone : protocole `jarvis://`, notifications Web Push, « Partager vers JARVIS »,
liens de fichiers à usage unique, appel de décision (« plus tard »).

- `POST /v1/protocole`                 : vérifie un lien `jarvis://` (liste blanche) → action d'interface 🟢
- `GET  /v1/push`                      : clé publique VAPID + abonnement de cet appareil
- `POST /v1/push/abonnement`           : abonne cet appareil (service de notification connu, HTTPS)
- `DELETE /v1/push/abonnement`         : désabonne cet appareil
- `POST /v1/push/essai`                : notification d'essai à cet appareil
- `GET/POST /v1/partages`, `POST /v1/partages/{id}/traite`, `DELETE /v1/partages/{id}`
- `GET  /v1/envois`                    : fichiers du dossier « a-envoyer » ; `POST /v1/envois/lien` : lien unique
- `GET  /f/{code}`                     : PUBLIC, téléchargement unique (10 min)
- `GET  /v1/demandes/{id}`             : une demande (appel de décision) ; `POST …/reporter` : « plus tard »
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from . import partages, protocole
from .push import ErreurPush
from .securite import audit
from .securite.appareils import Appareil
from .securite.permissions import ErreurAction

if TYPE_CHECKING:
    from .api import Contexte

routeur = APIRouter(prefix="/v1")
routeur_public = APIRouter()


def _ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


def _appareil(request: Request) -> Appareil:
    a: Appareil = request.state.appareil
    return a


# --- Protocole jarvis:// ---------------------------------------------------------------------------------------


class Lien(BaseModel):
    lien: str = Field(max_length=protocole.LONGUEUR_MAX)


@routeur.post("/protocole")
async def verifier_lien(request: Request, corps: Lien) -> dict[str, Any]:
    """Seconde vérification (la première est dans l'application de bureau) : rien n'est exécuté ici."""
    c, a = _ctx(request), _appareil(request)
    try:
        lien = protocole.analyser(corps.lien)
    except protocole.ErreurLien as exc:
        await audit.journaliser(c.pool, acteur=a.acteur, action="protocole.refuse", niveau="jaune", resultat=str(exc))
        raise HTTPException(422, str(exc)) from exc
    # Le texte de « dire » n'est pas journalisé (il peut être personnel) : seulement sa longueur
    details: dict[str, Any] = {k: (len(v) if k == "texte" else v) for k, v in lien.parametres.items()}
    await audit.journaliser(c.pool, acteur=a.acteur, action="protocole.lien", cible=lien.action, details=details)
    return lien.en_dict()


@routeur.get("/protocole")
async def actions_protocole() -> dict[str, Any]:
    return {
        "actions": [
            {"action": nom, "libelle": protocole.LIBELLES[nom], "parametres": sorted(p)}
            for nom, p in protocole.ACTIONS.items()
        ]
    }


# --- Notifications Web Push ------------------------------------------------------------------------------------


class Cles(BaseModel):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class Abonnement(BaseModel):
    endpoint: str = Field(max_length=1000)
    keys: Cles


class Desabonnement(BaseModel):
    endpoint: str | None = Field(default=None, max_length=1000)


@routeur.get("/push")
async def etat_push(request: Request) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    if not c.push.disponible:
        return {"disponible": False, "cle_publique": None, "abonne": False}
    try:
        cle = c.push.cle_publique()
    except ErreurPush as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"disponible": True, "cle_publique": cle, "abonne": await c.push.abonne(a.id)}


@routeur.post("/push/abonnement")
async def abonner(request: Request, corps: Abonnement) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    try:
        await c.push.abonner(a.id, corps.endpoint, corps.keys.p256dh, corps.keys.auth)
    except ErreurPush as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit.journaliser(c.pool, acteur=a.acteur, action="push.abonne")
    return {"abonne": True}


@routeur.delete("/push/abonnement")
async def desabonner(request: Request, corps: Desabonnement | None = None) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    retires = await c.push.desabonner(a.id, corps.endpoint if corps else None)
    await audit.journaliser(c.pool, acteur=a.acteur, action="push.desabonne", details={"retires": retires})
    return {"abonne": await c.push.abonne(a.id), "retires": retires}


@routeur.post("/push/essai")
async def essai_push(request: Request) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    if not await c.push.abonne(a.id):
        raise HTTPException(409, "Cet appareil n'est pas abonné aux notifications")
    try:
        remis = await c.push.envoyer(
            {"titre": "JARVIS", "corps": "Les notifications marchent.", "url": "/", "etiquette": "essai"}, a.id
        )
    except ErreurPush as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"remis": remis}


# --- Partager vers JARVIS --------------------------------------------------------------------------------------


class NouveauPartage(BaseModel):
    titre: str = Field(default="", max_length=1000)
    texte: str = Field(default="", max_length=40000)
    url: str = Field(default="", max_length=4000)


@routeur.get("/partages")
async def lister_partages(request: Request) -> dict[str, Any]:
    return {"partages": [p.en_dict() for p in await partages.lister(_ctx(request).pool)]}


@routeur.post("/partages")
async def recevoir_partage(request: Request, corps: NouveauPartage) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    try:
        p = await partages.recevoir(c.pool, a.id, corps.titre, corps.texte, corps.url)
    except partages.ErreurPartage as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit.journaliser(
        c.pool,
        acteur=a.acteur,
        action="partage.recu",
        cible=str(p.id),
        details={"longueur": len(p.texte), "lien": bool(p.url)},
    )
    return {"partage": p.en_dict(), "message": partages.encadrer(p)}


@routeur.get("/partages/{partage_id}")
async def obtenir_partage(request: Request, partage_id: UUID) -> dict[str, Any]:
    p = await partages.obtenir(_ctx(request).pool, partage_id)
    if p is None:
        raise HTTPException(404, "Partage introuvable")
    return {"partage": p.en_dict(), "message": partages.encadrer(p)}


@routeur.post("/partages/{partage_id}/traite")
async def partage_traite(request: Request, partage_id: UUID) -> dict[str, Any]:
    if not await partages.marquer_traite(_ctx(request).pool, partage_id):
        raise HTTPException(404, "Partage introuvable ou déjà traité")
    return {"traite": True}


@routeur.delete("/partages/{partage_id}")
async def supprimer_partage(request: Request, partage_id: UUID) -> dict[str, Any]:
    """🟢 : un contenu reçu, jamais traité comme une donnée de l'utilisateur ; l'effacer ne perd rien d'important."""
    c, a = _ctx(request), _appareil(request)
    if not await partages.supprimer(c.pool, partage_id):
        raise HTTPException(404, "Partage introuvable")
    await audit.journaliser(c.pool, acteur=a.acteur, action="partage.supprime", cible=str(partage_id))
    return {"supprime": True}


# --- Liens de fichiers à usage unique --------------------------------------------------------------------------


class NouveauLien(BaseModel):
    nom: str = Field(min_length=1, max_length=255)


def _dossier(c: Contexte) -> Any:
    if c.dossier_donnees is None:
        raise HTTPException(503, "Aucun dossier des données")
    return c.dossier_donnees


@routeur.get("/envois")
async def lister_envois(request: Request) -> dict[str, Any]:
    dossier = _dossier(_ctx(request))
    return {
        "dossier": partages.DOSSIER_ENVOIS,
        "fichiers": partages.fichiers_envoyables(dossier),
        "duree_minutes": int(partages.DUREE_LIEN.total_seconds() // 60),
    }


@routeur.post("/envois/lien")
async def creer_lien(request: Request, corps: NouveauLien) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    try:
        code, expire = await partages.creer_lien(c.pool, _dossier(c), corps.nom, a.id)
    except partages.ErreurPartage as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit.journaliser(c.pool, acteur=a.acteur, action="envoi.lien_cree", cible=corps.nom)
    ts = c.tailscale
    distante = ts.adresse if ts is not None and ts.serve_actif else None
    base = distante or f"{request.url.scheme}://{request.headers.get('host', '')}"
    return {"url": f"{base}/f/{code}", "chemin": f"/f/{code}", "expire_le": expire.isoformat()}


@routeur_public.get("/f/{code}", include_in_schema=False)
async def telecharger(request: Request, code: str) -> Response:
    """Public (le téléphone l'ouvre dans son navigateur) : un code de 256 bits, valable 10 minutes, une fois."""
    c = _ctx(request)
    if c.dossier_donnees is None:
        return PlainTextResponse("Lien inconnu, expiré ou déjà utilisé", status_code=410)
    async with c.pool.acquire() as conn:
        try:
            chemin = await partages.consommer_lien(conn, c.dossier_donnees, code)
        except partages.ErreurPartage as exc:
            await audit.journaliser(conn, acteur="inconnu", action="envoi.lien_refuse", niveau="jaune")
            return PlainTextResponse(str(exc), status_code=410, headers={"Cache-Control": "no-store"})
        await audit.journaliser(conn, acteur="lien unique", action="envoi.telecharge", cible=chemin.name)
    return FileResponse(
        chemin,
        filename=chemin.name,
        content_disposition_type="attachment",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


# --- Appel de décision -----------------------------------------------------------------------------------------


@routeur.get("/demandes/{demande_id}")
async def obtenir_demande(request: Request, demande_id: UUID) -> dict[str, Any]:
    c = _ctx(request)
    await c.approbations.lister("en_attente", 1)  # marque d'abord les demandes expirées
    demande = await c.approbations.obtenir(demande_id)
    if demande is None:
        raise HTTPException(404, "Demande introuvable")
    action = c.approbations.registre.actions.get(demande.action)
    return {
        "demande": c.approbations.completer(demande).en_dict(),
        "description": action.description if action else demande.action,
        "cles_acces": await c.pool.fetchval("SELECT count(*) FROM cles_acces"),
    }


@routeur.post("/demandes/{demande_id}/reporter")
async def reporter(request: Request, demande_id: UUID) -> dict[str, Any]:
    """« Plus tard » : rien n'est décidé ; rappel poussé dans 15 minutes."""
    c = _ctx(request)
    try:
        demande = await c.approbations.reporter(demande_id, _appareil(request))
    except ErreurAction as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"statut": "reportee", "demande": demande.en_dict()}
