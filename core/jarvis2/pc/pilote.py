"""Abstraction du contrôle du PC : ce que JARVIS sait lire et régler, sans dire comment.

`PilotePC` est implémenté par `windows.PiloteWindows` (le vrai PC) et, dans les tests, par un faux qui ne touche
à rien. Le service (`pc/__init__.py`) ne parle qu'à cette interface : il n'y a qu'un endroit où Windows est
réellement modifié.

Règle de vérification : chaque réglage est RELU après coup. Si la relecture est impossible ou ne donne pas la
valeur attendue, l'action est rendue « non vérifiée », jamais « faite » sur la seule foi de l'appel.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

CommandeMedia = Literal["lecture", "pause", "bascule", "suivant", "precedent"]
ActionFenetre = Literal["activer", "minimiser", "restaurer", "fermer"]


class ErreurPilote(RuntimeError):
    """Message en français, affichable tel quel (fonction absente de ce système, refus de Windows…)."""


@dataclass(frozen=True)
class Fenetre:
    id: int  # identifiant de la fenêtre (HWND sous Windows)
    titre: str
    programme: str  # nom de l'exécutable, ex. « notepad.exe »
    active: bool = False
    reduite: bool = False

    def en_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Media:
    application: str | None = None
    titre: str | None = None
    artiste: str | None = None
    statut: str | None = None  # « lecture », « pause », « arret », None si rien ne joue

    def en_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Volume:
    niveau: int  # 0 à 100
    muet: bool


class PilotePC(Protocol):
    """Lecture et réglages du PC. Toutes les méthodes sont bloquantes (appelées dans un fil à part)."""

    nom: str

    # --- Lecture (🟢) ---
    def lire_volume(self) -> Volume | None: ...
    def lire_luminosite(self) -> int | None: ...
    def fenetres(self) -> list[Fenetre]: ...
    def media(self) -> Media | None: ...
    def verrouille(self) -> bool | None: ...
    def lire_plan_alimentation(self) -> str | None: ...  # identifiant du plan actif
    def plans_alimentation(self) -> dict[str, str]: ...  # identifiant → nom
    def lire_notifications(self) -> bool | None: ...  # bannières de notification de Windows autorisées ?
    def lire_theme_sombre(self) -> bool | None: ...

    # --- Réglages (🟡🔴, toujours derrière la file d'approbations) ---
    def regler_volume(self, niveau: int) -> None: ...
    def regler_muet(self, muet: bool) -> None: ...
    def regler_luminosite(self, niveau: int) -> None: ...
    def agir_fenetre(self, ident: int, action: ActionFenetre) -> None: ...
    def commande_media(self, commande: CommandeMedia) -> None: ...
    def verrouiller(self) -> None: ...
    def planifier_extinction(self, delai_s: int, message: str) -> None: ...
    def annuler_extinction(self) -> bool: ...  # True : une extinction était prévue et a été annulée
    def regler_plan_alimentation(self, ident: str) -> None: ...
    def regler_notifications(self, actives: bool) -> None: ...
    def regler_theme_sombre(self, sombre: bool) -> None: ...


@dataclass(frozen=True)
class Verification:
    """Résultat d'une action : ce qui était demandé, ce qu'on a relu, et si les deux concordent."""

    verifiee: bool
    attendu: Any
    lu: Any
    detail: str = ""

    def en_dict(self) -> dict[str, Any]:
        return {
            "verifiee": self.verifiee,
            "statut": "vérifiée" if self.verifiee else "non vérifiée",
            "attendu": self.attendu,
            "lu": self.lu,
            **({"detail": self.detail} if self.detail else {}),
        }


async def verifier(
    lire: Callable[[], Any],
    attendu: Any,
    concorde: Callable[[Any, Any], bool] | None = None,
    essais: int = 4,
    pause: float = 0.25,
) -> Verification:
    """Relit l'état (dans un fil) jusqu'à ce qu'il concorde, quelques fois : Windows applique parfois un réglage
    avec un léger retard (luminosité DDC/CI, fenêtre qui se ferme). Une lecture impossible donne « non vérifiée »."""
    egal = concorde or (lambda a, b: a == b)
    lu: Any = None
    for i in range(essais):
        try:
            lu = await asyncio.to_thread(lire)
        except ErreurPilote as exc:
            return Verification(False, attendu, None, f"relecture impossible : {exc}")
        if lu is not None and egal(lu, attendu):
            return Verification(True, attendu, lu)
        if i < essais - 1:
            await asyncio.sleep(pause)
    detail = "relecture impossible sur ce PC" if lu is None else "l'état relu ne correspond pas à la demande"
    return Verification(False, attendu, lu, detail)


async def dans_un_fil(appel: Callable[[], Any]) -> Any:
    """Exécute un appel bloquant du pilote sans geler le Core."""
    return await asyncio.to_thread(appel)


Lecteur = Callable[[], Awaitable[Any]]
