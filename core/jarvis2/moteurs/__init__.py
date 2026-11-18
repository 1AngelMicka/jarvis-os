"""Moteurs d'inférence. L'import de ce paquet inscrit les moteurs fournis dans `MoteurRegistry`."""

from __future__ import annotations

from ..config import Parametres
from ..registre import MoteurRegistry
from . import claude_code, ollama  # noqa: F401 — inscription dans le registre
from .base import ErreurMoteur, Moteur
from .telemetrie import Enregistreur, MoteurInstrumente

__all__ = ["ErreurMoteur", "Moteur", "MoteurInstrumente", "MoteurRegistry", "construire_moteurs"]


def construire_moteurs(parametres: Parametres, enregistreur: Enregistreur) -> dict[str, MoteurInstrumente]:
    """Instancie chaque moteur inscrit avec sa configuration, enveloppé dans la télémétrie."""
    reglages: dict[str, dict[str, object]] = {
        "claude_code": {
            "commande": parametres.claude_commande or None,
            "modele": parametres.claude_modele,
            "effort": parametres.claude_effort,
            "dossier_travail": parametres.dossier_claude_vide,
        },
        "ollama": {"url": parametres.ollama_url},
    }
    moteurs: dict[str, MoteurInstrumente] = {}
    for cle in MoteurRegistry.keys():  # noqa: SIM118 — méthode du registre, pas un dict
        moteur = MoteurRegistry.create(cle, **reglages.get(cle, {}))
        moteurs[cle] = MoteurInstrumente(moteur, enregistreur)
    return moteurs
