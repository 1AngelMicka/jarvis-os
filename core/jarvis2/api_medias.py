"""Routes des créations (bac à sable), de la vision sur demande et de la voix (transcription locale)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import creations, vision, voix
from .ecran import garde_ecran
from .moteurs.base import ErreurMoteur
from .securite import audit
from .securite.appareils import Appareil
from .telechargements import ModeleAbsent

if TYPE_CHECKING:
    from .api import Contexte

routeur = APIRouter(prefix="/v1")
routeur_pages = APIRouter()  # pages des créations : hors de /v1, protégées par un jeton signé (iframe)


def _ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


def _appareil(request: Request) -> Appareil:
    a: Appareil = request.state.appareil
    return a


def _propre(ligne: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v.isoformat() if isinstance(v, datetime) else str(v) if isinstance(v, UUID) else v for k, v in ligne.items()
    }


# --- Créations ----------------------------------------------------------------------------------------------


class NouvelleCreation(BaseModel):
    titre: str = Field(min_length=1, max_length=200)
    demande: str = Field(min_length=3, max_length=8000)


class Modification(BaseModel):
    demande: str = Field(min_length=3, max_length=8000)


@routeur.get("/creations")
async def lister_creations(request: Request) -> dict[str, Any]:
    return {"creations": [_propre(c) for c in await creations.lister(_ctx(request).pool)]}


@routeur.post("/creations")
async def creer_creation(request: Request, corps: NouvelleCreation) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    try:
        resultat = await creations.creer(c.pool, c.service, corps.titre, corps.demande, a.acteur)
    except (ErreurMoteur, ValueError) as exc:
        raise HTTPException(502, str(exc)) from exc
    await audit.journaliser(c.pool, acteur=a.acteur, action="creation.creee", cible=resultat["id"])
    return resultat


@routeur.post("/creations/{ident}/modifier")
async def modifier_creation(request: Request, ident: UUID, corps: Modification) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    try:
        resultat = await creations.modifier(c.pool, c.service, ident, corps.demande)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ErreurMoteur, ValueError) as exc:
        raise HTTPException(502, str(exc)) from exc
    await audit.journaliser(c.pool, acteur=a.acteur, action="creation.modifiee", cible=str(ident))
    return resultat


@routeur.get("/creations/{ident}/lien")
async def lien_creation(request: Request, ident: UUID) -> dict[str, Any]:
    p = await creations.page(_ctx(request).pool, ident)
    if p is None:
        raise HTTPException(404, "Création introuvable")
    version = int(p["version"])
    return {"url": f"/creations/{ident}?v={version}&j={creations.jeton(ident, version)}", "version": version}


def _hote(request: Request) -> str:
    """Hôte de la requête, réduit aux caractères d'un nom d'hôte (il entre dans la CSP)."""
    return re.sub(r"[^A-Za-z0-9.:\[\]-]", "", request.headers.get("host", "localhost"))


@routeur_pages.get("/creations/{ident}", response_class=HTMLResponse)
async def page_creation(request: Request, ident: UUID, v: int, j: str) -> HTMLResponse:
    if not creations.verifier_jeton(ident, v, j):
        raise HTTPException(403, "Lien de création expiré ou invalide")
    p = await creations.page(_ctx(request).pool, ident, v)
    if p is None:
        raise HTTPException(404, "Création introuvable")
    entetes = {
        "Content-Security-Policy": creations.CSP_CREATION.format(origine=f"{request.url.scheme}://{_hote(request)}"),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    }
    return HTMLResponse(p["html"], headers=entetes)


# --- Vision sur demande -------------------------------------------------------------------------------------


class DemandeVision(BaseModel):
    image: str = Field(max_length=12_000_000)  # data URL
    question: str | None = Field(default=None, max_length=2000)
    forcer_modele: bool = False  # passer l'OCR et décrire par le modèle de vision local


@routeur.post("/vision/decrire", dependencies=[Depends(garde_ecran)])  # capture d'écran : refusée sans écran
async def decrire(request: Request, corps: DemandeVision) -> dict[str, Any]:
    """Uniquement sur demande explicite : l'image vient d'une capture déclenchée par l'utilisateur."""
    c, a = _ctx(request), _appareil(request)
    try:
        image = vision.decoder(corps.image)
        joignable = c.pc.ollama.joignable if c.pc is not None else None
        resultat = await vision.analyser(
            c.url_ollama, c.modele_vision, image, corps.question, c.ocr, joignable, corps.forcer_modele
        )
    except vision.ErreurVision as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit.journaliser(
        c.pool, acteur=a.acteur, action="vision.decrite", details={"octets": len(image), "methode": resultat["methode"]}
    )
    return resultat  # OCR d'abord ; modèle de vision local seulement s'il y a peu de texte


# --- Voix -----------------------------------------------------------------------------------------------------


@routeur.post("/voix/transcrire")
async def transcrire(request: Request) -> dict[str, Any]:
    """Corps : l'enregistrement brut (webm/ogg/wav) ; transcription sur le PC, mot d'éveil « Jarvis »."""
    c = _ctx(request)
    if c.transcripteur is None:
        raise HTTPException(404, "Transcription indisponible")
    audio = await request.body()
    if not audio:
        raise HTTPException(422, "Enregistrement vide")
    try:
        resultat = await voix.transcrire(c.transcripteur, audio)
    except ModeleAbsent as exc:  # jamais téléchargé en silence : l'utilisateur l'accepte dans le diagnostic
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(413, str(exc)) from exc
    except Exception as exc:  # décodage audio…
        raise HTTPException(500, f"Transcription impossible : {type(exc).__name__}") from exc
    return resultat.en_dict()
