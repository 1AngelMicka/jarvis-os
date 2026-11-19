"""Amélioration continue (phase 13, lot O) : une suggestion → un atelier → un aperçu testé → mise en service → retour
arrière possible.

- **Suggestion** : de JARVIS (proposée sous une réponse, validée d'un clic) ou de l'utilisateur, toujours avec son
  origine et sa raison. Aucune ne démarre seule.
- **Réalisation** dans un atelier Claude Code (`ateliers/`) : worktree et branche `jarvis/atelier-…` dédiés, jamais
  sur la branche du projet.
- **Aperçu** : différences entre la branche de l'atelier et le projet (fichiers non commités compris, lus par un
  index git temporaire : rien n'est modifié), et dernier essai des tests du projet sur ce contenu exact. L'empreinte
  du contenu (arbre git) relie l'essai des tests et la demande de mise en service à ce qui a été vu.
- **Mise en service** 🟡 (file d'approbations, jamais « toujours autorisée ») : refusée si le contenu a changé depuis
  la demande ou si les tests configurés n'ont pas réussi sur ce contenu ; fusion LOCALE (`merge --no-ff`), jamais de
  push. Le commit d'avant est noté.
- **Retour arrière** 🟡 : `git revert` du commit de fusion (rien n'est effacé de l'historique) ; si rien n'a été
  commité depuis, le projet revient exactement à l'arbre du commit d'avant (vérifié), puis les tests sont relancés.

Les tests ne sont lancés que sur un clic (ou après un retour arrière), avec la commande de la configuration locale
(`[[ateliers.projets]] tests`), sans clé d'API dans l'environnement, et sont interrompus par l'arrêt d'urgence.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from .ateliers.gestionnaire import ErreurAtelier, GestionnaireAteliers, Projet, git
from .db import Base
from .moteurs.claude_code import environnement_propre
from .securite.filtre import masquer_secrets
from .securite.urgence import ArretUrgence

journal = logging.getLogger("jarvis2.ameliorations")

COLONNES = (
    "id, titre, raison, description, origine, projet, statut, atelier_id, tests, commit_avant, commit_service,"
    " commit_retour, cree_par, cree_le, maj_le, en_service_le, retiree_le"
)
ORIGINES = ("jarvis", "utilisateur")
OUVERTES = ("proposee", "en_atelier")
DELAI_TESTS = 900.0  # secondes au plus pour les tests d'un projet
SORTIE_MAX = 20_000  # caractères gardés de la sortie des tests (la fin, où sont les erreurs)
DIFF_MAX = 200_000  # caractères du diff montrés dans l'aperçu
GIT_JARVIS = ("-c", "user.name=JARVIS", "-c", "user.email=jarvis@localhost")


class ErreurAmelioration(RuntimeError):
    """Message en français, affichable tel quel."""


def _maintenant() -> str:
    return datetime.now(UTC).isoformat()


async def _git_env(cwd: Path, env: dict[str, str], *args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(cwd), env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    sortie, _ = await proc.communicate()
    return proc.returncode or 0, sortie.decode("utf-8", "replace").strip()


async def instantane(worktree: Path, base: str) -> dict[str, Any]:
    """Contenu exact d'un worktree (fichiers non commités et nouveaux compris) comparé au commit `base`, lu par un
    index git TEMPORAIRE : ni l'index ni les fichiers du worktree ne sont modifiés. L'empreinte est l'arbre git."""
    with tempfile.TemporaryDirectory(prefix="jarvis2-apercu-") as dossier:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(dossier) / "index")}
        code, sortie = await _git_env(worktree, env, "add", "-A")
        if code != 0:
            raise ErreurAmelioration(f"Lecture de l'atelier impossible : {sortie[:300]}")
        _, empreinte = await _git_env(worktree, env, "write-tree")
        _, numstat = await _git_env(worktree, env, "diff", "--cached", "--numstat", "--no-renames", base)
        _, etats = await _git_env(worktree, env, "diff", "--cached", "--name-status", "--no-renames", base)
        _, diff = await _git_env(worktree, env, "diff", "--cached", "--no-renames", "--no-color", base)
    lettres = {}
    for ligne in etats.splitlines():
        lettre, _, chemin = ligne.partition("\t")
        lettres[chemin] = {"A": "ajoute", "D": "supprime"}.get(lettre[:1], "modifie")
    fichiers = []
    for ligne in numstat.splitlines():
        ajouts, retraits, chemin = [*ligne.split("\t", 2), "", ""][:3]
        fichiers.append(
            {
                "chemin": chemin,
                "etat": lettres.get(chemin, "modifie"),
                "ajouts": int(ajouts) if ajouts.isdigit() else None,  # None : fichier binaire
                "retraits": int(retraits) if retraits.isdigit() else None,
            }
        )
    tronque = len(diff) > DIFF_MAX
    return {
        "empreinte": empreinte,
        "fichiers": fichiers,
        "diff": masquer_secrets(diff[:DIFF_MAX]),
        "diff_tronque": tronque,
    }


class ServiceAmeliorations:
    def __init__(self, base: Base, ateliers: GestionnaireAteliers | None, urgence: ArretUrgence) -> None:
        self.base = base
        self.ateliers = ateliers
        self.urgence = urgence
        self.taches: dict[UUID, asyncio.Task[None]] = {}

    # --- Lecture ---------------------------------------------------------------------------------------------

    def _gestionnaire(self) -> GestionnaireAteliers:
        if self.ateliers is None:
            raise ErreurAmelioration("Ateliers indisponibles : aucun projet configuré")
        return self.ateliers

    def _projet(self, ident: str) -> Projet:
        projet = self._gestionnaire().projets.get(ident)
        if projet is None:
            raise ErreurAmelioration(f"Projet inconnu : « {ident} » (configuration locale, [[ateliers.projets]])")
        return projet

    def projets(self) -> list[dict[str, Any]]:
        if self.ateliers is None:
            return []
        return [{"id": p.id, "nom": p.nom, "tests": " ".join(p.tests)} for p in self.ateliers.projets.values()]

    async def obtenir(self, ident: UUID) -> dict[str, Any] | None:
        ligne = await self.base.fetchrow(f"SELECT {COLONNES} FROM ameliorations WHERE id = $1", ident)  # noqa: S608
        return self._completer(dict(ligne)) if ligne else None

    async def _exiger(self, ident: UUID) -> dict[str, Any]:
        a = await self.obtenir(ident)
        if a is None:
            raise ErreurAmelioration("Amélioration introuvable")
        return a

    def _completer(self, a: dict[str, Any]) -> dict[str, Any]:
        tests = a.get("tests")
        a["tests"] = (json.loads(tests) if isinstance(tests, str) else tests) or {}
        a["tests_en_cours"] = a["id"] in self.taches
        return a

    async def lister(self) -> list[dict[str, Any]]:
        lignes = await self.base.fetch(
            f"SELECT {COLONNES} FROM ameliorations ORDER BY cree_le DESC LIMIT 200"  # noqa: S608
        )
        return [self._completer(dict(r)) for r in lignes]

    async def _maj(self, ident: UUID, **champs: Any) -> None:
        if not champs:
            return
        noms = list(champs)
        affectations = ", ".join(f"{n} = ${i + 2}" for i, n in enumerate(noms))
        await self.base.execute(
            f"UPDATE ameliorations SET {affectations}, maj_le = now() WHERE id = $1",  # noqa: S608 — noms internes
            ident,
            *champs.values(),
        )

    async def _noter_tests(self, ident: UUID, cle: str, essai: dict[str, Any]) -> None:
        a = await self._exiger(ident)
        tests = {**a["tests"], cle: essai}
        await self.base.execute(
            "UPDATE ameliorations SET tests = $2::text::jsonb, maj_le = now() WHERE id = $1", ident, json.dumps(tests)
        )

    # --- Suggestions -----------------------------------------------------------------------------------------

    async def proposer(
        self, projet: str, titre: str, raison: str, description: str, origine: str, acteur: str
    ) -> dict[str, Any]:
        if origine not in ORIGINES:
            raise ErreurAmelioration("Origine : jarvis ou utilisateur")
        self._projet(projet)
        titre, raison = " ".join(titre.split()), raison.strip()
        if not titre or not raison:
            raise ErreurAmelioration("Une suggestion a toujours un titre et une raison")
        doublon = await self.base.fetchval(
            "SELECT id FROM ameliorations WHERE projet = $1 AND lower(titre) = lower($2)"
            " AND statut IN ('proposee', 'en_atelier')",
            projet,
            titre,
        )
        if doublon is not None:
            raise ErreurAmelioration("Cette amélioration est déjà proposée pour ce projet")
        ligne = await self.base.fetchrow(
            "INSERT INTO ameliorations (titre, raison, description, origine, projet, cree_par)"  # noqa: S608
            f" VALUES ($1, $2, $3, $4, $5, $6) RETURNING {COLONNES}",
            titre[:200],
            raison[:2000],
            description.strip()[:10_000],
            origine,
            projet,
            acteur,
        )
        assert ligne is not None
        return self._completer(dict(ligne))

    async def rejeter(self, ident: UUID) -> dict[str, Any]:
        """Écarte une suggestion pas encore en service ; son atelier éventuel est retiré (la branche reste)."""
        a = await self._exiger(ident)
        if a["statut"] not in OUVERTES:
            raise ErreurAmelioration("Seule une amélioration pas encore en service peut être écartée")
        if a["atelier_id"] is not None and self.ateliers is not None:
            atelier = await self.ateliers.obtenir(a["atelier_id"])
            if atelier is not None and atelier["statut"] not in ("fusionne", "abandonne"):
                await self.ateliers.abandonner(a["atelier_id"])
        await self._maj(ident, statut="rejetee")
        return await self._exiger(ident)

    # --- Réalisation dans un atelier -------------------------------------------------------------------------

    @staticmethod
    def consigne(a: dict[str, Any]) -> str:
        texte = (
            f"Amélioration à réaliser : {a['titre']}\n\nPourquoi : {a['raison']}\n"
            + (f"\nDétails : {a['description']}\n" if a["description"] else "")
            + "\nTravaille seulement dans ce dossier (branche dédiée). Ajoute ou mets à jour les tests qui prouvent"
            " le changement et vérifie qu'ils passent. Ne pousse rien, ne fusionne rien : la mise en service sera"
            " décidée par l'utilisateur après l'aperçu."
        )
        return texte

    async def ouvrir_atelier(self, ident: UUID, acteur: str, lancer: bool) -> dict[str, Any]:
        g = self._gestionnaire()
        a = await self._exiger(ident)
        if a["statut"] != "proposee":
            raise ErreurAmelioration("L'atelier de cette amélioration est déjà ouvert (ou elle est terminée)")
        try:
            atelier = await g.creer(a["projet"], a["titre"][:120], acteur)
        except ErreurAtelier as exc:
            raise ErreurAmelioration(str(exc)) from exc
        await self._maj(ident, statut="en_atelier", atelier_id=atelier["id"])
        if lancer:
            try:
                await g.lancer(atelier["id"], self.consigne(a))
            except ErreurAtelier as exc:
                raise ErreurAmelioration(f"Atelier ouvert, mais consigne non lancée : {exc}") from exc
        return await self._exiger(ident)

    async def _atelier(self, a: dict[str, Any]) -> dict[str, Any]:
        if a["atelier_id"] is None:
            raise ErreurAmelioration("Aucun atelier pour cette amélioration")
        atelier = await self._gestionnaire().obtenir(a["atelier_id"])
        if atelier is None:
            raise ErreurAmelioration("Atelier introuvable")
        return atelier

    # --- Aperçu ----------------------------------------------------------------------------------------------

    async def apercu(self, ident: UUID) -> dict[str, Any]:
        a = await self._exiger(ident)
        atelier = await self._atelier(a)
        projet = self._projet(a["projet"])
        worktree = Path(atelier["chemin"])
        if not await asyncio.to_thread(worktree.is_dir):
            raise ErreurAmelioration("Le dossier de l'atelier n'existe plus (atelier clôturé ou abandonné)")
        code, tete = await git(projet.chemin, "rev-parse", "HEAD")
        if code != 0:
            raise ErreurAmelioration("Tête du projet illisible")
        code, base = await git(worktree, "merge-base", "HEAD", tete)
        if code != 0:
            raise ErreurAmelioration("Point de départ de l'atelier introuvable")
        vue = await instantane(worktree, base)
        essai = a["tests"].get("atelier") or {}
        g = self._gestionnaire()
        return {
            **vue,
            "base": base,
            "tete_projet": tete,
            "branche": atelier["branche"],
            "atelier_statut": atelier["statut"],
            "atelier_actif": atelier["id"] in g.processus or atelier["id"] in g.taches,
            "commande_tests": " ".join(projet.tests),
            "tests": essai,
            "tests_a_jour": bool(essai) and essai.get("empreinte") == vue["empreinte"],
        }

    # --- Tests -----------------------------------------------------------------------------------------------

    async def executer_tests(self, projet: Projet, racine: Path) -> dict[str, Any]:
        """Lance la commande de tests de la configuration locale (sans shell, sans clé d'API, durée bornée)."""
        if not projet.tests:
            raise ErreurAmelioration("Aucune commande de tests pour ce projet ([[ateliers.projets]] tests)")
        dossier = (racine / projet.dossier_tests) if projet.dossier_tests else racine
        debut = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *projet.tests,
                cwd=str(dossier),
                # Pas de fichiers .pyc écrits par des tests Python : ils changeraient le contenu testé
                env={**environnement_propre(os.environ), "PYTHONDONTWRITEBYTECODE": "1"},
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            return {"reussi": False, "code": None, "sortie": f"Commande introuvable : {exc}", "duree": 0.0}
        try:
            sortie, _ = await asyncio.wait_for(proc.communicate(), DELAI_TESTS)
            code: int | None = proc.returncode
            texte = sortie.decode("utf-8", "replace")
        except (TimeoutError, asyncio.CancelledError) as exc:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), 10)
            if isinstance(exc, asyncio.CancelledError):
                raise
            code, texte = None, f"Tests interrompus : plus de {int(DELAI_TESTS)} s"
        return {
            "reussi": code == 0,
            "code": code,
            "sortie": masquer_secrets(texte[-SORTIE_MAX:]),
            "duree": round(time.monotonic() - debut, 1),
        }

    async def tester(self, ident: UUID) -> None:
        """Lance les tests du projet dans le worktree de l'atelier, en arrière-plan (résultat noté avec l'empreinte)."""
        if self.urgence.actif:
            raise ErreurAmelioration("Arrêt d'urgence actif")
        if ident in self.taches:
            raise ErreurAmelioration("Les tests tournent déjà")
        a = await self._exiger(ident)
        if a["statut"] != "en_atelier":
            raise ErreurAmelioration("Les tests de l'atelier ne se lancent qu'avant la mise en service")
        atelier = await self._atelier(a)
        projet = self._projet(a["projet"])
        if not projet.tests:
            raise ErreurAmelioration("Aucune commande de tests pour ce projet ([[ateliers.projets]] tests)")
        g = self._gestionnaire()
        if atelier["id"] in g.processus or atelier["id"] in g.taches:
            raise ErreurAmelioration("L'atelier travaille encore : attendez la fin avant de tester")
        worktree = Path(atelier["chemin"])
        _, tete = await git(projet.chemin, "rev-parse", "HEAD")
        _, base = await git(worktree, "merge-base", "HEAD", tete)
        empreinte = (await instantane(worktree, base))["empreinte"]

        async def tache() -> None:
            with self.urgence.suivre():  # l'arrêt d'urgence interrompt les tests
                try:
                    essai = await self.executer_tests(projet, worktree)
                except asyncio.CancelledError:
                    essai = {"reussi": False, "code": None, "sortie": "Tests interrompus (arrêt d'urgence)"}
                    await self._noter_tests(ident, "atelier", {**essai, "empreinte": empreinte, "le": _maintenant()})
                    raise
                except Exception as exc:
                    essai = {"reussi": False, "code": None, "sortie": f"Erreur : {exc}"}
                # Contenu modifié pendant les tests (fichiers écrits par les tests et non ignorés par git, ou travail
                # en parallèle) : l'essai ne vaut pas pour le nouveau contenu, et on le dit
                apres = (await instantane(worktree, base))["empreinte"]
                change = apres != empreinte
                await self._noter_tests(
                    ident,
                    "atelier",
                    {**essai, "empreinte": "" if change else empreinte, "contenu_change": change, "le": _maintenant()},
                )

        t = asyncio.create_task(tache())
        self.taches[ident] = t
        t.add_done_callback(lambda _: self.taches.pop(ident, None))

    async def attendre_tests(self, ident: UUID) -> None:
        t = self.taches.get(ident)
        if t is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await t

    # --- Mise en service et retour arrière (exécutées par la file d'approbations) -----------------------------

    async def parametres_mise_en_service(self, ident: UUID) -> dict[str, Any]:
        """Paramètres de la demande 🟡, calculés par le Core : l'empreinte lie l'approbation au contenu vu."""
        a = await self._exiger(ident)
        if a["statut"] != "en_atelier":
            raise ErreurAmelioration("Seule une amélioration en atelier peut être mise en service")
        vue = await self.apercu(ident)
        self._verifier_pret(vue)
        return {
            "amelioration_id": str(ident),
            "titre": a["titre"],
            "projet": a["projet"],
            "empreinte": vue["empreinte"],
            "fichiers": len(vue["fichiers"]),
        }

    @staticmethod
    def _verifier_pret(vue: dict[str, Any]) -> None:
        if vue["atelier_actif"]:
            raise ErreurAmelioration("L'atelier travaille encore : attendez la fin")
        if not vue["fichiers"]:
            raise ErreurAmelioration("L'atelier n'a rien changé : rien à mettre en service")
        if vue["commande_tests"] and not (vue["tests_a_jour"] and vue["tests"].get("reussi")):
            raise ErreurAmelioration("Les tests doivent avoir réussi sur ce contenu exact : relancez-les")

    async def mettre_en_service(self, ident: UUID, empreinte: str) -> dict[str, Any]:
        if self.urgence.actif:
            raise ErreurAmelioration("Arrêt d'urgence actif")
        a = await self._exiger(ident)
        if a["statut"] != "en_atelier":
            raise ErreurAmelioration("Seule une amélioration en atelier peut être mise en service")
        vue = await self.apercu(ident)
        if vue["empreinte"] != empreinte:
            raise ErreurAmelioration("L'atelier a changé depuis la demande : revoyez l'aperçu et redemandez")
        self._verifier_pret(vue)
        projet = self._projet(a["projet"])
        _, avant = await git(projet.chemin, "rev-parse", "HEAD")
        try:
            await self._gestionnaire().fusionner(self.base, a["atelier_id"])  # commit puis merge --no-ff, local
        except ErreurAtelier as exc:
            raise ErreurAmelioration(str(exc)) from exc
        _, apres = await git(projet.chemin, "rev-parse", "HEAD")
        await self.base.execute(
            "UPDATE ameliorations SET statut = 'en_service', commit_avant = $2, commit_service = $3,"
            " en_service_le = now(), maj_le = now() WHERE id = $1",
            ident,
            avant,
            apres,
        )
        return {"amelioration_id": str(ident), "commit_avant": avant, "commit_service": apres}

    async def revenir(self, ident: UUID) -> dict[str, Any]:
        """Annule la mise en service par `git revert` du commit de fusion (historique gardé), puis vérifie l'arbre
        et relance les tests du projet en arrière-plan."""
        if self.urgence.actif:
            raise ErreurAmelioration("Arrêt d'urgence actif")
        a = await self._exiger(ident)
        if a["statut"] != "en_service" or not a["commit_service"] or not a["commit_avant"]:
            raise ErreurAmelioration("Seule une amélioration en service peut être retirée")
        projet = self._projet(a["projet"])
        code, etat = await git(projet.chemin, "status", "--porcelain")
        if code != 0 or etat:
            raise ErreurAmelioration("Le projet a des modifications non commitées : retour arrière refusé")
        _, tete = await git(projet.chemin, "rev-parse", "HEAD")
        code, _ = await git(projet.chemin, "merge-base", "--is-ancestor", a["commit_service"], "HEAD")
        if code != 0:
            raise ErreurAmelioration("Le commit de mise en service n'est plus dans la branche du projet")
        code, sortie = await git(projet.chemin, *GIT_JARVIS, "revert", "-m", "1", "--no-edit", a["commit_service"])
        if code != 0:
            await git(projet.chemin, "revert", "--abort")
            raise ErreurAmelioration(f"Conflit : retour arrière annulé, le projet est inchangé ({sortie[:300]})")
        _, retour = await git(projet.chemin, "rev-parse", "HEAD")
        exact = None
        if tete == a["commit_service"]:  # rien depuis la mise en service : on doit retrouver l'arbre d'avant
            _, arbre = await git(projet.chemin, "rev-parse", "HEAD^{tree}")
            _, arbre_avant = await git(projet.chemin, "rev-parse", f"{a['commit_avant']}^{{tree}}")
            exact = arbre == arbre_avant
            if not exact:  # ne devrait jamais arriver : on le dit plutôt que de le cacher
                journal.error("Retour arrière de %s : arbre différent du commit d'avant", ident)
        await self.base.execute(
            "UPDATE ameliorations SET statut = 'retiree', commit_retour = $2, retiree_le = now(), maj_le = now()"
            " WHERE id = $1",
            ident,
            retour,
        )
        if projet.tests:
            self._tester_projet(ident, projet)
        return {"amelioration_id": str(ident), "commit_retour": retour, "identique_a_avant": exact}

    def _tester_projet(self, ident: UUID, projet: Projet) -> None:
        async def tache() -> None:
            with self.urgence.suivre():
                try:
                    essai = await self.executer_tests(projet, projet.chemin)
                except asyncio.CancelledError:
                    await self._noter_tests(
                        ident, "retour", {"reussi": False, "code": None, "sortie": "Tests interrompus", "le": ""}
                    )
                    raise
                except Exception as exc:
                    essai = {"reussi": False, "code": None, "sortie": f"Erreur : {exc}"}
                await self._noter_tests(ident, "retour", {**essai, "le": _maintenant()})

        t = asyncio.create_task(tache())
        self.taches[ident] = t
        t.add_done_callback(lambda _: self.taches.pop(ident, None))

    async def fermer(self) -> None:
        for t in list(self.taches.values()):
            t.cancel()
        for t in list(self.taches.values()):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
