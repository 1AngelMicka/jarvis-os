"""Routes des connecteurs maison facultatifs (Philips Hue, OBS, Home Assistant) : réglages faits par l'utilisateur.

Les commandes elles-mêmes (lumières, scènes, enregistrement, direct) passent par `/v1/actions` : file
d'approbations 🟡🔴, journal d'audit, arrêt d'urgence (écritures refusées en 423 par l'intergiciel).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from .api_securite import appareil_courant
from .maison.home_assistant import ErreurHomeAssistant
from .maison.wyoming import ErreurWyoming
from .securite import audit
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


class ReglagesHA(BaseModel):
    adresse: str | None = Field(default=None, min_length=3, max_length=200)
    mode: str | None = Field(default=None, pattern="^(mcp|rest)$")
    jeton: str | None = Field(default=None, max_length=1000)  # None : inchangé ; "" : retiré du coffre
    code_alarme: str | None = Field(default=None, max_length=40)


class ReglagesWyoming(BaseModel):
    actif: bool | None = None
    hote: str | None = Field(default=None, max_length=60)
    port: int | None = None
    clients: list[str] | None = Field(default=None, max_length=10)


class NouveauSatellite(BaseModel):
    nom: str = Field(min_length=1, max_length=60)
    piece: str = Field(min_length=1, max_length=60)
    volume_max: int = Field(default=70, ge=0, le=100)


class ModificationSatellite(BaseModel):
    nom: str | None = Field(default=None, min_length=1, max_length=60)
    piece: str | None = Field(default=None, min_length=1, max_length=60)
    volume_max: int | None = Field(default=None, ge=0, le=100)
    actif: bool | None = None


class Profil(BaseModel):
    nom: str | None = Field(default=None, min_length=1, max_length=60)
    volume_max: int | None = Field(default=None, ge=0, le=100)


async def _agir(appel: Any) -> Any:
    try:
        return await appel
    except (ErreurAction, ErreurHomeAssistant, ErreurWyoming) as exc:
        raise HTTPException(422, str(exc)) from exc


def _ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


# --- Wyoming, satellites, pièces, profils -------------------------------------------------------------------------


@routeur.get("/wyoming")
async def lire_wyoming(request: Request) -> dict[str, Any]:
    return _ctx(request).wyoming.decrire()


@routeur.put("/wyoming")
async def regler_wyoming(request: Request, corps: ReglagesWyoming) -> dict[str, Any]:
    c = _ctx(request)
    reglages = await _agir(c.wyoming.regler(corps.actif, corps.hote, corps.port, corps.clients))
    await audit.journaliser(
        c.pool,
        acteur=appareil_courant(request).acteur,
        action="maison.wyoming.regle",
        niveau="jaune" if reglages["actif"] else "vert",
        details={"actif": reglages["actif"], "port": reglages["port"], "clients": len(reglages["clients"])},
    )
    return c.wyoming.decrire()


@routeur.get("/satellites")
async def lister_satellites(request: Request) -> dict[str, Any]:
    c = _ctx(request)
    return {"satellites": await c.satellites.lister(), "connectes": c.wyoming.decrire()["satellites_connectes"]}


@routeur.post("/satellites")
async def ajouter_satellite(request: Request, corps: NouveauSatellite) -> dict[str, Any]:
    """Nouveau satellite : sa clé est renvoyée UNE fois (à recopier dans l'appareil) ; la base n'en garde que
    l'empreinte."""
    c = _ctx(request)
    fiche, cle = await _agir(c.satellites.ajouter(corps.nom, corps.piece, corps.volume_max))
    await audit.journaliser(
        c.pool,
        acteur=appareil_courant(request).acteur,
        action="maison.satellite.ajoute",
        cible=fiche["id"],
        niveau="jaune",
    )
    return {"satellite": fiche, "cle": cle}


@routeur.put("/satellites/{ident}")
async def modifier_satellite(request: Request, ident: str, corps: ModificationSatellite) -> dict[str, Any]:
    c = _ctx(request)
    fiche = await _agir(c.satellites.modifier(ident, corps.nom, corps.piece, corps.volume_max, corps.actif))
    await audit.journaliser(
        c.pool,
        acteur=appareil_courant(request).acteur,
        action="maison.satellite.modifie",
        cible=ident,
        details={k: v for k, v in corps.model_dump().items() if v is not None and k in ("volume_max", "actif")},
    )
    return {"satellite": fiche}


@routeur.delete("/satellites/{ident}")
async def retirer_satellite(request: Request, ident: str) -> dict[str, Any]:
    c = _ctx(request)
    if not await c.satellites.retirer(ident):
        raise HTTPException(404, "Satellite introuvable")
    await audit.journaliser(
        c.pool, acteur=appareil_courant(request).acteur, action="maison.satellite.retire", cible=ident
    )
    return {"ok": True}


@routeur.get("/pieces")
async def pieces(request: Request) -> dict[str, Any]:
    return {"pieces": await _ctx(request).satellites.pieces()}


@routeur.get("/profils")
async def lister_profils(request: Request) -> dict[str, Any]:
    c = _ctx(request)
    inscrits = c.proprietaire.profils_inscrits()
    profils = [{**p, "empreintes": inscrits.get(p["id"], 0)} for p in await c.satellites.profils()]
    etat = await c.proprietaire.etat()
    return {"profils": profils, "reconnaissance": {"actif": etat["actif"], "disponible": etat["disponible"]}}


@routeur.post("/profils")
async def ajouter_profil(request: Request, corps: Profil) -> dict[str, Any]:
    c = _ctx(request)
    if not corps.nom:
        raise HTTPException(422, "Nom du profil manquant")
    volume = corps.volume_max if corps.volume_max is not None else 100
    profil = await _agir(c.satellites.ajouter_profil(corps.nom, volume))
    await audit.journaliser(
        c.pool, acteur=appareil_courant(request).acteur, action="maison.profil.ajoute", cible=profil["id"]
    )
    return {"profil": profil}


@routeur.put("/profils/{ident}")
async def modifier_profil(request: Request, ident: str, corps: Profil) -> dict[str, Any]:
    c = _ctx(request)
    profil = await _agir(c.satellites.modifier_profil(ident, corps.nom, corps.volume_max))
    await audit.journaliser(
        c.pool, acteur=appareil_courant(request).acteur, action="maison.profil.modifie", cible=ident
    )
    return {"profil": profil}


@routeur.delete("/profils/{ident}")
async def retirer_profil(request: Request, ident: str) -> dict[str, Any]:
    """Le profil et ses empreintes de voix (dossier des données) disparaissent ensemble."""
    c = _ctx(request)
    if not await c.satellites.retirer_profil(ident):
        raise HTTPException(404, "Profil introuvable")
    retirees = await c.proprietaire.retirer_profil(ident)
    await audit.journaliser(
        c.pool,
        acteur=appareil_courant(request).acteur,
        action="maison.profil.retire",
        cible=ident,
        details={"empreintes": retirees},
    )
    return {"ok": True}


@routeur.post("/profils/{ident}/voix")
async def inscrire_voix_profil(request: Request, ident: str) -> dict[str, Any]:
    """Corps : un enregistrement de la voix de cette personne (3 s de parole au moins). Seul le vecteur est gardé."""
    from .transcription import TranscripteurRobuste

    c = _ctx(request)
    if await c.satellites.profil(ident) is None:
        raise HTTPException(404, "Profil introuvable")
    if not isinstance(c.transcripteur, TranscripteurRobuste):
        raise HTTPException(404, "Transcription indisponible")
    audio = await request.body()
    if not audio:
        raise HTTPException(422, "Enregistrement vide")
    try:
        r = await c.transcripteur.analyser(audio)
        empreinte = await c.proprietaire.inscrire(r, profil=ident)
    except (ErreurAction, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit.journaliser(
        c.pool,
        acteur=appareil_courant(request).acteur,
        action="voix.empreinte.ajoutee",
        cible=empreinte["id"],
        details={"profil": ident},
    )
    return {"empreinte": empreinte}


# --- Home Assistant (avant les routes génériques `/{ident}/…`) ----------------------------------------------------


@routeur.get("/home-assistant")
async def lire_ha(request: Request) -> dict[str, Any]:
    return gestion(request).decrire_ha()


@routeur.put("/home-assistant")
async def configurer_ha(request: Request, corps: ReglagesHA) -> dict[str, Any]:
    g = gestion(request)
    await _agir(g.ha.configurer(corps.adresse, corps.mode, corps.jeton, corps.code_alarme))
    await audit.journaliser(
        g.pool,
        acteur=appareil_courant(request).acteur,
        action="maison.home_assistant.configure",
        cible="home_assistant",
        niveau="jaune",
        details={  # jamais un jeton ni un code : seulement ce qui a changé
            "adresse": corps.adresse is not None,
            "mode": corps.mode,
            "jeton": None if corps.jeton is None else ("enregistré" if corps.jeton.strip() else "retiré"),
            "code_alarme": None if corps.code_alarme is None else bool(corps.code_alarme.strip()),
        },
    )
    return g.decrire_ha()


@routeur.post("/home-assistant/activer")
async def activer_ha(request: Request, corps: Activation) -> dict[str, Any]:
    g = gestion(request)
    await _agir(g.ha.activer(corps.actif))
    await audit.journaliser(
        g.pool,
        acteur=appareil_courant(request).acteur,
        action="maison.active" if corps.actif else "maison.desactive",
        cible="home_assistant",
        niveau="jaune" if corps.actif else "vert",
    )
    return {"ok": True}


@routeur.post("/home-assistant/tester")
async def tester_ha(request: Request) -> dict[str, Any]:
    resultat: dict[str, Any] = await gestion(request).ha.tester()
    return resultat


@routeur.delete("/home-assistant")
async def oublier_ha(request: Request) -> dict[str, Any]:
    g = gestion(request)
    await g.ha.oublier()
    await audit.journaliser(
        g.pool, acteur=appareil_courant(request).acteur, action="maison.oublie", cible="home_assistant"
    )
    return {"ok": True}


@routeur.post("/home-assistant/oauth")
async def commencer_oauth(request: Request) -> dict[str, Any]:
    """URL d'autorisation de Home Assistant (OAuth + PKCE) ; le retour arrive sur ce PC (adresse de bouclage)."""
    g = gestion(request)
    port = request.app.state.parametres.port
    try:
        url = g.ha.commencer_oauth(f"http://127.0.0.1:{port}")
    except ErreurHomeAssistant as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit.journaliser(
        g.pool, acteur=appareil_courant(request).acteur, action="maison.home_assistant.oauth", niveau="jaune"
    )
    return {"url": url}


@routeur.get("/home-assistant/oauth/retour", response_model=None)
async def retour_oauth(request: Request, code: str = "", state: str = "") -> RedirectResponse:
    """Retour du navigateur après l'accord dans Home Assistant (route sans jeton : `state` à usage unique + PKCE)."""
    g = gestion(request)
    if not code or not state or len(code) > 2000 or len(state) > 200:
        raise HTTPException(400, "Retour d'autorisation incomplet")
    try:
        await g.ha.terminer_oauth(code, state)
    except ErreurHomeAssistant as exc:
        await audit.journaliser(
            g.pool, acteur="home_assistant", action="maison.home_assistant.oauth_refuse", niveau="jaune"
        )
        raise HTTPException(400, str(exc)) from exc
    await audit.journaliser(g.pool, acteur="home_assistant", action="maison.home_assistant.connecte", niveau="jaune")
    return RedirectResponse("/#reglages/connecteurs", status_code=303)


@routeur.get("")
async def lister(request: Request) -> dict[str, Any]:
    g = gestion(request)
    return {"connecteurs": g.decrire(), "home_assistant": g.decrire_ha(), "outils_actifs": g.outils_actifs()}


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
