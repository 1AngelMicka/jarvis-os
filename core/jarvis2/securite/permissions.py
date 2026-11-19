"""Permissions 🟢🟡🔴 et file d'approbations.

Toute action qui agit passe par ici :
- 🟢 `vert`  : exécutée tout de suite (lecture, protection) ;
- 🟡 `jaune` : une demande attend l'approbation d'un appareil autorisé (un clic) ;
- 🔴 `rouge` : la demande ne s'approuve qu'avec une **clé d'accès** (WebAuthn, vérification de l'utilisateur).
Chaque étape (demande, approbation, refus, exécution, échec) est inscrite au journal d'audit chaîné.

En plus (lot F) :
- les **règles de protection** de l'utilisateur (regles.py) passent avant tout : « interdire » refuse l'action, même
  déjà approuvée ; « demander » impose une demande, même pour une action 🟢 ou « toujours autorisée » ;
- **« toujours autoriser »** : une action 🟡 approuvée avec cette case s'exécute ensuite sans demande. Jamais pour une
  action 🔴, ni pour une action marquée `autorisable=False` (clic à l'écran, navigateur, outil externe).
  Une action 🔴 ne s'approuve qu'avec une clé d'accès, depuis n'importe quel appareil : jamais à distance sans elle.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from ..db import Base, Connexion, Ligne
from . import audit, regles
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
    # « Toujours autoriser » possible (🟡 seulement). False pour un clic à l'écran, dans un navigateur, ou un outil
    # dont l'effet n'est pas connu d'avance (MCP) : chaque usage reste approuvé à la main.
    autorisable: bool = True

    @property
    def peut_etre_toujours_autorisee(self) -> bool:
        return self.niveau == "jaune" and self.autorisable

    # Action facultative (connecteur maison…) : proposée et exécutable seulement quand elle renvoie True
    disponible: Callable[[], bool] | None = None

    def est_disponible(self) -> bool:
        return self.disponible is None or self.disponible()


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

    def disponibles(self) -> list[Action]:
        """Actions proposables maintenant (celles d'un connecteur désactivé n'apparaissent pas)."""
        return [a for a in self.actions.values() if a.est_disponible()]


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
    toujours_possible: bool = False  # la case « Toujours autoriser » peut être proposée (🟡 autorisable)

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

    async def _interdite(self, conn: Connexion, action: Action, params: dict[str, Any], acteur: str) -> None:
        """Refus (ErreurAction) si une règle « interdire » vise cette action."""
        interdit, _ = await regles.verifier(conn, action.nom, action.resumer(params), params)
        if interdit is not None:
            await audit.journaliser(
                conn,
                acteur=acteur,
                action="action.refusee_par_regle",
                niveau="jaune",
                cible=str(interdit.id),
                details={"action": action.nom},
            )
            raise ErreurAction(f"Refusé par une règle de protection : « {interdit.libelle} »")

    async def demander(self, nom: str, params: dict[str, Any], appareil: Appareil) -> dict[str, Any]:
        """🟢 : exécute ; 🟡 / 🔴 : crée une demande en attente (🟡 « toujours autorisée » : exécutée).
        Une règle « interdire » refuse ; une règle « demander » impose la demande."""
        action = self.registre.get(nom)
        if not action.est_disponible():
            raise ErreurAction(f"Action indisponible : « {nom} » (connecteur désactivé)")
        async with self.pool.acquire() as conn:
            resume = action.resumer(params)
            interdit, a_demander = await regles.verifier(conn, action.nom, resume, params)
            if interdit is not None:
                await self._interdite(conn, action, params, appareil.acteur)
            if action.niveau == "vert" and a_demander is None:
                return {
                    "statut": "executee",
                    "resultat": await self._executer(conn, action, params, appareil.acteur, None),
                }
            if a_demander is None and action.peut_etre_toujours_autorisee and await self.toujours_autorisee(conn, nom):
                await conn.execute(
                    "UPDATE autorisations_permanentes SET utilisations = utilisations + 1,"
                    " derniere_utilisation = now() WHERE action = $1",
                    nom,
                )
                resultat = await self._executer(conn, action, params, f"{appareil.acteur} (toujours autorisé)", None)
                return {"statut": "executee", "resultat": resultat, "toujours_autorisee": True}
            niveau = "jaune" if action.niveau == "vert" else action.niveau  # règle « demander » sur une action 🟢
            ligne = await conn.fetchrow(
                f"INSERT INTO demandes (action, niveau, resume, parametres, demandeur, expire_le)"
                f" VALUES ($1, $2, $3, $4::text::jsonb, $5, $6) RETURNING {COLONNES}",
                action.nom,
                niveau,
                resume,
                json.dumps(params),
                appareil.acteur,
                datetime.now(UTC) + DUREE_DEMANDE,
            )
            assert ligne is not None
            demande = self._completer(_demande(ligne))
            await audit.journaliser(
                conn,
                acteur=appareil.acteur,
                action="demande.creee",
                niveau=niveau,
                cible=str(demande.id),
                details={
                    "action": action.nom,
                    "resume": resume,
                    **({"regle": str(a_demander.id)} if a_demander is not None else {}),
                },
            )
        return {
            "statut": "en_attente",
            "demande": demande.en_dict(),
            **({"regle": a_demander.libelle} if a_demander is not None else {}),
        }

    # --- « Toujours autoriser » ----------------------------------------------------------------------------

    async def toujours_autorisee(self, conn: Connexion, nom: str) -> bool:
        return bool(await conn.fetchval("SELECT count(*) FROM autorisations_permanentes WHERE action = $1", nom))

    async def autorisations(self) -> list[dict[str, Any]]:
        lignes = await self.pool.fetch(
            "SELECT action, cree_le, utilisations, derniere_utilisation FROM autorisations_permanentes ORDER BY cree_le"
        )
        sortie = []
        for r in lignes:
            action = self.registre.actions.get(r["action"])
            derniere = r["derniere_utilisation"]
            sortie.append(
                {
                    "action": r["action"],
                    "description": action.description if action else "Action qui n'existe plus",
                    "cree_le": r["cree_le"].isoformat(),
                    "utilisations": r["utilisations"],
                    "derniere_utilisation": derniere.isoformat() if derniere else None,
                }
            )
        return sortie

    async def retirer_autorisation(self, nom: str, appareil: Appareil) -> bool:
        """🟢 : retirer une autorisation protège (journalisé)."""
        async with self.pool.acquire() as conn:
            statut = await conn.execute("DELETE FROM autorisations_permanentes WHERE action = $1", nom)
            if statut.endswith(" 0"):
                return False
            await audit.journaliser(conn, acteur=appareil.acteur, action="autorisation.retiree", cible=nom)
        return True

    async def lister(self, statut: str | None = "en_attente", limite: int = 50) -> list[Demande]:
        await self.pool.execute(
            "UPDATE demandes SET statut = 'expiree' WHERE statut = 'en_attente' AND expire_le < now()"
        )
        lignes = await self.pool.fetch(
            f"SELECT {COLONNES} FROM demandes WHERE $1::text IS NULL OR statut = $1 ORDER BY cree_le DESC LIMIT $2",
            statut,
            limite,
        )
        return [self._completer(_demande(r)) for r in lignes]

    def _completer(self, d: Demande) -> Demande:
        action = self.registre.actions.get(d.action)
        possible = action is not None and d.niveau == "jaune" and action.peut_etre_toujours_autorisee
        return replace(d, toujours_possible=possible)

    async def obtenir(self, demande_id: UUID) -> Demande | None:
        ligne = await self.pool.fetchrow(f"SELECT {COLONNES} FROM demandes WHERE id = $1", demande_id)
        return _demande(ligne) if ligne else None

    async def decider(
        self, demande_id: UUID, appareil: Appareil, approuver: bool, methode: str, toujours: bool = False
    ) -> dict[str, Any]:
        """Approuve (puis exécute) ou refuse une demande en attente. 🔴 : `methode` doit être `cle_acces`.
        `toujours` : l'action 🟡 sera ensuite exécutée sans demande (refusé pour 🔴 et les actions non autorisables)."""
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
                action = self.registre.get(demande.action)
                if approuver and toujours and not (demande.niveau == "jaune" and action.peut_etre_toujours_autorisee):
                    raise ErreurAction(
                        "« Toujours autoriser » : impossible pour cette action (🔴, clic à l'écran ou outil externe)"
                    )
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
                if approuver and toujours:
                    await conn.execute(
                        "INSERT INTO autorisations_permanentes (action, cree_par) VALUES ($1, $2)"
                        " ON CONFLICT (action) DO NOTHING",
                        action.nom,
                        appareil.id,
                    )
                    await audit.journaliser(
                        conn,
                        acteur=appareil.acteur,
                        action="autorisation.permanente",
                        niveau="jaune",
                        cible=action.nom,
                        details={"demande": str(demande_id)},
                    )
            if not approuver:
                return {"statut": "refusee"}
            try:
                # Règle ajoutée depuis la demande : elle prime sur l'approbation (la demande passe en échec)
                await self._interdite(conn, action, demande.parametres, appareil.acteur)
                if not action.est_disponible():
                    raise ErreurAction(f"Action indisponible : « {action.nom} » (connecteur désactivé)")
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
