"""Ateliers Claude Code : chaque atelier travaille dans son propre worktree git, sur sa branche `jarvis/atelier-…`.

Claude Code (binaire officiel, abonnement de l'utilisateur) tourne dans le worktree ; CHAQUE outil qu'il veut
utiliser passe par l'outil d'autorisation de JARVIS (`--permission-prompt-tool`, serveur MCP `jarvis2 atelier-mcp`) :
écriture hors du worktree refusée, commandes et accès hors du worktree soumis à l'utilisateur en direct.
Pilotage : pause réelle (processus suspendu, autorisations retenues), reprise, arrêt (processus tué), reprise de
session Claude Code ; relance automatique après un plantage technique (2 fois au plus), relance à la main après un
échec ; modèle choisi par atelier ; clôture avec notes (travail commité sur la branche, worktree retiré).
Coordination : les fichiers modifiés par chaque atelier sont notés ; deux ateliers ouverts du même projet qui
touchent le même fichier sont signalés (jamais bloqués). La fusion dans le projet est une action 🟡 : JARVIS commite
le worktree puis fusionne la branche (`--no-ff`) dans un projet propre, sinon il refuse.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import secrets
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ..db import Base, Executant
from ..moteurs.claude_code import environnement_propre
from ..moteurs.sousprocessus import trouver
from ..securite.filtre import masquer_secrets
from ..securite.urgence import ArretUrgence
from .autorisation import decider
from .processus import suspendre

journal = logging.getLogger("jarvis2.ateliers")

IDENT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
DELAI_ATTENTE = 600.0  # une demande d'autorisation sans réponse est refusée au bout de 10 minutes
COLONNES = "id, projet, nom, branche, chemin, statut, session, cree_par, cree_le, maj_le, modele, notes, clos_le"
RELANCES_MAX = 2  # relances automatiques après un plantage technique de Claude Code
DELAI_RELANCE = 2.0  # secondes avant la 1re relance automatique (puis 4 s)
MODELE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-\[\]]{0,79}$")
# Choix proposés (un identifiant complet de modèle Claude est aussi accepté)
MODELES: tuple[tuple[str, str], ...] = (
    ("sonnet", "Sonnet — rapide, pour la plupart des tâches"),
    ("opus", "Opus — plus puissant, pour les tâches complexes"),
    ("haiku", "Haiku — très rapide, pour les petites tâches"),
)
OUTILS_ECRITURE = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
CONSIGNE_RELANCE = (
    "Claude Code s'est arrêté sur une erreur technique. Reprends le travail là où tu t'étais arrêté, "
    "sans refaire ce qui est déjà fait."
)


class ErreurAtelier(RuntimeError):
    pass


def valider_modele(modele: str | None) -> str | None:
    """Modèle de Claude Code choisi pour un atelier ; vide = le réglage de Claude Code."""
    modele = (modele or "").strip()
    if not modele:
        return None
    if not MODELE.match(modele):
        raise ErreurAtelier(f"Modèle invalide : « {modele[:80]} »")
    return modele


def chemin_relatif(racine: Path, fichier: str) -> str | None:
    """Chemin d'un fichier relatif au worktree (None s'il est dehors)."""
    try:
        cible = Path(fichier)
        cible = (cible if cible.is_absolute() else racine / cible).resolve()
        return cible.relative_to(racine.resolve()).as_posix()
    except (OSError, ValueError):
        return None


@dataclass(frozen=True)
class Projet:
    id: str
    nom: str
    chemin: Path

    @classmethod
    def depuis_config(cls, bloc: dict[str, Any]) -> Projet:
        ident = str(bloc.get("id", ""))
        if not IDENT.match(ident) or not bloc.get("chemin"):
            raise ValueError(f"ateliers.projets : id (minuscules) et chemin attendus ({ident!r})")
        return cls(ident, str(bloc.get("nom") or ident), Path(str(bloc["chemin"])))


@dataclass
class Attente:
    id: str
    atelier: UUID
    outil: str
    entree: dict[str, Any]
    raison: str
    futur: asyncio.Future[bool] = field(repr=False)

    def en_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "atelier": str(self.atelier),
            "outil": self.outil,
            "entree": self.entree,
            "raison": self.raison,
        }


async def git(cwd: Path, *args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    sortie, _ = await proc.communicate()
    return proc.returncode or 0, sortie.decode("utf-8", "replace").strip()


class GestionnaireAteliers:
    def __init__(
        self,
        base: Base,
        projets: Sequence[Projet],
        dossier: Path,
        url_core: str,
        urgence: ArretUrgence,
        commande_claude: Sequence[str] | None = None,
        commande_mcp: Sequence[str] | None = None,
    ) -> None:
        self.base = base
        self.projets = {p.id: p for p in projets}
        self.dossier = dossier
        self.url_core = url_core.rstrip("/")
        self.urgence = urgence
        self.commande_claude = list(commande_claude) if commande_claude else (trouver(None, "claude") or ["claude"])
        self.commande_mcp = list(commande_mcp) if commande_mcp else [sys.executable, "-m", "jarvis2", "atelier-mcp"]
        self.processus: dict[UUID, asyncio.subprocess.Process] = {}
        self.taches: dict[UUID, asyncio.Task[None]] = {}
        self.jetons: dict[str, UUID] = {}
        self.attentes: dict[str, Attente] = {}
        # Pause : événement baissé = atelier en pause (processus suspendu, autorisations retenues)
        self.reprises: dict[UUID, asyncio.Event] = {}

    # --- Lecture ---------------------------------------------------------------------------------------------

    async def obtenir(self, ident: UUID) -> dict[str, Any] | None:
        ligne = await self.base.fetchrow(f"SELECT {COLONNES} FROM ateliers WHERE id = $1", ident)  # noqa: S608
        return dict(ligne) if ligne else None

    def en_pause(self, ident: UUID) -> bool:
        ev = self.reprises.get(ident)
        return ev is not None and not ev.is_set()

    async def lister(self) -> list[dict[str, Any]]:
        lignes = await self.base.fetch(f"SELECT {COLONNES} FROM ateliers ORDER BY cree_le DESC LIMIT 100")  # noqa: S608
        return [dict(r) for r in lignes]

    async def evenements(self, ident: UUID, apres: int = 0, limite: int = 300) -> list[dict[str, Any]]:
        lignes = await self.base.fetch(
            "SELECT id, horodatage, type, contenu FROM evenements_atelier WHERE atelier_id = $1 AND id > $2"
            " ORDER BY id LIMIT $3",
            ident,
            apres,
            limite,
        )
        return [dict(r) for r in lignes]

    async def _noter(self, ident: UUID, type_: str, contenu: dict[str, Any]) -> None:
        await self.base.execute(
            "INSERT INTO evenements_atelier (atelier_id, type, contenu) VALUES ($1, $2, $3)", ident, type_, contenu
        )

    async def _statut(self, ident: UUID, statut: str, session: str | None = None) -> None:
        await self.base.execute(
            "UPDATE ateliers SET statut = $2, session = coalesce($3, session), maj_le = now() WHERE id = $1",
            ident,
            statut,
            session,
        )

    # --- Cycle de vie ----------------------------------------------------------------------------------------

    async def creer(self, projet_id: str, nom: str, acteur: str, modele: str | None = None) -> dict[str, Any]:
        modele = valider_modele(modele)
        projet = self.projets.get(projet_id)
        if projet is None:
            raise ErreurAtelier(f"Projet inconnu : « {projet_id} » (configuration locale, [[ateliers.projets]])")
        code, _ = await git(projet.chemin, "rev-parse", "--is-inside-work-tree")
        if code != 0:
            raise ErreurAtelier(f"{projet.chemin} n'est pas un dépôt git")
        ident = uuid4()
        branche = f"jarvis/atelier-{ident.hex[:8]}"
        chemin = self.dossier / projet.id / ident.hex[:8]
        chemin.parent.mkdir(parents=True, exist_ok=True)
        code, sortie = await git(projet.chemin, "worktree", "add", "-b", branche, str(chemin), "HEAD")
        if code != 0:
            raise ErreurAtelier(f"Worktree impossible : {sortie}")
        await self.base.execute(
            "INSERT INTO ateliers (id, projet, nom, branche, chemin, cree_par, modele)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7)",
            ident,
            projet.id,
            nom.strip()[:120] or "Atelier",
            branche,
            str(chemin),
            acteur,
            modele,
        )
        await self._noter(ident, "cree", {"branche": branche, "chemin": str(chemin), "modele": modele})
        atelier = await self.obtenir(ident)
        assert atelier is not None
        return atelier

    async def choisir_modele(self, ident: UUID, modele: str | None) -> dict[str, Any]:
        """Change le modèle d'un atelier (pris en compte à la consigne suivante)."""
        modele = valider_modele(modele)
        atelier = await self._ouvert(ident)
        if ident in self.processus or ident in self.taches:
            raise ErreurAtelier("L'atelier travaille : le modèle se change entre deux consignes")
        await self.base.execute("UPDATE ateliers SET modele = $2, maj_le = now() WHERE id = $1", ident, modele)
        await self._noter(ident, "modele", {"modele": modele, "avant": atelier["modele"]})
        nouveau = await self.obtenir(ident)
        assert nouveau is not None
        return nouveau

    async def _ouvert(self, ident: UUID) -> dict[str, Any]:
        atelier = await self.obtenir(ident)
        if atelier is None:
            raise ErreurAtelier("Atelier introuvable")
        if atelier["clos_le"] is not None:
            raise ErreurAtelier("Atelier clôturé")
        return atelier

    def arguments(self, jeton: str, session: str | None, modele: str | None = None) -> list[str]:
        config_mcp = {
            "mcpServers": {
                "jarvis": {
                    "command": self.commande_mcp[0],
                    "args": self.commande_mcp[1:],
                    "env": {
                        "JARVIS2_ATELIER_URL": f"{self.url_core}/v1/ateliers-autorisation",
                        "JARVIS2_ATELIER_JETON": jeton,
                    },
                }
            }
        }
        args = [
            *self.commande_claude,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-prompt-tool",
            "mcp__jarvis__autoriser",
            "--mcp-config",
            json.dumps(config_mcp),
            "--strict-mcp-config",
        ]
        if modele:
            args += ["--model", modele]
        return [*args, "--resume", session] if session else args

    async def lancer(self, ident: UUID, consigne: str, reprendre: bool = False) -> None:
        atelier = await self._ouvert(ident)
        if atelier["statut"] in ("fusionne", "abandonne"):
            raise ErreurAtelier("Atelier terminé")
        if ident in self.processus or ident in self.taches:
            raise ErreurAtelier("Cet atelier travaille déjà")
        if self.urgence.actif:
            raise ErreurAtelier("Arrêt d'urgence actif")
        session = atelier["session"] if reprendre else None
        await self._statut(ident, "en_cours")
        await self._noter(ident, "consigne", {"texte": consigne, "reprise": bool(session)})
        tache = asyncio.get_running_loop().create_task(
            self._executer(ident, Path(atelier["chemin"]), consigne, session, atelier["modele"])
        )
        self.taches[ident] = tache
        tache.add_done_callback(lambda _: self.taches.pop(ident, None))

    async def relancer(self, ident: UUID) -> None:
        """Après un échec : la dernière consigne repart, dans la même session Claude Code si elle existe."""
        atelier = await self._ouvert(ident)
        if atelier["statut"] not in ("erreur", "arrete"):
            raise ErreurAtelier("Seul un atelier en échec ou arrêté se relance")
        contenu = await self.base.fetchval(
            "SELECT contenu FROM evenements_atelier WHERE atelier_id = $1 AND type = 'consigne'"
            " ORDER BY id DESC LIMIT 1",
            ident,
        )
        if isinstance(contenu, str):
            contenu = json.loads(contenu)
        texte = str((contenu or {}).get("texte") or "").strip()
        if not texte:
            raise ErreurAtelier("Aucune consigne à relancer")
        await self._noter(ident, "relance", {"automatique": False})
        await self.lancer(ident, texte, reprendre=bool(atelier["session"]))

    def _journal_erreurs(self, ident: UUID) -> Path:
        dossier = self.dossier / "journaux"
        dossier.mkdir(parents=True, exist_ok=True)
        return dossier / f"{ident.hex[:8]}.log"

    async def _executer(
        self, ident: UUID, chemin: Path, consigne: str, session: str | None, modele: str | None = None
    ) -> None:
        statut_final = "pret"
        try:
            for essai in range(RELANCES_MAX + 1):
                issue = await self._une_execution(ident, chemin, consigne, session, modele)
                if issue != "plantage":
                    statut_final = issue
                    break
                if essai == RELANCES_MAX:
                    statut_final = "erreur"
                    await self._noter(
                        ident, "erreur", {"message": f"Claude Code a planté {essai + 1} fois de suite : j'arrête"}
                    )
                    break
                await self._noter(ident, "relance", {"automatique": True, "essai": essai + 1})
                actuel = await self.obtenir(ident)
                session = (actuel or {}).get("session") or session
                if session:
                    consigne = CONSIGNE_RELANCE
                await asyncio.sleep(DELAI_RELANCE * (essai + 1))
        except asyncio.CancelledError:
            statut_final = "arrete"
            raise
        finally:
            self.reprises.pop(ident, None)
            for a in [a for a in self.attentes.values() if a.atelier == ident]:
                if not a.futur.done():
                    a.futur.set_result(False)
            with contextlib.suppress(Exception):
                await asyncio.shield(self.noter_fichiers_modifies(ident))
            actuel = await self.obtenir(ident)
            if actuel is not None and actuel["statut"] == "en_cours":
                await asyncio.shield(self._statut(ident, statut_final))

    async def _une_execution(
        self, ident: UUID, chemin: Path, consigne: str, session: str | None, modele: str | None
    ) -> str:
        """Une exécution de Claude Code → « pret », « erreur » ou « plantage » (à relancer)."""
        jeton = secrets.token_urlsafe(32)
        self.jetons[jeton] = ident
        reprise = asyncio.Event()
        reprise.set()
        self.reprises[ident] = reprise
        fin_vue: dict[str, Any] | None = None
        journal_erreurs = self._journal_erreurs(ident)
        groupe: dict[str, Any] = {} if sys.platform == "win32" else {"start_new_session": True}
        try:
            with self.urgence.suivre(), journal_erreurs.open("ab") as sortie_erreurs:
                debut_erreurs = sortie_erreurs.tell()
                proc = await asyncio.create_subprocess_exec(
                    *self.arguments(jeton, session, modele),
                    cwd=str(chemin),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=sortie_erreurs,
                    env=environnement_propre(dict(os.environ)),
                    limit=16 * 1024 * 1024,
                    **groupe,
                )
                self.processus[ident] = proc
                assert proc.stdin is not None and proc.stdout is not None
                proc.stdin.write(consigne.encode())
                await proc.stdin.drain()
                proc.stdin.close()
                async for brut in proc.stdout:
                    try:
                        ev = json.loads(brut)
                    except json.JSONDecodeError:
                        continue
                    if not await self._evenement(ident, ev):
                        proc.kill()
                        return "erreur"
                    if ev.get("type") == "result":
                        fin_vue = ev
                code = await proc.wait()
            if fin_vue is not None:
                return "erreur" if fin_vue.get("is_error") else "pret"
            if code == 0:
                return "pret"
            fin_journal = await asyncio.to_thread(self._lire_fin, journal_erreurs, debut_erreurs)
            await self._noter(
                ident, "erreur", {"message": f"Claude Code s'est arrêté (code {code})", "journal": fin_journal}
            )
            return "plantage"
        except OSError as exc:
            await self._noter(ident, "erreur", {"message": f"Claude Code introuvable : {exc}"})
            return "erreur"
        finally:
            self.jetons.pop(jeton, None)
            proc_fini = self.processus.pop(ident, None)
            if proc_fini is not None and proc_fini.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc_fini.kill()

    @staticmethod
    def _lire_fin(chemin: Path, debut: int) -> str:
        """Fin de la sortie d'erreur de cette exécution (secrets masqués), pour comprendre un plantage."""
        try:
            with chemin.open("rb") as f:
                f.seek(max(debut, chemin.stat().st_size - 2000))
                return masquer_secrets(f.read().decode("utf-8", "replace").strip())[-1000:]
        except OSError:
            return ""

    async def _evenement(self, ident: UUID, ev: dict[str, Any]) -> bool:
        """Garde l'événement utile ; False = arrêter (réponse qui ne vient pas de l'abonnement)."""
        type_ = ev.get("type")
        if type_ == "system" and ev.get("subtype") == "init":
            source = str(ev.get("apiKeySource", ""))
            if source != "none":
                await self._noter(ident, "erreur", {"message": f"Source d'authentification refusée : {source}"})
                return False
            await self._statut(ident, "en_cours", str(ev.get("session_id") or "") or None)
            await self._noter(ident, "session", {"session": ev.get("session_id"), "modele": ev.get("model")})
        elif type_ == "assistant":
            for bloc in (ev.get("message") or {}).get("content") or []:
                if bloc.get("type") == "text" and bloc.get("text"):
                    await self._noter(ident, "texte", {"texte": str(bloc["text"])[:20_000]})
                elif bloc.get("type") == "tool_use":
                    entree = json.dumps(bloc.get("input") or {}, ensure_ascii=False)[:2000]
                    await self._noter(ident, "outil", {"nom": bloc.get("name"), "entree": entree})
        elif type_ == "result":
            await self._noter(
                ident, "fin", {"erreur": bool(ev.get("is_error")), "texte": str(ev.get("result") or "")[:20_000]}
            )
        return True

    async def arreter(self, ident: UUID) -> bool:
        tache = self.taches.get(ident)
        if tache is None:
            return False
        proc = self.processus.get(ident)
        if proc is not None and self.en_pause(ident):
            suspendre(proc.pid, False)  # un processus suspendu est réveillé pour être arrêté proprement
        tache.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await tache
        await self._statut(ident, "arrete")
        await self._noter(ident, "arret", {})
        return True

    async def mettre_en_pause(self, ident: UUID) -> bool:
        """Pause réelle : Claude Code est suspendu et aucune autorisation ne lui est rendue avant la reprise."""
        proc, reprise = self.processus.get(ident), self.reprises.get(ident)
        if proc is None or reprise is None or not reprise.is_set():
            return False
        reprise.clear()
        suspendu = suspendre(proc.pid, True)
        await self._noter(ident, "pause", {"suspendu": suspendu})
        return True

    async def reprendre(self, ident: UUID) -> bool:
        proc, reprise = self.processus.get(ident), self.reprises.get(ident)
        if reprise is None or reprise.is_set():
            return False
        if proc is not None:
            suspendre(proc.pid, False)
        reprise.set()
        await self._noter(ident, "reprise", {})
        return True

    # --- Autorisations (appelées par l'outil d'autorisation de Claude Code) ----------------------------------

    async def autoriser(self, jeton: str, outil: str, entree: dict[str, Any]) -> dict[str, Any]:
        ident = self.jetons.get(jeton)
        if ident is None:
            return {"behavior": "deny", "message": "Session d'atelier inconnue"}
        atelier = await self.obtenir(ident)
        if atelier is None or self.urgence.actif:
            return {"behavior": "deny", "message": "Atelier arrêté"}
        reprise = self.reprises.get(ident)
        if reprise is not None and not reprise.is_set():
            await reprise.wait()  # en pause : la demande attend la reprise (l'arrêt la refuse)
            if ident not in self.processus:
                return {"behavior": "deny", "message": "Atelier arrêté"}
        decision = decider(Path(atelier["chemin"]), outil, entree)
        if decision.verdict == "demander":
            attente = Attente(
                secrets.token_hex(8), ident, outil, entree, decision.raison, asyncio.get_running_loop().create_future()
            )
            self.attentes[attente.id] = attente
            await self._noter(ident, "attente", attente.en_dict())
            try:
                accorde = await asyncio.wait_for(attente.futur, timeout=DELAI_ATTENTE)
            except TimeoutError:
                accorde = False
            finally:
                self.attentes.pop(attente.id, None)
            reponse = (
                {"behavior": "allow", "updatedInput": entree}
                if accorde
                else {"behavior": "deny", "message": "Refusé par l'utilisateur (ou sans réponse)"}
            )
        else:
            reponse = decision.reponse(entree)
        await self._noter(
            ident,
            "autorisation",
            {"outil": outil, "verdict": reponse["behavior"], "raison": reponse.get("message", decision.raison)},
        )
        if reponse["behavior"] == "allow" and outil in OUTILS_ECRITURE:
            fichier = entree.get("file_path") or entree.get("notebook_path")
            relatif = chemin_relatif(Path(atelier["chemin"]), str(fichier)) if fichier else None
            if relatif:
                await self.declarer_fichiers(ident, [relatif])
        return reponse

    def en_attente(self, ident: UUID | None = None) -> list[dict[str, Any]]:
        return [a.en_dict() for a in self.attentes.values() if ident is None or a.atelier == ident]

    def repondre(self, attente_id: str, accorde: bool) -> bool:
        attente = self.attentes.get(attente_id)
        if attente is None or attente.futur.done():
            return False
        attente.futur.set_result(accorde)
        return True

    # --- Fusion et abandon -----------------------------------------------------------------------------------

    async def fusionner(self, conn: Executant, ident: UUID) -> dict[str, Any]:
        """Commite le worktree puis fusionne sa branche dans le projet (projet propre exigé, conflit = annulé)."""
        atelier = await self.obtenir(ident)
        if atelier is None:
            raise ErreurAtelier("Atelier introuvable")
        if ident in self.processus:
            raise ErreurAtelier("L'atelier travaille encore : arrêtez-le ou attendez la fin")
        if atelier["statut"] in ("fusionne", "abandonne"):
            raise ErreurAtelier("Atelier déjà terminé")
        projet = self.projets.get(atelier["projet"])
        if projet is None:
            raise ErreurAtelier("Projet inconnu")
        chemin = Path(atelier["chemin"])
        await git(chemin, "add", "-A")
        code, sortie = await git(chemin, "diff", "--cached", "--quiet")
        if code != 0:
            code, sortie = await git(
                chemin,
                "-c",
                "user.name=JARVIS",
                "-c",
                "user.email=jarvis@localhost",
                "commit",
                "-m",
                f"Atelier JARVIS : {atelier['nom']}",
            )
            if code != 0:
                raise ErreurAtelier(f"Commit impossible : {sortie}")
        code, etat = await git(projet.chemin, "status", "--porcelain")
        if code != 0 or etat:
            raise ErreurAtelier("Le projet a des modifications non commitées : fusion refusée")
        code, sortie = await git(
            projet.chemin,
            "-c",
            "user.name=JARVIS",
            "-c",
            "user.email=jarvis@localhost",
            "merge",
            "--no-ff",
            "--no-edit",
            atelier["branche"],
        )
        if code != 0:
            await git(projet.chemin, "merge", "--abort")
            raise ErreurAtelier(f"Conflit : fusion annulée, le projet est inchangé ({sortie[:300]})")
        await self._statut(ident, "fusionne")
        await self._noter(ident, "fusion", {"branche": atelier["branche"]})
        return {"atelier": str(ident), "branche": atelier["branche"], "projet": projet.id}

    async def abandonner(self, ident: UUID) -> None:
        """Retire le worktree ; la branche reste (rien de commité n'est perdu)."""
        atelier = await self.obtenir(ident)
        if atelier is None:
            raise ErreurAtelier("Atelier introuvable")
        await self.arreter(ident)
        projet = self.projets.get(atelier["projet"])
        if projet is not None:
            await git(projet.chemin, "worktree", "remove", "--force", atelier["chemin"])
        await self._statut(ident, "abandonne")
        await self._noter(ident, "abandon", {})

    # --- Coordination : fichiers touchés, conflits entre ateliers ------------------------------------------------

    async def declarer_fichiers(self, ident: UUID, chemins: Sequence[str]) -> list[dict[str, Any]]:
        """Note les fichiers modifiés par un atelier ; renvoie les nouveaux conflits (signalés des deux côtés)."""
        atelier = await self.obtenir(ident)
        if atelier is None:
            return []
        nouveaux: list[dict[str, Any]] = []
        for chemin in dict.fromkeys(c for c in chemins if c and len(c) <= 1000):
            ajoute = await self.base.fetchval(
                "INSERT INTO fichiers_atelier (atelier_id, chemin) VALUES ($1, $2) ON CONFLICT DO NOTHING"
                " RETURNING chemin",
                ident,
                chemin,
            )
            if ajoute is None:
                continue
            autres = await self.base.fetch(
                "SELECT a.id, a.nom FROM fichiers_atelier f JOIN ateliers a ON a.id = f.atelier_id"
                " WHERE f.chemin = $1 AND a.projet = $2 AND a.id <> $3 AND a.clos_le IS NULL"
                " AND a.statut IN ('pret', 'en_cours', 'arrete', 'erreur')",
                chemin,
                atelier["projet"],
                ident,
            )
            for autre in autres:
                await self._noter(
                    ident, "conflit", {"fichier": chemin, "atelier": str(autre["id"]), "nom": autre["nom"]}
                )
                await self._noter(
                    autre["id"], "conflit", {"fichier": chemin, "atelier": str(ident), "nom": atelier["nom"]}
                )
                nouveaux.append({"fichier": chemin, "ateliers": [str(ident), str(autre["id"])]})
        return nouveaux

    async def noter_fichiers_modifies(self, ident: UUID) -> list[dict[str, Any]]:
        """Après une exécution : fichiers modifiés dans le worktree, même par une commande (git le sait)."""
        atelier = await self.obtenir(ident)
        if atelier is None or atelier["statut"] in ("fusionne", "abandonne"):
            return []
        chemin = Path(atelier["chemin"])
        if not await asyncio.to_thread(chemin.is_dir):
            return []
        fichiers: list[str] = []
        for args in (("diff", "--name-only", "--no-renames", "HEAD"), ("ls-files", "--others", "--exclude-standard")):
            code, sortie = await git(chemin, "-c", "core.quotepath=false", *args)
            if code == 0:
                fichiers += [ligne.strip() for ligne in sortie.splitlines() if ligne.strip()]
        projet = self.projets.get(atelier["projet"])
        if projet is not None:
            code, tete = await git(projet.chemin, "rev-parse", "HEAD")
            if code == 0:
                code, commun = await git(chemin, "merge-base", "HEAD", tete)
                if code == 0:
                    code, commites = await git(chemin, "diff", "--name-only", "--no-renames", commun, "HEAD")
                    if code == 0:
                        fichiers += commites.splitlines()
        return await self.declarer_fichiers(ident, fichiers)

    async def conflits(self) -> dict[str, list[dict[str, Any]]]:
        """Par atelier ouvert : les fichiers qu'il partage avec un autre atelier ouvert du même projet."""
        lignes = await self.base.fetch(
            "SELECT a.id, a.nom, a.projet, f.chemin FROM fichiers_atelier f JOIN ateliers a ON a.id = f.atelier_id"
            " WHERE a.clos_le IS NULL AND a.statut IN ('pret', 'en_cours', 'arrete', 'erreur')"
        )
        par_fichier: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for r in lignes:
            par_fichier.setdefault((r["projet"], r["chemin"]), []).append(dict(r))
        resultat: dict[str, list[dict[str, Any]]] = {}
        for (_, fichier), ateliers in sorted(par_fichier.items()):
            if len(ateliers) < 2:
                continue
            for a in ateliers:
                autres = [{"id": str(b["id"]), "nom": b["nom"]} for b in ateliers if b["id"] != a["id"]]
                resultat.setdefault(str(a["id"]), []).append({"fichier": fichier, "ateliers": autres})
        return resultat

    # --- Clôture ----------------------------------------------------------------------------------------------

    async def cloturer(self, ident: UUID, notes: str) -> dict[str, Any]:
        """Archive l'atelier avec des notes : le travail non commité l'est sur sa branche, puis le worktree est
        retiré (la branche reste : rien n'est perdu). Un atelier clôturé sort des résumés et des conflits."""
        atelier = await self._ouvert(ident)
        if ident in self.processus or ident in self.taches:
            raise ErreurAtelier("L'atelier travaille encore : arrêtez-le ou attendez la fin")
        chemin = Path(atelier["chemin"])
        commite = False
        if atelier["statut"] != "abandonne" and await asyncio.to_thread(chemin.is_dir):
            await git(chemin, "add", "-A")
            code, _ = await git(chemin, "diff", "--cached", "--quiet")
            if code != 0:
                code, sortie = await git(
                    chemin,
                    "-c",
                    "user.name=JARVIS",
                    "-c",
                    "user.email=jarvis@localhost",
                    "commit",
                    "-m",
                    f"Atelier JARVIS (clôturé) : {atelier['nom']}",
                )
                if code != 0:
                    raise ErreurAtelier(f"Commit impossible : {sortie}")
                commite = True
            projet = self.projets.get(atelier["projet"])
            if projet is not None:
                await git(projet.chemin, "worktree", "remove", "--force", str(chemin))
        notes = notes.strip()[:10_000]
        await self.base.execute(
            "UPDATE ateliers SET notes = $2, clos_le = now(), maj_le = now() WHERE id = $1", ident, notes or None
        )
        await self._noter(ident, "cloture", {"notes": notes, "commit": commite})
        clos = await self.obtenir(ident)
        assert clos is not None
        return clos

    # --- Résumé pour le contexte de JARVIS --------------------------------------------------------------------

    async def resume(self) -> str:
        """Ce qui tourne dans les ateliers, en quelques lignes (jamais le contenu des fils)."""
        lignes = await self.base.fetch(
            f"SELECT {COLONNES} FROM ateliers WHERE clos_le IS NULL"  # noqa: S608
            " AND statut IN ('pret', 'en_cours', 'arrete', 'erreur') ORDER BY maj_le DESC LIMIT 30"
        )
        conflits = await self.conflits()
        attentes = {a.atelier for a in self.attentes.values()}
        parties: list[str] = []
        for r in lignes:
            ident = r["id"]
            if ident in self.processus or ident in self.taches:
                etat = "en pause" if self.en_pause(ident) else "au travail"
            elif r["statut"] == "erreur":
                etat = "en échec (relançable)"
            elif r["statut"] == "arrete":
                etat = "arrêté"
            elif str(ident) in conflits:
                etat = "prêt"
            else:
                continue  # prêt et sans souci : rien ne tourne
            if ident in attentes:
                etat += ", attend l'accord de l'utilisateur"
            if str(ident) in conflits:
                fichiers = ", ".join(c["fichier"] for c in conflits[str(ident)][:3])
                etat += f", conflit de fichiers avec un autre atelier ({fichiers})"
            modele = f", modèle {r['modele']}" if r["modele"] else ""
            parties.append(f"- « {r['nom']} » (projet {r['projet']}{modele}) : {etat}")
        if not parties:
            return ""
        return "Ateliers Claude Code de JARVIS :\n" + "\n".join(parties[:10])

    async def fermer(self) -> None:
        for ident in list(self.taches):
            await self.arreter(ident)
