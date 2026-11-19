"""Mode serveur sans écran (`jarvis2 serveur --sans-ecran`, ou `JARVIS2_SANS_ECRAN=true`).

Sur un serveur domestique, il n'y a ni écran ni session graphique : tout ce qui regarde ou pilote l'écran du PC
(capture décrite par la vision, clics, contrôle des fenêtres) est REFUSÉ par le Core, pas seulement masqué dans
l'interface. La voix passe par le micro du navigateur (ou d'un satellite), qui envoie l'enregistrement au Core.

Toute route qui touche l'écran appelle `exiger_ecran` (ou dépend de `garde_ecran`) avant d'agir.
"""

from __future__ import annotations

import os
import sys

from fastapi import HTTPException, Request

MESSAGE_SANS_ECRAN = "Indisponible en mode sans écran : ce Core tourne sur un serveur sans écran"
CODE_SANS_ECRAN = 409  # l'appel est valable, c'est l'état du Core qui l'empêche


class SansEcran(HTTPException):
    def __init__(self) -> None:
        super().__init__(CODE_SANS_ECRAN, MESSAGE_SANS_ECRAN)


def exiger_ecran(sans_ecran: bool) -> None:
    """Lève `SansEcran` si le Core tourne en mode sans écran."""
    if sans_ecran:
        raise SansEcran()


def garde_ecran(request: Request) -> None:
    """Dépendance FastAPI des routes d'écran : lit le mode dans le contexte du Core."""
    exiger_ecran(bool(getattr(request.app.state.ctx, "sans_ecran", False)))


def session_graphique() -> bool:
    """Une session graphique est-elle disponible pour ce processus ?

    Windows et macOS : on considère que oui (un service sans bureau reste rare) ; Linux et autres Unix :
    seulement si DISPLAY ou WAYLAND_DISPLAY est défini.
    """
    if sys.platform in ("win32", "darwin"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
