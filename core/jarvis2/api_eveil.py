"""Routes de l'éveil « Dis Jarvis » (phase 13, lot K1) : phrases captées, état de la conversation vocale, réglages.

Les horodatages viennent de l'horloge de l'appareil (en-têtes `X-Debut` et `X-Fin`, millisecondes depuis 1970) : le
Core ne les compare qu'entre eux, jamais à sa propre horloge.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .config import Parametres
from .eveil import ServiceEveil, dossier_eveil, maintenant_ms, modele_eveil
from .securite import audit
from .securite.appareils import Appareil
from .telechargements import ModeleAbsent, est_pret

if TYPE_CHECKING:
    from .api import Contexte

routeur = APIRouter(prefix="/v1")


def _ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


def _appareil(request: Request) -> Appareil:
    a: Appareil = request.state.appareil
    return a


def _parametres(request: Request) -> Parametres:
    p: Parametres = request.app.state.parametres
    return p


def _service(request: Request) -> ServiceEveil:
    s = _ctx(request).eveil
    if s.acoustique.dossier is None:
        s.acoustique.dossier = dossier_eveil(_parametres(request).dossier_modeles)
    return s


def _horodatage(valeur: str | None, defaut: float) -> float:
    try:
        t = float(valeur) if valeur is not None else defaut
    except ValueError:
        return defaut
    return t if math.isfinite(t) and t > 0 else defaut


async def _etat(request: Request) -> dict[str, Any]:
    c, s = _ctx(request), _service(request)
    return {
        "reglages": await s.lire_reglages(),
        "conversation": s.etat(str(_appareil(request).id)),
        "acoustique": s.etat_acoustique(),
        "telechargement": c.telechargeur.etat(modele_eveil(_parametres(request).dossier_modeles)).en_dict(),
        "ambiance": {"phrases": len(s.ambiance.phrases), "derniere": s.ambiance.derniere},
    }


@routeur.get("/voix/eveil")
async def lire(request: Request) -> dict[str, Any]:
    return await _etat(request)


class Reglages(BaseModel):
    ambiance: bool | None = None
    openwakeword: bool | None = None
    relance_s: int | None = Field(default=None, ge=2, le=20)


@routeur.put("/voix/eveil")
async def regler(request: Request, corps: Reglages) -> dict[str, Any]:
    c, s, a = _ctx(request), _service(request), _appareil(request)
    avant = await s.lire_reglages()
    apres = await s.regler(**corps.model_dump())
    changes = {k: v for k, v in apres.items() if avant.get(k) != v}
    if changes:
        await audit.journaliser(c.pool, acteur=a.acteur, action="voix.eveil.regle", details=changes)
    return await _etat(request)


@routeur.post("/voix/ecoute")
async def ecouter(request: Request) -> dict[str, Any]:
    """Corps : la phrase captée (webm/ogg/wav) ; en-têtes `X-Debut` / `X-Fin` : ses horodatages sur l'appareil."""
    c = _ctx(request)
    if c.transcripteur is None:
        raise HTTPException(404, "Transcription indisponible")
    audio = await request.body()
    if not audio:
        raise HTTPException(422, "Enregistrement vide")
    maintenant = maintenant_ms()
    fin = _horodatage(request.headers.get("x-fin"), maintenant)
    debut = min(_horodatage(request.headers.get("x-debut"), fin), fin)
    try:
        return await _service(request).ecouter(str(_appareil(request).id), c.transcripteur, audio, debut, fin)
    except ModeleAbsent as exc:  # jamais téléchargé en silence : l'utilisateur l'accepte dans le diagnostic
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(413, str(exc)) from exc
    except Exception as exc:  # décodage audio…
        raise HTTPException(500, f"Transcription impossible : {type(exc).__name__}") from exc


class Evenement(BaseModel):
    evenement: Literal["parole_fin", "reponse_debut", "annuler"]
    t: float | None = Field(default=None, gt=0)


@routeur.post("/voix/ecoute/evenement")
async def signaler(request: Request, corps: Evenement) -> dict[str, Any]:
    """L'interface dit quand la voix de JARVIS s'est tue (début de la fenêtre de relance), ou qu'un envoi a échoué."""
    t = corps.t if corps.t is not None and math.isfinite(corps.t) else maintenant_ms()
    return _service(request).signaler(str(_appareil(request).id), corps.evenement, t)


@routeur.post("/voix/eveil/modele")
async def telecharger(request: Request) -> dict[str, Any]:
    """Le clic de l'utilisateur vaut accord : modèle « Dis Jarvis » d'openWakeWord, téléchargé en tâche de fond."""
    c, a = _ctx(request), _appareil(request)
    modele = modele_eveil(_parametres(request).dossier_modeles)
    if est_pret(modele) and not c.telechargeur.actif(modele):
        return await _etat(request)
    c.telechargeur.lancer(modele)
    await audit.journaliser(c.pool, acteur=a.acteur, action="telechargement.lancer", details={"modele": "eveil"})
    return await _etat(request)


@routeur.post("/voix/ambiance/oublier")
async def oublier(request: Request) -> dict[str, Any]:
    """Oublie tout de suite les phrases d'ambiance encore en mémoire vive (rien n'en est retenu)."""
    _service(request).ambiance.oublier()
    return await _etat(request)
