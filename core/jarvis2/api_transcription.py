"""Routes du lot K3 : état et préchauffage de la transcription, transcription anticipée et fin de tour,
reconnaissance du propriétaire, dictée globale."""

from __future__ import annotations

import asyncio
from pathlib import PurePath
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import telechargements
from .dictee import STYLES, preparer
from .fin_tour import evaluer
from .proprietaire import modele_proprietaire
from .securite import audit
from .securite.appareils import Appareil
from .securite.permissions import ErreurAction
from .telechargements import ModeleAbsent
from .transcription import TranscripteurRobuste, TranscriptionEnPause

if TYPE_CHECKING:
    from .api import Contexte
    from .config import Parametres

routeur = APIRouter(prefix="/v1")


def _ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


def _appareil(request: Request) -> Appareil:
    a: Appareil = request.state.appareil
    return a


def _robuste(c: Contexte) -> TranscripteurRobuste:
    if not isinstance(c.transcripteur, TranscripteurRobuste):
        raise HTTPException(404, "Transcription indisponible")
    return c.transcripteur


async def _audio(request: Request) -> bytes:
    audio = await request.body()
    if not audio:
        raise HTTPException(422, "Enregistrement vide")
    return audio


def _erreur(exc: Exception) -> HTTPException:
    if isinstance(exc, ModeleAbsent):
        return HTTPException(409, str(exc))
    if isinstance(exc, TranscriptionEnPause):
        return HTTPException(503, str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(413 if "trop long" in str(exc) else 422, str(exc))
    if isinstance(exc, ErreurAction):
        return HTTPException(422, str(exc))
    return HTTPException(500, f"Transcription impossible : {type(exc).__name__}")


# --- Transcription ------------------------------------------------------------------------------------------


@routeur.get("/voix/transcription")
async def etat_transcription(request: Request) -> dict[str, Any]:
    c = _ctx(request)
    t = _robuste(c)
    etat = await asyncio.to_thread(t.etat)  # première détection de la carte : peut lancer nvidia-smi
    return {**etat, "fin_de_tour": {"modele": c.juge_fin_tour.modele or None}}


@routeur.post("/voix/prechauffer")
async def prechauffer(request: Request) -> dict[str, Any]:
    """Charge Whisper et fait un premier calcul (la première phrase n'attend plus). Ne télécharge jamais rien."""
    t = _robuste(_ctx(request))
    if t.prechauffe:
        return {"prechauffe": True, "duree_ms": 0}
    try:
        duree = await t.prechauffer()
    except Exception as exc:
        raise _erreur(exc) from exc
    return {"prechauffe": True, "duree_ms": round(duree)}


@routeur.post("/voix/anticipee")
async def anticiper(request: Request) -> dict[str, Any]:
    """Phrase envoyée dès le début du silence : texte et fin de tour. Si l'enregistrement final n'apporte que du
    silence, ce texte resservira tel quel (aucune action n'est faite ici)."""
    c = _ctx(request)
    t = _robuste(c)
    audio = await _audio(request)
    try:
        r = await t.transcrire_detail(audio, anticipation=True)
    except Exception as exc:
        raise _erreur(exc) from exc
    fin = await evaluer(r.texte, c.juge_fin_tour)
    return {**r.en_dict(), "fin_de_tour": fin.en_dict()}


class Texte(BaseModel):
    texte: str = Field(max_length=4000)


@routeur.post("/voix/fin-de-tour")
async def fin_de_tour(request: Request, corps: Texte) -> dict[str, Any]:
    return (await evaluer(corps.texte, _ctx(request).juge_fin_tour)).en_dict()


# --- Reconnaissance du propriétaire -----------------------------------------------------------------------


def _modele(request: Request) -> telechargements.Modele:
    p: Parametres = request.app.state.parametres
    return modele_proprietaire(p.dossier_modeles)


async def _etat_proprietaire(request: Request) -> dict[str, Any]:
    c = _ctx(request)
    return {**(await c.proprietaire.etat()), "modele": c.telechargeur.etat(_modele(request)).en_dict()}


@routeur.get("/voix/proprietaire")
async def lire_proprietaire(request: Request) -> dict[str, Any]:
    return await _etat_proprietaire(request)


class ReglagesProprietaire(BaseModel):
    actif: bool | None = None
    seuil: float | None = Field(None, ge=0.2, le=0.9)


@routeur.put("/voix/proprietaire")
async def regler_proprietaire(request: Request, corps: ReglagesProprietaire) -> dict[str, Any]:
    c = _ctx(request)
    reglages = await c.proprietaire.regler(corps.actif, corps.seuil)
    await audit.journaliser(
        c.pool, acteur=_appareil(request).acteur, action="voix.proprietaire.regle", details=reglages
    )
    return await _etat_proprietaire(request)


@routeur.post("/voix/proprietaire/empreintes")
async def inscrire(request: Request) -> dict[str, Any]:
    """Corps : un enregistrement de la voix du propriétaire (3 s de parole au moins). Seul le vecteur est gardé."""
    c = _ctx(request)
    t = _robuste(c)
    audio = await _audio(request)
    try:
        r = await t.analyser(audio)
        empreinte = await c.proprietaire.inscrire(r)
    except Exception as exc:
        raise _erreur(exc) from exc
    await audit.journaliser(
        c.pool, acteur=_appareil(request).acteur, action="voix.empreinte.ajoutee", cible=empreinte["id"]
    )
    return {"empreinte": empreinte, **(await _etat_proprietaire(request))}


@routeur.delete("/voix/proprietaire/empreintes/{ident}")
async def retirer(request: Request, ident: str) -> dict[str, Any]:
    c = _ctx(request)
    if not await c.proprietaire.retirer(ident):
        raise HTTPException(404, "Empreinte introuvable")
    await audit.journaliser(c.pool, acteur=_appareil(request).acteur, action="voix.empreinte.retiree", cible=ident)
    return await _etat_proprietaire(request)


# --- Dictée -------------------------------------------------------------------------------------------------


class Correction(BaseModel):
    de: str = Field(max_length=80)
    vers: str = Field(max_length=200)


class ReglagesDictee(BaseModel):
    actif: bool | None = None
    corrections: list[Correction] | None = Field(None, max_length=200)
    styles: dict[str, str] | None = None


async def _etat_dictee(request: Request) -> dict[str, Any]:
    from .api_securite import est_local

    c = _ctx(request)
    return {**(await c.dictee.charger()), "styles_possibles": list(STYLES), "collage_possible": est_local(request)}


@routeur.get("/dictee")
async def lire_dictee(request: Request) -> dict[str, Any]:
    return await _etat_dictee(request)


@routeur.put("/dictee")
async def regler_dictee(request: Request, corps: ReglagesDictee) -> dict[str, Any]:
    c = _ctx(request)
    corrections = [x.model_dump() for x in corps.corrections] if corps.corrections is not None else None
    reglages = await c.dictee.regler(corps.actif, corrections, corps.styles)
    await audit.journaliser(
        c.pool,
        acteur=_appareil(request).acteur,
        action="dictee.reglee",
        details={"actif": reglages["actif"], "corrections": len(reglages["corrections"])},
    )
    return await _etat_dictee(request)


@routeur.post("/dictee")
async def dicter(request: Request) -> dict[str, Any]:
    """Corps : l'enregistrement pendant que le raccourci était tenu. `?coller=1` : collé dans l'application au
    premier plan (depuis le PC seulement, jamais en mode sans écran)."""
    from .api_securite import est_local

    c = _ctx(request)
    reglages = await c.dictee.charger()
    if not reglages["actif"]:
        raise HTTPException(409, "Dictée désactivée : activez-la dans Réglages › Voix & écoute")
    t = _robuste(c)
    audio = await _audio(request)
    coller = request.query_params.get("coller") in ("1", "oui", "true")
    if coller and (c.sans_ecran or not est_local(request)):
        raise HTTPException(403, "Collage possible seulement sur le PC lui-même, hors mode sans écran")
    programme = await asyncio.to_thread(c.dictee.premier_plan) if coller else None
    try:
        r = await t.transcrire_detail(audio)
    except Exception as exc:
        raise _erreur(exc) from exc
    texte, style = preparer(r.texte, reglages, programme)
    colle = False
    if coller and texte:
        try:
            await asyncio.to_thread(c.dictee.colleur, texte)
            colle = True
        except Exception as exc:
            raise HTTPException(500, f"Collage impossible : {exc}") from exc
    nom = PurePath(programme.replace("\\", "/")).name.lower() if programme else None
    # Jamais le texte dicté au journal d'audit : seulement où et combien
    await audit.journaliser(
        c.pool,
        acteur=_appareil(request).acteur,
        action="dictee.collee" if colle else "dictee.transcrite",
        details={"programme": nom, "style": style, "caracteres": len(texte)},
    )
    return {"texte": texte, "style": style, "programme": nom, "colle": colle, "transcription": r.en_dict()}
