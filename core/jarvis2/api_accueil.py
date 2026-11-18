"""Routes du premier lancement : diagnostic, réparations sûres, état de l'assistant d'accueil, Tailscale."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request

from . import diagnostic
from .config import Parametres
from .db import migrer
from .securite import audit
from .securite.appareils import Appareil
from .tailscale import lire_etat as lire_tailscale

if TYPE_CHECKING:
    from .api import Contexte

routeur = APIRouter(prefix="/v1")


def _ctx(request: Request) -> Contexte:
    c: Contexte = request.app.state.ctx
    return c


def _parametres(request: Request) -> Parametres:
    p: Parametres = request.app.state.parametres
    return p


def _appareil(request: Request) -> Appareil:
    a: Appareil = request.state.appareil
    return a


async def _verifications(request: Request) -> list[dict[str, Any]]:
    c, p = _ctx(request), _parametres(request)
    resultats = await diagnostic.diagnostiquer(
        p, c.pool, c.connecteurs, c.tailscale, c.chargement_modele, urgence_active=c.urgence.actif
    )
    return [v.en_dict() for v in resultats]


@routeur.get("/diagnostic")
async def lire_diagnostic(request: Request) -> dict[str, Any]:
    return {"verifications": await _verifications(request)}


@routeur.post("/diagnostic/reparer/{reparation}")
async def reparer(request: Request, reparation: str) -> dict[str, Any]:
    """Réparations sûres seulement : créer ou mettre à jour le schéma SQLite, télécharger le modèle d'embeddings."""
    c, p, a = _ctx(request), _parametres(request), _appareil(request)
    if reparation == "migrer":
        if p.stockage_effectif != "sqlite":
            raise HTTPException(409, "PostgreSQL : lancez `jarvis2 migrer` (identifiants du propriétaire)")
        appliquees = await migrer(p)
        await audit.journaliser(c.pool, acteur=a.acteur, action="diagnostic.migrer", details={"versions": appliquees})
    elif reparation == "telecharger_modele":
        from .api import precharger_modele

        if c.chargement_modele != "en_cours":
            asyncio.get_running_loop().create_task(precharger_modele(c))
        await audit.journaliser(c.pool, acteur=a.acteur, action="diagnostic.telecharger_modele")
    else:
        raise HTTPException(404, f"Réparation inconnue : « {reparation} »")
    return {"verifications": await _verifications(request)}


@routeur.get("/accueil")
async def accueil(request: Request) -> dict[str, Any]:
    c, p = _ctx(request), _parametres(request)
    valeur = await c.pool.fetchval("SELECT valeur FROM etat_systeme WHERE cle = 'accueil'")
    etat = valeur if isinstance(valeur, dict) else json.loads(valeur or "{}")
    return {
        "termine": bool(etat.get("termine")),
        "stockage": p.stockage_effectif,
        "tailscale": c.tailscale.en_dict(p.port) if c.tailscale else None,
    }


@routeur.post("/accueil/terminer")
async def terminer_accueil(request: Request) -> dict[str, Any]:
    c, a = _ctx(request), _appareil(request)
    await c.pool.execute(
        "UPDATE etat_systeme SET valeur = $1::text::jsonb, maj_le = now() WHERE cle = 'accueil'",
        json.dumps({"termine": True, "par": a.acteur}),
    )
    await audit.journaliser(c.pool, acteur=a.acteur, action="accueil.termine")
    return {"termine": True}


@routeur.get("/tailscale")
async def tailscale(request: Request) -> dict[str, Any]:
    """Relit l'état de Tailscale (après `tailscale up` ou `tailscale serve` lancés par l'utilisateur)."""
    c, p = _ctx(request), _parametres(request)
    c.tailscale = await lire_tailscale(p.port)
    if c.tailscale.adresse:
        request.app.state.origines.add(c.tailscale.adresse)
    return c.tailscale.en_dict(p.port)
