"""Routes de la synthèse vocale : réglages, clé ElevenLabs (coffre local), voix Piper (sur accord), phrase en audio."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import synthese
from .securite import audit
from .securite.appareils import Appareil

if TYPE_CHECKING:
    from .api import Contexte

routeur = APIRouter(prefix="/v1")


class Reglages(BaseModel):
    moteur: Literal["navigateur", "piper", "elevenlabs"] | None = None
    voix_piper: str | None = None
    voix_elevenlabs: str | None = Field(None, max_length=40)
    coupure: bool | None = None


class Cle(BaseModel):
    cle: str = Field(min_length=8, max_length=200)


class Phrase(BaseModel):
    texte: str = Field(min_length=1, max_length=synthese.LONGUEUR_MAX)
    moteur: Literal["piper", "elevenlabs"] | None = None


def _ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


def _service(request: Request) -> synthese.ServiceSynthese:
    s = _ctx(request).synthese
    if s is None:
        raise HTTPException(503, "Synthèse vocale indisponible")
    return s


def _appareil(request: Request) -> Appareil:
    a: Appareil = request.state.appareil
    return a


@routeur.get("/synthese")
async def lire(request: Request) -> dict[str, Any]:
    c = _ctx(request)
    return await _service(request).decrire(c.telechargeur)


@routeur.put("/synthese")
async def regler(request: Request, corps: Reglages) -> dict[str, Any]:
    """Choix de la voix (🟡, journalisé) : navigateur, Piper ou ElevenLabs ; coupure quand on parle par-dessus."""
    c, s = _ctx(request), _service(request)
    if corps.voix_piper is not None and corps.voix_piper not in synthese.VOIX_PIPER:
        raise HTTPException(422, "Voix Piper inconnue")
    actuels = await synthese.lire_reglages(c.pool)
    changes = {k: v for k, v in corps.model_dump().items() if v is not None}
    reglages = await synthese.ecrire_reglages(c.pool, {**actuels, **changes})
    await audit.journaliser(
        c.pool, acteur=_appareil(request).acteur, action="synthese.reglages", details=changes, niveau="jaune"
    )
    return await s.decrire(c.telechargeur) | {"reglages": reglages}


@routeur.put("/synthese/cle")
async def definir_cle(request: Request, corps: Cle) -> dict[str, Any]:
    """La clé ElevenLabs va dans le coffre local : jamais renvoyée, journalisée ni stockée en base."""
    c, s = _ctx(request), _service(request)
    await asyncio.to_thread(s.coffre.definir, synthese.CLE_COFFRE, corps.cle.strip())
    await audit.journaliser(c.pool, acteur=_appareil(request).acteur, action="synthese.cle_definie", niveau="jaune")
    return await s.decrire(c.telechargeur)


@routeur.delete("/synthese/cle")
async def supprimer_cle(request: Request) -> dict[str, Any]:
    c, s = _ctx(request), _service(request)
    if await asyncio.to_thread(s.coffre.supprimer, synthese.CLE_COFFRE):
        await audit.journaliser(c.pool, acteur=_appareil(request).acteur, action="synthese.cle_supprimee")
    reglages = await synthese.lire_reglages(c.pool)
    if reglages["moteur"] == "elevenlabs":  # plus de clé : retour à une voix locale
        await synthese.ecrire_reglages(c.pool, {**reglages, "moteur": "navigateur"})
    return await s.decrire(c.telechargeur)


@routeur.post("/synthese/piper/telecharger")
async def telecharger_piper(request: Request) -> dict[str, Any]:
    """Le clic de l'utilisateur vaut accord : la voix Piper choisie est téléchargée en tâche de fond."""
    c, s = _ctx(request), _service(request)
    reglages = await synthese.lire_reglages(c.pool)
    modele = synthese.modele_piper(s.dossier_modeles, reglages["voix_piper"])
    if not s.voix_piper_prete(reglages["voix_piper"]):
        c.telechargeur.lancer(modele)
        await audit.journaliser(
            c.pool,
            acteur=_appareil(request).acteur,
            action="telechargement.lancer",
            details={"modele": "piper", "voix": reglages["voix_piper"]},
        )
    return await s.decrire(c.telechargeur)


@routeur.post("/synthese/dire")
async def dire(request: Request, corps: Phrase) -> Response:
    """Une phrase en audio (WAV de Piper, MP3 d'ElevenLabs). 409 : ce moteur ne peut pas la dire, l'interface la
    lit avec la voix du système (JARVIS n'est jamais muet)."""
    try:
        audio = await _service(request).dire(corps.texte, corps.moteur)
    except synthese.ErreurSynthese as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response(audio.donnees, media_type=audio.type, headers={"X-Voix": audio.moteur, "Cache-Control": "no-store"})
