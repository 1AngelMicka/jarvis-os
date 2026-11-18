"""Routes de sécurité : appareils, jumelage, clés d'accès, actions et demandes, arrêt d'urgence, audit."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

import segno
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .securite import appareils, audit, cles
from .securite.appareils import Appareil, ErreurJumelage
from .securite.permissions import ErreurAction

if TYPE_CHECKING:
    from .api import Contexte

routeur = APIRouter(prefix="/v1")


def ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


def appareil_courant(request: Request) -> Appareil:
    a: Appareil = request.state.appareil
    return a


def est_local(request: Request) -> bool:
    """Requête venue de la boucle locale du PC, adressée à localhost."""
    hote = (request.headers.get("host") or "").rsplit(":", 1)[0]
    return bool(request.client and request.client.host in ("127.0.0.1", "::1")) and hote in (
        "localhost",
        "127.0.0.1",
        "[::1]",
    )


def origine_page(request: Request) -> str:
    return request.headers.get("origin") or f"{request.url.scheme}://{request.headers.get('host', '')}"


def rp_id(request: Request) -> str:
    try:
        return cles.partie(request.headers.get("host", ""))
    except cles.ErreurCle as exc:
        raise HTTPException(400, str(exc)) from exc


class NouvelAppareil(BaseModel):
    nom: str = Field(min_length=1, max_length=80)


class Echange(BaseModel):
    code: str = Field(min_length=10, max_length=200)
    nom: str = Field(min_length=1, max_length=80)


class Jumelage(BaseModel):
    type: str = Field(default="telephone", pattern="^(navigateur|telephone|pc)$")


class EnregistrementCle(BaseModel):
    credential: dict[str, Any]
    nom: str = Field(default="Clé d'accès", max_length=80)


class DemandeAction(BaseModel):
    action: str = Field(max_length=80)
    parametres: dict[str, Any] = Field(default_factory=dict)


class Decision(BaseModel):
    credential: dict[str, Any] | None = None


# --- Appareils et jumelage ---------------------------------------------------------------------------------


@routeur.get("/auth/etat")
async def etat_auth(request: Request) -> dict[str, Any]:
    """Public : dit si cet appareil doit être jumelé, et si le « premier appareil » est encore possible."""
    c = ctx(request)
    return {"premier_possible": est_local(request) and await appareils.premier_possible(c.pool)}


@routeur.post("/appareils/premier")
async def premier_appareil(request: Request, corps: NouvelAppareil) -> dict[str, Any]:
    """Public, une seule fois : le navigateur du PC devient le premier appareil autorisé."""
    if not est_local(request):
        raise HTTPException(403, "Le premier appareil s'enregistre depuis le PC (http://localhost)")
    c = ctx(request)
    async with c.pool.acquire() as conn:
        try:
            appareil, jeton = await appareils.creer_premier(conn, corps.nom)
        except ErreurJumelage as exc:
            raise HTTPException(409, str(exc)) from exc
        await audit.journaliser(conn, acteur=appareil.acteur, action="appareil.premier", cible=str(appareil.id))
    return {"appareil": appareil.en_dict(), "jeton": jeton}


@routeur.post("/jumelage/echanger")
async def echanger(request: Request, corps: Echange) -> dict[str, Any]:
    """Public : code de jumelage à usage unique -> jeton de ce nouvel appareil."""
    c = ctx(request)
    async with c.pool.acquire() as conn:
        try:
            appareil, jeton = await appareils.echanger_jumelage(conn, corps.code, corps.nom)
        except ErreurJumelage as exc:
            await audit.journaliser(conn, acteur="inconnu", action="jumelage.refuse", niveau="jaune", resultat=str(exc))
            raise HTTPException(403, str(exc)) from exc
        await audit.journaliser(conn, acteur=appareil.acteur, action="jumelage.utilise", cible=str(appareil.id))
    return {"appareil": appareil.en_dict(), "jeton": jeton}


@routeur.post("/jumelage")
async def creer_jumelage(request: Request, corps: Jumelage) -> dict[str, Any]:
    """Code à usage unique (5 min) + QR, pour associer un nouvel appareil."""
    c, a = ctx(request), appareil_courant(request)
    code, expire = await appareils.creer_jumelage(c.pool, a.id, corps.type)
    url = f"{origine_page(request)}/#jumeler={code}"
    qr = segno.make(url, error="m").svg_data_uri(scale=5, border=2, dark="#02070c", light="#c4f7ff")
    await audit.journaliser(c.pool, acteur=a.acteur, action="jumelage.cree", details={"type": corps.type})
    return {"url": url, "qr": qr, "expire_le": expire.isoformat(), "local": est_local(request)}


@routeur.get("/appareils")
async def lister_appareils(request: Request) -> dict[str, Any]:
    c, a = ctx(request), appareil_courant(request)
    liste = await appareils.lister(c.pool)
    cles_par_appareil = {
        r["appareil_id"]: r["n"]
        for r in await c.pool.fetch("SELECT appareil_id, count(*) AS n FROM cles_acces GROUP BY 1")
    }
    return {
        "appareils": [{**x.en_dict(), "courant": x.id == a.id, "cles": cles_par_appareil.get(x.id, 0)} for x in liste]
    }


@routeur.post("/appareils/{appareil_id}/revoquer")
async def revoquer(request: Request, appareil_id: UUID) -> dict[str, Any]:
    """🟢 : retirer un accès protège, il n'attend pas d'approbation (journalisé)."""
    c, a = ctx(request), appareil_courant(request)
    if not await appareils.revoquer(c.pool, appareil_id):
        raise HTTPException(404, "Appareil introuvable ou déjà révoqué")
    await audit.journaliser(c.pool, acteur=a.acteur, action="appareil.revoque", cible=str(appareil_id))
    return {"revoque": True, "soi_meme": appareil_id == a.id}


# --- Clés d'accès -----------------------------------------------------------------------------------------


@routeur.post("/cles/enregistrement/options")
async def options_cle(request: Request) -> dict[str, Any]:
    c, a = ctx(request), appareil_courant(request)
    return await cles.options_enregistrement(c.pool, a.id, a.nom, rp_id(request))


@routeur.post("/cles/enregistrement")
async def enregistrer_cle(request: Request, corps: EnregistrementCle) -> dict[str, Any]:
    c, a = ctx(request), appareil_courant(request)
    try:
        ident = await cles.enregistrer(c.pool, a.id, corps.credential, corps.nom, rp_id(request), origine_page(request))
    except cles.ErreurCle as exc:
        raise HTTPException(400, str(exc)) from exc
    await audit.journaliser(c.pool, acteur=a.acteur, action="cle_acces.ajoutee", cible=ident)
    return {"id": ident}


# --- Actions et demandes ----------------------------------------------------------------------------------


@routeur.get("/actions")
async def lister_actions(request: Request) -> dict[str, Any]:
    actions = ctx(request).approbations.registre.actions.values()
    return {"actions": [{"nom": x.nom, "niveau": x.niveau, "description": x.description} for x in actions]}


@routeur.post("/actions")
async def demander_action(request: Request, corps: DemandeAction) -> dict[str, Any]:
    c = ctx(request)
    try:
        return await c.approbations.demander(corps.action, corps.parametres, appareil_courant(request))
    except ErreurAction as exc:
        raise HTTPException(422, str(exc)) from exc


@routeur.get("/demandes")
async def lister_demandes(request: Request, statut: str | None = "en_attente") -> dict[str, Any]:
    demandes = await ctx(request).approbations.lister(statut if statut != "toutes" else None)
    return {"demandes": [d.en_dict() for d in demandes]}


@routeur.post("/demandes/{demande_id}/options")
async def options_approbation(request: Request, demande_id: UUID) -> dict[str, Any]:
    """Défi WebAuthn lié à cette demande 🔴."""
    c, a = ctx(request), appareil_courant(request)
    demande = await c.approbations.obtenir(demande_id)
    if demande is None or demande.statut != "en_attente":
        raise HTTPException(404, "Demande introuvable ou déjà traitée")
    try:
        return await cles.options_approbation(c.pool, a.id, demande_id, rp_id(request))
    except cles.ErreurCle as exc:
        raise HTTPException(409, str(exc)) from exc


@routeur.post("/demandes/{demande_id}/approuver")
async def approuver(request: Request, demande_id: UUID, corps: Decision) -> dict[str, Any]:
    c, a = ctx(request), appareil_courant(request)
    methode = "clic"
    if corps.credential is not None:
        try:
            await cles.verifier_approbation(
                c.pool, a.id, demande_id, corps.credential, rp_id(request), origine_page(request)
            )
        except cles.ErreurCle as exc:
            await audit.journaliser(
                c.pool,
                acteur=a.acteur,
                action="demande.cle_refusee",
                niveau="rouge",
                cible=str(demande_id),
                resultat=str(exc),
            )
            raise HTTPException(403, str(exc)) from exc
        methode = "cle_acces"
    try:
        return await c.approbations.decider(demande_id, a, approuver=True, methode=methode)
    except ErreurAction as exc:
        raise HTTPException(409, str(exc)) from exc


@routeur.post("/demandes/{demande_id}/refuser")
async def refuser(request: Request, demande_id: UUID) -> dict[str, Any]:
    c = ctx(request)
    try:
        return await c.approbations.decider(demande_id, appareil_courant(request), approuver=False, methode="clic")
    except ErreurAction as exc:
        raise HTTPException(409, str(exc)) from exc


# --- Arrêt d'urgence et audit -----------------------------------------------------------------------------


@routeur.post("/urgence/arreter")
async def arreter(request: Request) -> dict[str, Any]:
    """🟢 : n'importe quel appareil autorisé peut tout arrêter, tout de suite."""
    c, a = ctx(request), appareil_courant(request)
    interrompues = await c.urgence.arreter(c.pool, a.acteur)
    await audit.journaliser(
        c.pool, acteur=a.acteur, action="urgence.arret", niveau="rouge", details={"reponses_interrompues": interrompues}
    )
    return {"urgence": c.urgence.en_dict(), "reponses_interrompues": interrompues}


@routeur.post("/urgence/lever")
async def lever(request: Request) -> dict[str, Any]:
    """🔴 : crée la demande ; elle ne s'approuve qu'avec une clé d'accès."""
    c = ctx(request)
    if not c.urgence.actif:
        raise HTTPException(409, "L'arrêt d'urgence n'est pas actif")
    return await c.approbations.demander("urgence.lever", {}, appareil_courant(request))


@routeur.get("/audit")
async def lire_audit(request: Request, limite: int = 50) -> dict[str, Any]:
    c = ctx(request)
    return {"entrees": await audit.lister(c.pool, max(1, min(limite, 500))), "rompue_a": await audit.verifier(c.pool)}
