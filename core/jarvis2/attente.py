"""Phrase d'attente (phase 14, D 16) : dès qu'un outil long démarre, JARVIS le dit au lieu de rester muet.

Le Core émet l'événement SSE `attente` ({outil, phrase}) ; l'interface affiche la phrase à la place de « réflexion »
et la dit à voix haute si la lecture est active. Phrases fixes, choisies par le code : jamais écrites par le modèle,
elles ne disent que ce qui démarre vraiment (pas de « c'est fait » avant la fin).
"""

from __future__ import annotations

from typing import Any

PHRASES: dict[str, str] = {
    "conseil": "Je consulte le conseil d'experts, cela peut prendre une minute.",
    "vision": "Je regarde les images, un instant.",
    "recherche_web": "Je cherche sur le web, un instant.",
    "mission": "Je lance la mission, je vous préviens quand elle avance.",
    "memoire": "Je cherche dans ma mémoire.",
}


def phrase(outil: str) -> str:
    return PHRASES.get(outil, "Un instant, je m'en occupe.")


def evenement(outil: str) -> dict[str, Any]:
    """Données de l'événement SSE `attente`."""
    return {"outil": outil if outil in PHRASES else "autre", "phrase": phrase(outil)}
