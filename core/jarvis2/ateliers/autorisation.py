"""Décision sur chaque outil que Claude Code veut utiliser dans un atelier (outil d'autorisation de JARVIS).

- Écriture (Edit, Write, MultiEdit, NotebookEdit) : AUTORISÉE dans le worktree de l'atelier, REFUSÉE ailleurs —
  chemins résolus (`..`, liens symboliques, autre disque) avant comparaison.
- Lecture (Read, Glob, Grep, LS) : autorisée dans le worktree ; ailleurs, l'utilisateur décide.
- Commandes (Bash), accès réseau (WebFetch, WebSearch) et tout autre outil : l'utilisateur décide, en direct.
- Jamais : écrire dans `.git` (l'historique se fait par la fusion approuvée), ni dans un fichier `.env`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

ECRITURE = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
LECTURE = frozenset({"Read", "Glob", "Grep", "LS"})
SANS_EFFET = frozenset({"TodoWrite", "ExitPlanMode", "Task"})  # outils internes de Claude Code, sans accès au disque
CLES_CHEMIN = ("file_path", "notebook_path", "path")

Verdict = Literal["autoriser", "refuser", "demander"]


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    raison: str

    def reponse(self, entree: dict[str, Any]) -> dict[str, Any]:
        """Réponse attendue par Claude Code (`--permission-prompt-tool`)."""
        if self.verdict == "autoriser":
            return {"behavior": "allow", "updatedInput": entree}
        return {"behavior": "deny", "message": self.raison}


def dans(racine: Path, chemin: str) -> bool:
    """Le chemin (relatif à la racine ou absolu), une fois résolu, est-il dans la racine ?"""
    base = racine.resolve()
    cible = Path(chemin)
    cible = (cible if cible.is_absolute() else base / cible).resolve()
    return cible == base or base in cible.parents


def interdit(racine: Path, chemin: str) -> bool:
    cible = Path(chemin)
    parties = (cible if cible.is_absolute() else racine / cible).resolve().parts
    return ".git" in parties or Path(chemin).name.lower().startswith(".env")


def decider(racine: Path, outil: str, entree: dict[str, Any]) -> Decision:
    chemins = [str(entree[c]) for c in CLES_CHEMIN if isinstance(entree.get(c), str) and entree[c]]
    if outil in ECRITURE:
        if not chemins:
            return Decision("refuser", f"{outil} sans chemin de fichier")
        for c in chemins:
            if not dans(racine, c):
                return Decision("refuser", f"Écriture hors de l'atelier refusée : {c}")
            if interdit(racine, c):
                return Decision("refuser", f"Écriture interdite (.git ou .env) : {c}")
        return Decision("autoriser", "écriture dans l'atelier")
    if outil in LECTURE:
        if all(dans(racine, c) for c in chemins):
            return Decision("autoriser", "lecture dans l'atelier")
        return Decision("demander", f"Lecture hors de l'atelier : {', '.join(chemins)}")
    if outil in SANS_EFFET:
        return Decision("autoriser", "outil interne de Claude Code")
    if outil == "Bash":
        return Decision("demander", f"Commande : {str(entree.get('command', ''))[:500]}")
    return Decision("demander", f"Outil {outil}")
