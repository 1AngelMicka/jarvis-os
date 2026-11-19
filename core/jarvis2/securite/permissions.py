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

En plus (phase 14, point B 7) :
- **empreinte du plan exact** : à la création, le Core calcule l'empreinte SHA-256 du texte canonique de la demande
  (action, niveau, résumé, paramètres ; `empreinte_plan`). L'approbation n'est reçue que de l'interface, avec
  l'empreinte qu'elle a affichée : si elle diffère, ou si la demande enregistrée ne correspond plus à son empreinte,
  l'approbation tombe (demande en échec, à relancer). L'empreinte est revérifiée juste avant d'exécuter. Le modèle
  ne peut rien approuver : aucune action du registre ni aucun bloc du pilotage n'appelle `decider`.
  Une action dont la cible peut changer entre la demande et l'approbation (contenu d'un atelier) « fige » cet état
  dans ses paramètres (`Action.figer`) : il entre dans l'empreinte et l'exécution le revérifie ;
- **pile d'annulation** : chaque action 🟡 déclare si elle est réversible et comment l'annuler (`annuler`,
  `annulation`). Une action réversible exécutée entre dans la pile (`annulations`, 24 h) ; « Annuler » (interface ou
  commande rapide) rejoue son annulation, inscrite au journal d'audit.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from ..db import Base, Connexion, Ligne
from . import audit, barriere, regles
from .appareils import Appareil

journal = logging.getLogger("jarvis2.permissions")

Niveau = Literal["vert", "jaune", "rouge"]
DUREE_DEMANDE = timedelta(minutes=30)
DELAI_REPORT = timedelta(minutes=15)  # « plus tard » : rappel poussé au téléphone 15 minutes après
REPORTS_MAX = 3
DUREE_ANNULATION = timedelta(hours=24)  # une action reste annulable un jour
PILE_MAX = 30  # entrées listées dans « Dernières actions annulables »
EMOJI = {"vert": "🟢", "jaune": "🟡", "rouge": "🔴"}

INTERDITS = ("deverrouill", "unlock")  # noms d'action refusés par le registre

Executeur = Callable[[Connexion, dict[str, Any]], Awaitable[dict[str, Any]]]
# Annulation : (connexion, paramètres de l'action, résultat de l'exécution, état d'avant compris) → résultat
Annuleur = Callable[[Connexion, dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]
# Figeage : (connexion, paramètres) → paramètres complétés par le Core (état de la cible qui entre dans l'empreinte)
Figeur = Callable[[Connexion, dict[str, Any]], Awaitable[dict[str, Any]]]


def _canonique(valeur: Any) -> Any:
    """Nombres entiers écrits en flottant ramenés à l'entier : `jsonb` relit 1e2 comme 100."""
    if isinstance(valeur, dict):
        return {str(c): _canonique(v) for c, v in valeur.items()}
    if isinstance(valeur, list | tuple):
        return [_canonique(v) for v in valeur]
    if isinstance(valeur, float) and valeur.is_integer():
        return int(valeur)
    return valeur


def empreinte_plan(action: str, niveau: str, resume: str, parametres: dict[str, Any]) -> str:
    """Empreinte SHA-256 du plan exact : JSON canonique (clés triées, sans espaces, UTF-8) de ce qui sera exécuté."""
    texte = json.dumps(
        _canonique({"action": action, "niveau": niveau, "resume": resume, "parametres": parametres}),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(texte.encode()).hexdigest()


def empreinte_courte(empreinte: str | None) -> str | None:
    """Ce que l'interface affiche : 8 caractères en deux groupes (« 3fa2 9c01 »)."""
    return f"{empreinte[:4]} {empreinte[4:8]}" if empreinte else None


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

    # Action 🟢 qui écrit ou envoie (réglage, état changé) : refusée comme une 🟡 dans un tour contaminé
    ecrit: bool = False

    # Pile d'annulation : comment revenir en arrière (None : irréversible). `annulation` dit, en clair, comment
    # l'action s'annule — ou pourquoi elle ne s'annule pas et quoi faire à la main. Toute action 🟡 le déclare.
    annuler: Annuleur | None = None
    annulation: str = ""
    # Cette exécution-là peut-elle être annulée ? (état d'avant illisible, commande sans inverse…) ; None : oui
    annulable: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None

    # État de la cible figé dans les paramètres à la demande (il entre dans l'empreinte ; l'exécution le revérifie)
    figer: Figeur | None = None

    def est_disponible(self) -> bool:
        return self.disponible is None or self.disponible()

    @property
    def reversible(self) -> bool:
        return self.annuler is not None

    def peut_annuler(self, params: dict[str, Any], resultat: dict[str, Any]) -> bool:
        return self.annuler is not None and (self.annulable is None or self.annulable(params, resultat))


class Registre:
    def __init__(self) -> None:
        self.actions: dict[str, Action] = {}

    def ajouter(self, action: Action) -> None:
        # Jamais de déverrouillage (session du PC, téléphone) : ni à distance ni sur place, aucune action ne le fait
        if any(m in action.nom.lower() for m in INTERDITS):
            raise ValueError(f"Action interdite par conception : {action.nom}")
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
    rappel_le: str | None = None  # « plus tard » : heure du rappel
    reports: int = 0
    empreinte: str | None = None  # SHA-256 du plan exact (None : demande d'avant la migration 025)
    reversible: bool = False  # l'action se défait (« Annuler ») une fois exécutée

    def en_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "id": str(self.id), "empreinte_courte": empreinte_courte(self.empreinte)}

    def empreinte_attendue(self) -> str:
        return empreinte_plan(self.action, self.niveau, self.resume, self.parametres)


COLONNES = (
    "id, action, niveau, resume, parametres, statut, demandeur, cree_le, expire_le, resultat, rappel_le, reports,"
    " empreinte"
)
COLONNES_PILE = "id, action, resume, comment, parametres, resultat, demande_id, acteur, statut, cree_le, expire_le"


class PlanChange(ErreurAction):
    """L'approbation ne correspond plus au plan exact : elle tombe (la demande passe en échec)."""


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
        rappel_le=r["rappel_le"].isoformat() if r["rappel_le"] else None,
        reports=r["reports"],
        empreinte=r["empreinte"],
    )


def _entree_pile(r: Ligne) -> dict[str, Any]:
    return {
        "id": str(r["id"]),
        "action": r["action"],
        "resume": r["resume"],
        "comment": r["comment"],
        "demande_id": str(r["demande_id"]) if r["demande_id"] else None,
        "acteur": r["acteur"],
        "statut": r["statut"],
        "cree_le": r["cree_le"].isoformat(),
        "expire_le": r["expire_le"].isoformat(),
    }


class Approbations:
    def __init__(self, pool: Base, registre: Registre) -> None:
        self.pool = pool
        self.registre = registre
        # Prévenu de chaque nouvelle demande (notification poussée au téléphone) ; jamais bloquant
        self.apres_demande: Callable[[Demande], Awaitable[Any]] | None = None

    async def _executer(
        self,
        conn: Connexion,
        action: Action,
        params: dict[str, Any],
        acteur: str,
        demande: UUID | None,
        resume: str | None = None,
        niveau: str | None = None,
        empreinte: str | None = None,
    ) -> dict[str, Any]:
        """Exécute (transaction), journalise, puis empile l'annulation si l'action est réversible.
        `empreinte` : celle de la demande approuvée, revérifiée ici, juste avant d'agir, sur les paramètres exécutés."""
        if empreinte is not None and demande is not None:
            reelle = empreinte_plan(action.nom, niveau or action.niveau, resume or "", params)
            if reelle != empreinte:
                raise PlanChange("Le plan exécuté n'est pas celui approuvé (empreinte différente) : rien n'est fait")
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
            details={**params, "resultat": resultat, **({"empreinte": empreinte} if empreinte else {})},
            resultat="execute",
        )
        if action.peut_annuler(params, resultat):
            entree = await self._empiler(conn, action, params, resultat, acteur, demande, resume)
            return {**resultat, "annulation": entree}
        return resultat

    async def _empiler(
        self,
        conn: Connexion,
        action: Action,
        params: dict[str, Any],
        resultat: dict[str, Any],
        acteur: str,
        demande: UUID | None,
        resume: str | None,
    ) -> dict[str, Any]:
        ligne = await conn.fetchrow(
            "INSERT INTO annulations (action, resume, comment, parametres, resultat, demande_id, acteur, expire_le)"
            f" VALUES ($1, $2, $3, $4::text::jsonb, $5::text::jsonb, $6, $7, $8) RETURNING {COLONNES_PILE}",
            action.nom,
            resume or action.resumer(params),
            action.annulation or "Revenir à l'état d'avant",
            json.dumps(params),
            json.dumps(resultat),
            demande,
            acteur,
            datetime.now(UTC) + DUREE_ANNULATION,
        )
        assert ligne is not None
        return _entree_pile(ligne)

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
            if action.figer is not None:  # état de la cible calculé par le Core : il entre dans l'empreinte
                params = await action.figer(conn, params)
            resume = action.resumer(params)
            # Tour contaminé (contenu non fiable lu) : aucune action qui agit, même 🟢 « écrit » ou toujours autorisée
            await barriere.verifier(conn, action, resume, appareil.acteur)
            interdit, a_demander = await regles.verifier(conn, action.nom, resume, params)
            if interdit is not None:
                await self._interdite(conn, action, params, appareil.acteur)
            if action.niveau == "vert" and a_demander is None:
                return {
                    "statut": "executee",
                    "resultat": await self._executer(conn, action, params, appareil.acteur, None, resume),
                }
            if a_demander is None and action.peut_etre_toujours_autorisee and await self.toujours_autorisee(conn, nom):
                await conn.execute(
                    "UPDATE autorisations_permanentes SET utilisations = utilisations + 1,"
                    " derniere_utilisation = now() WHERE action = $1",
                    nom,
                )
                acteur = f"{appareil.acteur} (toujours autorisé)"
                resultat = await self._executer(conn, action, params, acteur, None, resume)
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
            # Empreinte calculée sur la demande RELUE (paramètres tels que la base les rend) : stable ensuite
            relue = _demande(ligne)
            empreinte = relue.empreinte_attendue()
            await conn.execute("UPDATE demandes SET empreinte = $2 WHERE id = $1", relue.id, empreinte)
            demande = self.completer(replace(relue, empreinte=empreinte))
            await audit.journaliser(
                conn,
                acteur=appareil.acteur,
                action="demande.creee",
                niveau=niveau,
                cible=str(demande.id),
                details={
                    "action": action.nom,
                    "resume": resume,
                    "empreinte": empreinte,
                    **({"regle": str(a_demander.id)} if a_demander is not None else {}),
                },
            )
        if self.apres_demande is not None:
            try:
                await self.apres_demande(demande)
            except Exception:  # une notification ratée ne fait jamais échouer la demande
                journal.exception("Notification de la demande %s", demande.id)
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
        return [self.completer(_demande(r)) for r in lignes]

    def completer(self, d: Demande) -> Demande:
        action = self.registre.actions.get(d.action)
        possible = action is not None and d.niveau == "jaune" and action.peut_etre_toujours_autorisee
        return replace(d, toujours_possible=possible, reversible=action is not None and action.reversible)

    async def obtenir(self, demande_id: UUID) -> Demande | None:
        ligne = await self.pool.fetchrow(f"SELECT {COLONNES} FROM demandes WHERE id = $1", demande_id)
        return _demande(ligne) if ligne else None

    async def reporter(self, demande_id: UUID, appareil: Appareil) -> Demande:
        """« Plus tard » : la demande reste en attente ; rappel dans 15 minutes (3 fois au plus). Ne décide rien."""
        async with self.pool.acquire() as conn, conn.transaction():
            ligne = await conn.fetchrow(f"SELECT {COLONNES} FROM demandes WHERE id = $1 FOR UPDATE", demande_id)
            if ligne is None:
                raise ErreurAction("Demande introuvable")
            demande = _demande(ligne)
            if demande.statut != "en_attente" or datetime.fromisoformat(demande.expire_le) < datetime.now(UTC):
                raise ErreurAction("Demande déjà traitée ou expirée")
            if demande.reports >= REPORTS_MAX:
                raise ErreurAction(f"Déjà reportée {REPORTS_MAX} fois : décidez maintenant (oui ou non)")
            rappel = datetime.now(UTC) + DELAI_REPORT
            expire = max(datetime.fromisoformat(demande.expire_le), rappel + DELAI_REPORT)
            ligne = await conn.fetchrow(
                "UPDATE demandes SET rappel_le = $2, expire_le = $3, reports = reports + 1 WHERE id = $1"
                f" RETURNING {COLONNES}",
                demande_id,
                rappel,
                expire,
            )
            assert ligne is not None
            await audit.journaliser(
                conn,
                acteur=appareil.acteur,
                action="demande.reportee",
                niveau=demande.niveau,  # type: ignore[arg-type]
                cible=str(demande_id),
                details={"action": demande.action, "rappel_le": rappel.isoformat()},
            )
        return self.completer(_demande(ligne))

    async def rappels_dus(self) -> list[Demande]:
        """Demandes reportées dont le rappel est dû (le rappel est consommé : un seul envoi)."""
        lignes = await self.pool.fetch(
            f"UPDATE demandes SET rappel_le = NULL WHERE statut = 'en_attente' AND rappel_le IS NOT NULL"
            f" AND rappel_le <= $1 AND expire_le > $1 RETURNING {COLONNES}",
            datetime.now(UTC),
        )
        return [self.completer(_demande(r)) for r in lignes]

    async def decider(
        self,
        demande_id: UUID,
        appareil: Appareil,
        approuver: bool,
        methode: str,
        toujours: bool = False,
        empreinte: str | None = None,
    ) -> dict[str, Any]:
        """Approuve (puis exécute) ou refuse une demande en attente. 🔴 : `methode` doit être `cle_acces`.
        `toujours` : l'action 🟡 sera ensuite exécutée sans demande (refusé pour 🔴 et les actions non autorisables).
        `empreinte` : celle que l'interface a affichée (l'API l'exige) ; différente de celle de la demande, ou demande
        enregistrée qui ne correspond plus à son empreinte : l'approbation tombe (demande en échec, à relancer)."""
        async with self.pool.acquire() as conn:
            plan_change: str | None = None
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
                if approuver:
                    plan_change = self._plan_change(demande, empreinte)
                if plan_change is not None:
                    await conn.execute(
                        "UPDATE demandes SET statut = 'echec', resultat = $2::text::jsonb WHERE id = $1",
                        demande_id,
                        json.dumps({"erreur": plan_change}),
                    )
                    await audit.journaliser(
                        conn,
                        acteur=appareil.acteur,
                        action="demande.empreinte_invalide",
                        niveau=demande.niveau,  # type: ignore[arg-type]
                        cible=str(demande_id),
                        details={"action": demande.action, "attendue": demande.empreinte, "recue": empreinte},
                        resultat=plan_change,
                    )
            if plan_change is not None:
                raise PlanChange(plan_change)
            async with conn.transaction():
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
                    details={
                        "action": demande.action,
                        "methode": methode,
                        **({"empreinte": demande.empreinte, "confirmation": "interface"} if approuver else {}),
                    },
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
                resultat = await self._executer(
                    conn,
                    action,
                    demande.parametres,
                    appareil.acteur,
                    demande_id,
                    demande.resume,
                    demande.niveau,
                    demande.empreinte,
                )
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

    @staticmethod
    def _plan_change(demande: Demande, empreinte: str | None) -> str | None:
        """Raison pour laquelle l'approbation tombe, ou None si le plan approuvé est bien celui de la demande."""
        if demande.empreinte is None:
            return "Demande sans empreinte (antérieure à la mise à jour) : relancez l'action"
        if demande.empreinte != demande.empreinte_attendue():
            return "Le plan enregistré a changé depuis la demande : approbation annulée, relancez l'action"
        if empreinte is not None and empreinte.strip().lower() != demande.empreinte:
            return "Vous avez approuvé un autre plan que celui de la demande : approbation annulée, relancez l'action"
        return None

    # --- Pile d'annulation ------------------------------------------------------------------------------------

    async def annulables(self, limite: int = PILE_MAX) -> list[dict[str, Any]]:
        """Dernières actions encore annulables, la plus récente d'abord (les entrées de plus de 24 h périment)."""
        await self.pool.execute(
            "UPDATE annulations SET statut = 'perimee' WHERE statut = 'disponible' AND expire_le < $1",
            datetime.now(UTC),
        )
        lignes = await self.pool.fetch(
            f"SELECT {COLONNES_PILE} FROM annulations WHERE statut = 'disponible' ORDER BY cree_le DESC LIMIT $1",
            limite,
        )
        return [_entree_pile(r) for r in lignes]

    async def annuler(self, ident: UUID | None, appareil: Appareil) -> dict[str, Any]:
        """« Annuler » : rejoue l'annulation déclarée par l'action (la plus récente si `ident` est None).
        Geste de l'utilisateur dans l'interface (bouton ou commande rapide), inscrit au journal d'audit."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if ident is None:
                    ligne = await conn.fetchrow(
                        f"SELECT {COLONNES_PILE} FROM annulations WHERE statut = 'disponible' AND expire_le > $1"
                        " ORDER BY cree_le DESC LIMIT 1 FOR UPDATE",
                        datetime.now(UTC),
                    )
                    if ligne is None:
                        raise ErreurAction("Rien à annuler")
                else:
                    ligne = await conn.fetchrow(
                        f"SELECT {COLONNES_PILE} FROM annulations WHERE id = $1 FOR UPDATE", ident
                    )
                    if ligne is None:
                        raise ErreurAction("Action à annuler introuvable")
                if ligne["statut"] != "disponible":
                    raise ErreurAction("Action déjà annulée ou plus annulable")
                if ligne["expire_le"] < datetime.now(UTC):
                    await conn.execute("UPDATE annulations SET statut = 'perimee' WHERE id = $1", ligne["id"])
                    raise ErreurAction("Trop ancienne pour être annulée (24 h au plus)")
                action = self.registre.actions.get(ligne["action"])
                if action is None or action.annuler is None:
                    raise ErreurAction("Cette action ne s'annule plus")
                # Pris tout de suite : un double clic n'annule pas deux fois
                await conn.execute(
                    "UPDATE annulations SET statut = 'annulee', annule_le = $2, annule_par = $3 WHERE id = $1",
                    ligne["id"],
                    datetime.now(UTC),
                    appareil.acteur,
                )
            entree = _entree_pile(ligne)
            details = {"action": action.nom, "demande": entree["demande_id"], "comment": action.annulation}
            try:
                async with conn.transaction():
                    resultat = await action.annuler(conn, ligne["parametres"], ligne["resultat"])
            except ErreurAction as exc:
                await conn.execute(
                    "UPDATE annulations SET statut = 'echec', detail = $2 WHERE id = $1", ligne["id"], str(exc)[:500]
                )
                await audit.journaliser(
                    conn,
                    acteur=appareil.acteur,
                    action="annulation.echec",
                    niveau="jaune",
                    cible=entree["id"],
                    details=details,
                    resultat=f"echec : {exc}",
                )
                raise
            await audit.journaliser(
                conn,
                acteur=appareil.acteur,
                action="annulation.executee",
                niveau="jaune",
                cible=entree["id"],
                details={**details, "resultat": resultat},
            )
        return {"statut": "annulee", "annulation": {**entree, "statut": "annulee"}, "resultat": resultat}
