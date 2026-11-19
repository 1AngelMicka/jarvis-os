"""Veille des sessions Claude Code de l'utilisateur, en LECTURE SEULE.

JARVIS regarde si une session Claude Code ouverte par l'utilisateur (terminal, application de bureau) travaille,
l'attend ou est bloquée sur une permission, et peut l'alerter (voix, notification sur le téléphone ouvert).

Garde-fous :
- **lecture seule** : les fichiers sont ouverts en lecture binaire, jamais écrits, jamais déplacés ; rien n'est
  envoyé à ces sessions ;
- **aucun jeton ni identifiant** : seuls les fichiers d'état `<pid>.json` du dossier `sessions` sont lus (les
  fichiers voisins, dont les clés `*.key`, ne sont jamais ouverts) ; de chaque fichier, seuls quelques champs
  d'état sont gardés (les identifiants de compte ou d'organisation qu'il peut contenir sont ignorés) ;
- **format interne derrière une abstraction** : `SourceSessions` ; le format actuel de Claude Code n'est connu que
  de `interpreter()` (testé). Un format inconnu donne l'état « inconnu », jamais une erreur ;
- **désactivée par défaut**, désactivable à tout moment (réglage `veille_claude_code`) ; désactivée, elle ne lit
  rien.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from ..db import Base

journal = logging.getLogger("jarvis2.veille")

Etat = Literal["travaille", "vous_attend", "permission", "bloquee", "inconnu"]
TAILLE_MAX = 64 * 1024  # un fichier d'état fait moins d'un kilo-octet ; au-delà, ce n'est pas un fichier d'état
INTERVALLE = 3.0  # secondes entre deux lectures (veille active seulement)
CLE_REGLAGE = "veille_claude_code"
REGLAGES_DEFAUT: dict[str, bool] = {"actif": False, "voix": False, "notification": True}
LIBELLES: dict[Etat, str] = {
    "travaille": "travaille",
    "vous_attend": "vous attend",
    "permission": "bloquée sur une permission",
    "bloquee": "bloquée",
    "inconnu": "état inconnu",
}


@dataclass(frozen=True)
class EtatSession:
    ident: str  # identifiant de la session Claude Code (pas un secret : il nomme le fichier de transcription)
    nom: str
    dossier: str  # dossier de travail de la session
    etat: Etat
    detail: str | None = None  # ce que la session attend (« approve Bash: … », « input needed »…)
    depuis: datetime | None = None
    origine: str | None = None  # terminal, application de bureau…

    @property
    def projet(self) -> str:
        return Path(self.dossier).name or self.dossier

    def en_dict(self) -> dict[str, Any]:
        return {
            "id": self.ident,
            "nom": self.nom,
            "projet": self.projet,
            "dossier": self.dossier,
            "etat": self.etat,
            "libelle": LIBELLES[self.etat],
            "detail": self.detail,
            "depuis": self.depuis.isoformat() if self.depuis else None,
            "origine": self.origine,
        }


class SourceSessions(Protocol):
    """Ce que la veille sait d'une source de sessions : la liste des sessions vivantes et leur état."""

    def lire(self) -> list[EtatSession]: ...


# --- Format actuel de Claude Code (seul endroit qui le connaît) ---------------------------------------------------


def _date(ms: Any) -> datetime | None:
    if isinstance(ms, int | float) and ms > 0:
        with contextlib.suppress(OverflowError, OSError, ValueError):
            return datetime.fromtimestamp(ms / 1000, UTC)
    return None


def _court(texte: Any, taille: int = 160) -> str | None:
    if not isinstance(texte, str) or not texte.strip():
        return None
    texte = " ".join(texte.split())
    return texte if len(texte) <= taille else f"{texte[: taille - 1]}…"


def interpreter(o: Any) -> EtatSession | None:
    """Fichier d'état d'une session (`sessions/<pid>.json`) → état ; None si ce n'est pas une session.

    Champs lus : `sessionId`, `cwd`, `name`, `status` (`busy`, `idle`, `waiting`), `waitingFor`, `state`,
    `statusUpdatedAt`, `entrypoint`, `kind`. Tout le reste est ignoré.
    """
    if not isinstance(o, dict):
        return None
    ident, dossier = o.get("sessionId"), o.get("cwd")
    if not isinstance(ident, str) or not ident or not isinstance(dossier, str) or not dossier:
        return None
    if o.get("kind") not in (
        None,
        "interactive",
    ):  # sessions de fond (`claude -p`, agents) : pas celles de l'utilisateur
        return None
    statut, attend, etat_cli = o.get("status"), o.get("waitingFor"), o.get("state")
    attend_txt = attend if isinstance(attend, str) else ""
    etat: Etat
    if etat_cli in ("blocked", "failed", "waiting_for_login"):
        etat = "bloquee"
    elif statut == "waiting" or attend_txt:
        bas = attend_txt.lower()
        demande_accord = (
            bas.startswith("approve") or "permission" in bas or bas in ("sandbox request", "worker request")
        )
        etat = "permission" if demande_accord else "vous_attend"
    elif statut == "busy":
        etat = "travaille"
    elif statut == "idle":
        etat = "vous_attend"
    else:
        etat = "inconnu"
    nom = _court(o.get("name"), 80) or Path(dossier).name or "Session"
    detail = _court(attend_txt) if attend_txt else (_court(o.get("needs")) if etat == "bloquee" else None)
    origine = o.get("entrypoint") if isinstance(o.get("entrypoint"), str) else None
    return EtatSession(ident[:64], nom, dossier, etat, detail, _date(o.get("statusUpdatedAt")), origine)


def fichier_autorise(chemin: Path) -> bool:
    """Seuls les fichiers d'état `<pid>.json` sont lus : jamais une clé, un jeton ou un fichier d'identifiants."""
    nom = chemin.name
    return nom.endswith(".json") and nom[: -len(".json")].isdigit()


def processus_vivant(pid: int) -> bool:
    """Le processus existe encore (sans jamais lui envoyer de signal sous Windows)."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        noyau = ctypes.windll.kernel32
        poignee = noyau.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not poignee:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(noyau.GetExitCodeProcess(poignee, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            noyau.CloseHandle(poignee)
    try:
        os.kill(pid, 0)  # POSIX : signal 0 = simple vérification
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def dossier_par_defaut() -> Path:
    racine = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(racine) if racine else Path.home() / ".claude") / "sessions"


@dataclass
class SourceFichiersEtat:
    """Sessions Claude Code d'après leurs fichiers d'état (format actuel de la CLI)."""

    dossier: Path = field(default_factory=dossier_par_defaut)
    vivant: Callable[[int], bool] = processus_vivant

    def disponible(self) -> bool:
        return self.dossier.is_dir()

    def lire(self) -> list[EtatSession]:
        if not self.dossier.is_dir():
            return []
        sessions: dict[str, EtatSession] = {}
        for chemin in sorted(self.dossier.iterdir()):
            if not fichier_autorise(chemin) or not chemin.is_file():
                continue
            if not self.vivant(int(chemin.name[: -len(".json")])):
                continue  # fichier laissé par une session fermée
            try:
                with chemin.open("rb") as f:  # lecture seule
                    brut = f.read(TAILLE_MAX + 1)
                if len(brut) > TAILLE_MAX:
                    continue
                session = interpreter(json.loads(brut))
            except (OSError, ValueError):
                continue  # fichier en cours d'écriture : relu au tour suivant
            if session is not None:
                avant = sessions.get(session.ident)
                if avant is None or (session.depuis or datetime.min.replace(tzinfo=UTC)) > (
                    avant.depuis or datetime.min.replace(tzinfo=UTC)
                ):
                    sessions[session.ident] = session
        return list(sessions.values())


# --- Veille : réglage, transitions, alertes --------------------------------------------------------------------


@dataclass(frozen=True)
class Alerte:
    id: int
    session: EtatSession
    texte: str
    horodatage: datetime

    def en_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "texte": self.texte,
            "etat": self.session.etat,
            "session": self.session.ident,
            "horodatage": self.horodatage.isoformat(),
        }


def texte_alerte(avant: Etat | None, s: EtatSession) -> str | None:
    """Alerte à donner quand une session change d'état (None : rien à dire)."""
    if s.etat == avant:
        return None
    if s.etat == "permission":
        return f"Claude Code attend votre permission dans « {s.nom} »."
    if s.etat == "bloquee":
        return f"La session Claude Code « {s.nom} » est bloquée."
    if s.etat == "vous_attend" and avant == "travaille":
        return f"Claude Code a fini et vous attend dans « {s.nom} »."
    return None


class VeilleClaudeCode:
    def __init__(
        self,
        base: Base,
        source: SourceSessions,
        exclure: Callable[[str], bool] = lambda _: False,
        ignorer_dossiers: Sequence[Path] = (),
    ) -> None:
        self.base = base
        self.source = source
        self.exclure = exclure  # sujets exclus par l'utilisateur : ces sessions ne sont ni montrées ni annoncées
        self.ignorer_dossiers = [p.resolve() for p in ignorer_dossiers]  # worktrees des ateliers de JARVIS
        self.reglages: dict[str, bool] = dict(REGLAGES_DEFAUT)
        self.sessions: list[EtatSession] = []
        self.alertes: deque[Alerte] = deque(maxlen=50)
        self._dernier_id = 0
        self._etats: dict[str, Etat] = {}
        self.maj_le: datetime | None = None

    @property
    def actif(self) -> bool:
        return self.reglages["actif"]

    async def charger(self) -> None:
        valeur = await self.base.fetchval("SELECT valeur FROM etat_systeme WHERE cle = $1", CLE_REGLAGE)
        if isinstance(valeur, str):
            valeur = json.loads(valeur)
        if isinstance(valeur, dict):
            self.reglages = {k: bool(valeur.get(k, d)) for k, d in REGLAGES_DEFAUT.items()}

    async def regler(self, **changements: bool | None) -> dict[str, bool]:
        for cle, val in changements.items():
            if cle in REGLAGES_DEFAUT and val is not None:
                self.reglages[cle] = bool(val)
        await self.base.execute(
            "UPDATE etat_systeme SET valeur = $2::text::jsonb, maj_le = now() WHERE cle = $1",
            CLE_REGLAGE,
            json.dumps(self.reglages),
        )
        if not self.actif:  # désactivée : plus rien n'est gardé
            self.sessions, self._etats, self.maj_le = [], {}, None
            self.alertes.clear()
        return dict(self.reglages)

    def _gardee(self, s: EtatSession) -> bool:
        if self.exclure(s.dossier) or self.exclure(s.nom):
            return False
        with contextlib.suppress(OSError, ValueError):
            dossier = Path(s.dossier).resolve()
            if any(dossier == p or p in dossier.parents for p in self.ignorer_dossiers):
                return False
        return True

    def appliquer(self, lues: Sequence[EtatSession], maintenant: datetime | None = None) -> list[Alerte]:
        """Nouvel état des sessions → alertes des changements (la première lecture n'annonce que les blocages)."""
        maintenant = maintenant or datetime.now(UTC)
        gardees = [s for s in lues if self._gardee(s)]
        nouvelles: list[Alerte] = []
        for s in gardees:
            texte = texte_alerte(self._etats.get(s.ident), s)
            if texte:
                self._dernier_id += 1
                alerte = Alerte(self._dernier_id, s, texte, maintenant)
                self.alertes.append(alerte)
                nouvelles.append(alerte)
        self._etats = {s.ident: s.etat for s in gardees}
        self.sessions = sorted(gardees, key=lambda s: s.depuis or maintenant, reverse=True)
        self.maj_le = maintenant
        return nouvelles

    async def sonder(self) -> list[Alerte]:
        if not self.actif:
            return []
        lues = await asyncio.to_thread(self.source.lire)
        return self.appliquer(lues)

    @property
    def dernier_id(self) -> int:
        return self._dernier_id

    def alertes_apres(self, apres: int) -> list[dict[str, Any]]:
        return [a.en_dict() for a in self.alertes if a.id > apres]

    def resume(self) -> str:
        """Ligne de contexte pour JARVIS : états seulement (jamais le contenu de ces sessions)."""
        if not self.actif or not self.sessions:
            return ""
        parties = [f"« {s.nom} » ({s.projet}) : {LIBELLES[s.etat]}" for s in self.sessions[:8]]
        return "Sessions Claude Code de l'utilisateur (veille en lecture seule) : " + " ; ".join(parties) + "."

    async def boucle(self) -> None:
        with contextlib.suppress(Exception):
            await self.charger()
        while True:
            try:
                await self.sonder()
            except asyncio.CancelledError:
                raise
            except Exception:  # jamais bloquant : une lecture ratée est refaite au tour suivant
                journal.exception("Veille des sessions Claude Code")
            await asyncio.sleep(INTERVALLE)
