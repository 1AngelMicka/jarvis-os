"""Exécution d'une CLI officielle d'IA (Codex, Antigravity…) en sous-processus, lue ligne par ligne (JSONL).

Garanties communes à tous les connecteurs « compte par CLI » :
- chaque appel tourne dans un dossier temporaire VIDE, effacé ensuite : la CLI n'y trouve aucun projet ni fichier ;
- l'environnement est nettoyé : aucune clé d'API, aucun secret de JARVIS (la CLI utilise le compte de l'utilisateur) ;
- le prompt passe par l'entrée standard (Windows limite la ligne de commande à 32 767 caractères) ;
- délai dépassé, annulation ou arrêt d'urgence : tout l'arbre de processus est tué.
JARVIS ne lit, ne copie ni ne stocke jamais les fichiers d'identifiants de ces CLI.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import AsyncGenerator, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .base import ErreurMoteur
from .claude_code import TAMPON, environnement_propre, tuer_arbre


def environnement(retirees: Iterable[str] = (), source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environnement du sous-processus sans secrets (voir claude_code) ni les variables `retirees`."""
    supplementaires = {v.upper() for v in retirees}
    base = environnement_propre(source if source is not None else os.environ)
    return {k: v for k, v in base.items() if k.upper() not in supplementaires}


def trouver(commande: str | Sequence[str] | None, nom: str) -> list[str] | None:
    """Commande à lancer : celle de la configuration, sinon le binaire `nom` du PATH ; None s'il est absent."""
    if isinstance(commande, str) and commande.strip():
        return [commande.strip()]
    if commande and not isinstance(commande, str):
        return list(commande)
    chemin = shutil.which(nom)
    return [chemin] if chemin else None


async def executer_court(args: Sequence[str], env: Mapping[str, str], delai: float = 15.0) -> tuple[int, str]:
    """Commande brève (version, état de connexion, liste des modèles) : (code, sortie + erreurs)."""
    with tempfile.TemporaryDirectory(prefix="jarvis2-") as vide:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=vide,
            env=dict(env),
        )
        try:
            sortie, _ = await asyncio.wait_for(proc.communicate(), timeout=delai)
        except TimeoutError:
            tuer_arbre(proc)
            await proc.wait()
            return 124, "délai dépassé"
    return proc.returncode or 0, sortie.decode("utf-8", "replace")


async def lignes_json(
    args: Sequence[str],
    entree: str,
    env: Mapping[str, str],
    delai: float,
    dossier_parent: Path | None = None,
) -> AsyncGenerator[dict[str, Any]]:
    """Lance la CLI, écrit `entree` sur son entrée standard, rend chaque ligne JSON de sa sortie (les autres lignes
    sont ignorées). Lève ErreurMoteur si la CLI échoue sans rien produire d'exploitable."""
    if dossier_parent is not None:
        await asyncio.to_thread(dossier_parent.mkdir, parents=True, exist_ok=True)
    groupe: dict[str, Any] = {"start_new_session": True}
    if sys.platform == "win32":
        groupe = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    with tempfile.TemporaryDirectory(prefix="jarvis2-", dir=dossier_parent) as vide:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=vide,
                env=dict(env),
                limit=TAMPON,
                **groupe,
            )
        except FileNotFoundError as exc:
            raise ErreurMoteur(f"{Path(args[0]).name} introuvable : programme non installé") from exc
        assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
        erreurs = asyncio.create_task(proc.stderr.read())
        echeance = time.monotonic() + delai
        termine = False
        vues = 0
        try:
            proc.stdin.write(entree.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
            while True:
                reste = echeance - time.monotonic()
                if reste <= 0:
                    raise TimeoutError
                ligne = await asyncio.wait_for(proc.stdout.readline(), timeout=reste)
                if not ligne:
                    break
                try:
                    evenement = json.loads(ligne.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if isinstance(evenement, dict):
                    vues += 1
                    yield evenement
            await asyncio.wait_for(proc.wait(), timeout=max(1.0, echeance - time.monotonic()))
            termine = True
        except TimeoutError as exc:
            raise ErreurMoteur(f"{Path(args[0]).name} n'a pas répondu en {delai:.0f} s") from exc
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise ErreurMoteur(f"{Path(args[0]).name} s'est arrêté avant de lire la demande") from exc
        finally:
            if not termine:
                tuer_arbre(proc)
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(proc.wait(), timeout=10)
            if not erreurs.done():
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(asyncio.shield(erreurs), timeout=2)
            if not erreurs.done():
                erreurs.cancel()
        if proc.returncode not in (0, None) and vues == 0:
            detail = (erreurs.result() if erreurs.done() and not erreurs.cancelled() else b"").decode(
                "utf-8", "replace"
            )
            raise ErreurMoteur(f"{Path(args[0]).name} a échoué (code {proc.returncode}) : {detail.strip()[:300]}")
