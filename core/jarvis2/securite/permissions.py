"""Permissions 🟢🟡🔴 et file d'approbations.

Toute action qui agit passe par ici :
- 🟢 `vert`  : exécutée tout de suite (lecture, protection) ;
- 🟡 `jaune` : une demande attend l'approbation d'un appareil autorisé (un clic) ;
- 🔴 `rouge` : la demande ne s'approuve qu'avec une **clé d'accès** (WebAuthn, vérification de l'utilisateur).
Chaque étape (demande, approbation, refus, exécution, échec) est inscrite au journal d'audit chaîné.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from ..db import Base, Connexion, Ligne
from . import audit
from .appareils import Appareil

journal = logging.getLogger("jarvis2.permissions")

Niveau = Literal["vert", "jaune", "rouge"]
DUREE_DEMANDE = timedelta(minutes=30)
EMOJI = {"vert": "🟢", "jaune": "🟡", "rouge": "🔴"}

Executeur = Callable[[Connexion, dict[str, Any]], Awaitable[dict[str, Any]]]


STATUTS_LISIBLES = {
    "approuvee": "approuvée",
    "refusee": "refusée",
    "executee": "exécutée",
    "expiree": "expirée",
    "echec": "en échec",
}


class ErreurAction(Exception):
    """Message en français, affichable tel quel."""


@dataclass(frozen=True)
class Action:
    nom: str
    niveau: Niveau
    description: str
    resumer: Callable[[dict[str, Any]], str]
    executer: Executeur


class Registre:
    def __init__(self) -> None:
        self.actions: dict[str, Action] = {}

    def ajouter(self, action: Action) -> None:
        if action.nom in self.actions:
            raise ValueError(f"Action déjà déclarée : {action.nom}")
        self.actions[action.nom] = action

    def get(self, nom: str) -> Action:
        try:
            return self.actions[nom]
        except KeyError as exc:
            raise ErreurAction(f"Action inconnue : « {nom} »") from exc


@dataclass(frozen=True)
class Demande:
    id: UUID
    action: str
    niveau: str
    resume: str
    parametres: dict[str, Any]
    statut: str
    demandeur: str
    cree_le: str
    expire_le: str
    resultat: dict[str, Any] | None

    def en_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "id": str(self.id)}


COLONNES = "id, action, niveau, resume, parametres, statut, demandeur, cree_le, expire_le, resultat"


def _demande(r: Ligne) -> Demande:
    return Demande(
        r["id"],
        r["action"],
        r["niveau"],
        r["resume"],
        r["parametres"],
        r["statut"],
        r["demandeur"],
        r["cree_le"].isoformat(),
        r["expire_le"].isoformat(),
        r["resultat"],
    )


class Approbations:
    def __init__(self, pool: Base, registre: Registre) -> None:
        self.pool = pool
        self.registre = registre

    async def _executer(
        self, conn: Connexion, action: Action, params: dict[str, Any], acteur: str, demande: UUID | None
    ) -> dict[str, Any]:
        try:
            async with conn.transaction():
                resultat = await action.executer(conn, params)
        except ErreurAction as exc:
            await audit.journaliser(
                conn,
                acteur=acteur,
                action=action.nom,
                niveau=action.niveau,
                cible=str(demande) if demande else None,
                details=params,
                resultat=f"echec : {exc}",
            )
            raise
        await audit.journaliser(
            conn,
            acteur=acteur,
            action=action.nom,
            niveau=action.niveau,
            cible=str(demande) if demande else None,
            details={**params, "resultat": resultat},
            resultat="execute",
        )
        return resultat

    async def demander(self, nom: str, params: dict[str, Any], appareil: Appareil) -> dict[str, Any]:
        """🟢 : exécute ; 🟡 / 🔴 : crée une demande en attente."""
        action = self.registre.get(nom)
        async with self.pool.acquire() as conn:
            if action.niveau == "vert":
                return {
                    "statut": "executee",
                    "resultat": await self._executer(conn, action, params, appareil.acteur, None),
                }
            resume = action.resumer(params)
            ligne = await conn.fetchrow(
                f"INSERT INTO demandes (action, niveau, resume, parametres, demandeur, expire_le)"
                f" VALUES ($1, $2, $3, $4::text::jsonb, $5, $6) RETURNING {COLONNES}",
                action.nom,
                action.niveau,
                resume,
                json.dumps(params),
                appareil.acteur,
                datetime.now(UTC) + DUREE_DEMANDE,
            )
            assert ligne is not None
            demande = _demande(ligne)
            await audit.journaliser(
                conn,
                acteur=appareil.acteur,
                action="demande.creee",
                niveau=action.niveau,
                cible=str(demande.id),
                details={"action": action.nom, "resume": resume},
            )
        return {"statut": "en_attente", "demande": demande.en_dict()}

    async def lister(self, statut: str | None = "en_attente", limite: int = 50) -> list[Demande]:
        await self.pool.execute(
            "UPDATE demandes SET statut = 'expiree' WHERE statut = 'en_attente' AND expire_le < now()"
        )
        lignes = await self.pool.fetch(
            f"SELECT {COLONNES} FROM demandes WHERE $1::text IS NULL OR statut = $1 ORDER BY cree_le DESC LIMIT $2",
            statut,
            limite,
        )
        return [_demande(r) for r in lignes]

    async def obtenir(self, demande_id: UUID) -> Demande | None:
        ligne = await self.pool.fetchrow(f"SELECT {COLONNES} FROM demandes WHERE id = $1", demande_id)
        return _demande(ligne) if ligne else None

    async def decider(self, demande_id: UUID, appareil: Appareil, approuver: bool, methode: str) -> dict[str, Any]:
        """Approuve (puis exécute) ou refuse une demande en attente. 🔴 : `methode` doit être `cle_acces`."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                ligne = await conn.fetchrow(
                    f"SELECT {COLONNES} FROM demandes WHERE id = $1 FOR UPDATE",
                    demande_id,
                )
                if ligne is None:
                    raise ErreurAction("Demande introuvable")
                demande = _demande(ligne)
                if demande.statut != "en_attente":
                    raise ErreurAction(f"Demande déjà traitée ({STATUTS_LISIBLES.get(demande.statut, demande.statut)})")
                if await conn.fetchval("SELECT expire_le < now() FROM demandes WHERE id = $1", demande_id):
                    await conn.execute("UPDATE demandes SET statut = 'expiree' WHERE id = $1", demande_id)
                    raise ErreurAction("Demande expirée : relancez l'action")
                if approuver and demande.niveau == "rouge" and methode != "cle_acces":
                    raise ErreurAction("Action 🔴 : approbation par clé d'accès obligatoire")
                statut = "approuvee" if approuver else "refusee"
                await conn.execute(
                    "UPDATE demandes SET statut = $2, decide_le = now(), decide_par = $3, methode = $4 WHERE id = $1",
                    demande_id,
                    statut,
                    appareil.id,
                    methode,
                )
                await audit.journaliser(
                    conn,
                    acteur=appareil.acteur,
                    action=f"demande.{statut}",
                    niveau=demande.niveau,  # type: ignore[arg-type]
                    cible=str(demande_id),
                    details={"action": demande.action, "methode": methode},
                )
            if not approuver:
                return {"statut": "refusee"}
            action = self.registre.get(demande.action)
            try:
                resultat = await self._executer(conn, action, demande.parametres, appareil.acteur, demande_id)
            except ErreurAction as exc:
                await conn.execute(
                    "UPDATE demandes SET statut = 'echec', resultat = $2::text::jsonb WHERE id = $1",
                    demande_id,
                    json.dumps({"erreur": str(exc)}),
                )
                raise
            await conn.execute(
                "UPDATE demandes SET statut = 'executee', resultat = $2::text::jsonb WHERE id = $1",
                demande_id,
                json.dumps(resultat),
            )
        return {"statut": "executee", "resultat": resultat}
