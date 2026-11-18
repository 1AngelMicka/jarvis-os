"""Moteurs d'inférence (connecteurs d'IA). L'import de ce paquet inscrit les classes dans `MoteurRegistry`.

Le catalogue complet des connecteurs d'une installation (comptes, clés d'API, modèles locaux) est construit par
`jarvis2.connecteurs.construire_catalogue`.
"""

from __future__ import annotations

from ..config import Parametres
from ..registre import MoteurRegistry
from . import anthropic_api, antigravity, claude_code, codex, compatible_openai, ollama  # noqa: F401 — inscription
from .base import ErreurMoteur, Moteur
from .telemetrie import Enregistreur, MoteurInstrumente

__all__ = ["ErreurMoteur", "Moteur", "MoteurInstrumente", "MoteurRegistry", "construire_moteurs"]


def construire_moteurs(parametres: Parametres, enregistreur: Enregistreur) -> dict[str, MoteurInstrumente]:
    """Moteurs de base (Claude Code et Ollama), sans coffre ni configuration locale : tests et outils."""
    moteurs = {
        "claude_code": claude_code.MoteurClaudeCode(
            commande=parametres.claude_commande or None,
            modele=parametres.claude_modele,
            effort=parametres.claude_effort,
            dossier_travail=parametres.dossier_claude_vide,
        ),
        "ollama": ollama.MoteurOllama(url=parametres.ollama_url),
    }
    return {cle: MoteurInstrumente(m, enregistreur) for cle, m in moteurs.items()}
