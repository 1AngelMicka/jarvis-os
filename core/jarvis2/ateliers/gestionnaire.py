"""Ateliers Claude Code : chaque atelier travaille dans son propre worktree git, sur sa branche `jarvis/atelier-…`.

Claude Code (binaire officiel, abonnement de l'utilisateur) tourne dans le worktree ; CHAQUE outil qu'il veut
utiliser passe par l'outil d'autorisation de JARVIS (`--permission-prompt-tool`, serveur MCP `jarvis2 atelier-mcp`) :
écriture hors du worktree refusée, commandes et accès hors du worktree soumis à l'utilisateur en direct.
Pilotage : arrêt (processus tué), reprise (session Claude Code reprise). La fusion dans le projet est une action 🟡 :
JARVIS commite le worktree puis fusionne la branche (`--no-ff`) dans un projet propre, sinon il refuse.
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
from ..securite.urgence import ArretUrgence
from .autorisation import decider

journal = logging.getLogger("jarvis2.ateliers")

IDENT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
DELAI_ATTENTE = 600.0  # une demande d'autorisation sans réponse est refusée au bout de 10 minutes
COLONNES = "id, projet, nom, branche, chemin, statut, session, cree_par, cree_le, maj_le"


class ErreurAtelier(RuntimeError):
    pass


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

    # --- Lecture ---------------------------------------------------------------------------------------------

    async def obtenir(self, ident: UUID) -> dict[str, Any] | None:
        ligne = await self.base.fetchrow(f"SELECT {COLONNES} FROM ateliers WHERE id = $1", ident)  # noqa: S608
        return dict(ligne) if ligne else None

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

    async def creer(self, projet_id: str, nom: str, acteur: str) -> dict[str, Any]:
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
            "INSERT INTO ateliers (id, projet, nom, branche, chemin, cree_par) VALUES ($1, $2, $3, $4, $5, $6)",
            ident,
            projet.id,
            nom.strip()[:120] or "Atelier",
            branche,
            str(chemin),
            acteur,
        )
        await self._noter(ident, "cree", {"branche": branche, "chemin": str(chemin)})
        atelier = await self.obtenir(ident)
        assert atelier is not None
        return atelier

    def arguments(self, jeton: str, session: str | None) -> list[str]:
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
        return [*args, "--resume", session] if session else args

    async def lancer(self, ident: UUID, consigne: str, reprendre: bool = False) -> None:
        atelier = await self.obtenir(ident)
        if atelier is None:
            raise ErreurAtelier("Atelier introuvable")
        if atelier["statut"] in ("fusionne", "abandonne"):
            raise ErreurAtelier("Atelier terminé")
        if ident in self.processus:
            raise ErreurAtelier("Cet atelier travaille déjà")
        if self.urgence.actif:
            raise ErreurAtelier("Arrêt d'urgence actif")
        session = atelier["session"] if reprendre else None
        await self._statut(ident, "en_cours")
        await self._noter(ident, "consigne", {"texte": consigne, "reprise": bool(session)})
        tache = asyncio.get_running_loop().create_task(
            self._executer(ident, Path(atelier["chemin"]), consigne, session)
        )
        self.taches[ident] = tache
        tache.add_done_callback(lambda _: self.taches.pop(ident, None))

    async def _executer(self, ident: UUID, chemin: Path, consigne: str, session: str | None) -> None:
        jeton = secrets.token_urlsafe(32)
        self.jetons[jeton] = ident
        statut_final = "pret"
        try:
            with self.urgence.suivre():
                proc = await asyncio.create_subprocess_exec(
                    *self.arguments(jeton, session),
                    cwd=str(chemin),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    env=environnement_propre(dict(os.environ)),
                    limit=16 * 1024 * 1024,
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
                        statut_final = "erreur"
                        break
                await proc.wait()
        except asyncio.CancelledError:
            statut_final = "arrete"
            raise
        except OSError as exc:
            statut_final = "erreur"
            await self._noter(ident, "erreur", {"message": f"Claude Code introuvable : {exc}"})
        finally:
            self.jetons.pop(jeton, None)
            proc_fini = self.processus.pop(ident, None)
            if proc_fini is not None and proc_fini.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc_fini.kill()
            for a in [a for a in self.attentes.values() if a.atelier == ident]:
                if not a.futur.done():
                    a.futur.set_result(False)
            actuel = await self.obtenir(ident)
            if actuel is not None and actuel["statut"] == "en_cours":
                await asyncio.shield(self._statut(ident, statut_final))

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
        tache.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await tache
        await self._statut(ident, "arrete")
        await self._noter(ident, "arret", {})
        return True

    # --- Autorisations (appelées par l'outil d'autorisation de Claude Code) ----------------------------------

    async def autoriser(self, jeton: str, outil: str, entree: dict[str, Any]) -> dict[str, Any]:
        ident = self.jetons.get(jeton)
        if ident is None:
            return {"behavior": "deny", "message": "Session d'atelier inconnue"}
        atelier = await self.obtenir(ident)
        if atelier is None or self.urgence.actif:
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

    async def fermer(self) -> None:
        for ident in list(self.taches):
            await self.arreter(ident)
