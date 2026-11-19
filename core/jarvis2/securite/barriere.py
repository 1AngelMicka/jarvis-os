"""Barrière d'injection par tour : après une lecture de contenu non fiable, plus aucune action jusqu'à la fin du tour.

Un **tour** est une unité de travail menée par un modèle : une réponse du dialogue, une mission, une recette, une
exécution d'atelier piloté. Dès que ce tour a lu du contenu qui ne vient pas de l'utilisateur — page ou recherche
web, capture d'écran ou OCR, fichier externe, partage reçu, sortie d'une autre session, résultat d'outil MCP, fiche
de connaissances bâtie sur des sources externes —, il est **contaminé** : ce contenu peut contenir des instructions
cachées (injection de prompt). Jusqu'à la fin du tour :

- les **lectures** restent permises ;
- les **actions qui agissent** sont refusées : toute action 🟡 🔴 du registre, et les actions 🟢 qui écrivent ou
  envoient (`Action.ecrit`) ; les propositions du pilotage sont marquées bloquées (jamais appliquées seules) ;
- chaque refus a une raison claire, une entrée d'audit `barriere.action_refusee`, et l'utilisateur est invité à
  relancer l'action lui-même : une action lancée depuis l'interface (hors de tout tour) n'est jamais bloquée.

Ce module est le SEUL endroit où l'on marque un tour et où l'on décide d'un refus : chaque source de contenu
externe appelle `marquer()`, chaque exécuteur d'action appelle `verifier()`.

Deux façons de tenir un tour :
- `with tour("dialogue")` : le tour courant vit dans une variable de contexte (asyncio) ; `marquer()` sans tour
  courant ne fait rien (lecture demandée par l'utilisateur depuis l'interface) ;
- `Tour(...)` tenu explicitement par son propriétaire (un atelier : les autorisations de Claude Code arrivent par
  des requêtes HTTP séparées) et passé à `marquer(..., tour=)` / `refus_outil()`.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from ..db import Executant
from . import audit

if TYPE_CHECKING:
    from .permissions import Action

Source = Literal["web", "science", "ecran", "fichier", "partage", "session", "mcp", "atelier", "connaissances"]
SOURCES: dict[str, str] = {
    "web": "une page ou une recherche web",
    "science": "une source scientifique en ligne",
    "ecran": "une capture d'écran ou une image (OCR, vision)",
    "fichier": "un fichier externe",
    "partage": "un contenu partagé reçu",
    "session": "la sortie d'une autre session",
    "mcp": "le résultat d'un outil MCP",
    "atelier": "la sortie d'un atelier",
    "connaissances": "des fiches de connaissances bâties sur des sources externes",
}
ACTION_AUDIT = "barriere.action_refusee"
LONGUEUR_DETAIL = 120
# Pilotage : seules ces actions ne font que lire ou montrer ; tout le reste (régler, lancer, proposer, demander,
# ajouter une règle) agit et est bloqué dans un tour contaminé.
PILOTAGE_LECTURE = frozenset({"naviguer", "ouvrir", "rechercher_memoire"})
# Balise posée autour d'un contenu reçu de l'extérieur (partage du lot M) : la voir dans un message, c'est le lire
BALISE_NON_FIABLE = "<contenu_recu non_fiable>"


@dataclass(frozen=True)
class Lecture:
    source: str
    detail: str = ""

    def en_dict(self) -> dict[str, str]:
        return {"source": self.source, "libelle": SOURCES.get(self.source, self.source), "detail": self.detail}


@dataclass
class Tour:
    genre: str  # dialogue, mission, recette, atelier
    ident: str | None = None
    lectures: list[Lecture] = field(default_factory=list)
    bloquees: list[str] = field(default_factory=list)  # libellés des actions refusées pendant ce tour

    @property
    def contamine(self) -> bool:
        return bool(self.lectures)

    def marquer(self, source: str, detail: str = "") -> None:
        court = " ".join(str(detail).split())
        if len(court) > LONGUEUR_DETAIL:
            court = f"{court[: LONGUEUR_DETAIL - 1]}…"
        lecture = Lecture(source, court)
        if lecture not in self.lectures:
            self.lectures.append(lecture)

    def sources(self) -> list[str]:
        """Sources distinctes, dans l'ordre de la première lecture."""
        return list(dict.fromkeys(lu.source for lu in self.lectures))

    def raison(self) -> str:
        libelles = [SOURCES.get(s, s) for s in self.sources()]
        return (
            f"Barrière d'injection : ce tour a lu {', '.join(libelles)} (contenu non fiable). Aucune action n'est "
            "lancée par JARVIS jusqu'à la fin du tour : relancez-la vous-même si vous la voulez."
        )

    def bilan(self) -> dict[str, Any] | None:
        """Meta affichée sous la réponse (None : tour sain)."""
        if not self.contamine:
            return None
        return {
            "sources": [lu.en_dict() for lu in self.lectures],
            "bloquees": list(self.bloquees),
            "message": self.raison(),
        }


_courant: ContextVar[Tour | None] = ContextVar("jarvis2_tour", default=None)


@contextlib.contextmanager
def tour(genre: str, ident: str | None = None) -> Iterator[Tour]:
    """Ouvre un tour (variable de contexte) ; il se ferme à la sortie du bloc, contamination comprise."""
    t = Tour(genre, ident)
    jeton = _courant.set(t)
    try:
        yield t
    finally:
        with contextlib.suppress(ValueError):  # générateur fermé depuis un autre contexte : rien à restaurer
            _courant.reset(jeton)


def courant() -> Tour | None:
    return _courant.get()


def marquer(source: str, detail: str = "", tour: Tour | None = None) -> None:
    """Une source de contenu externe vient d'être lue. Hors de tout tour (lecture lancée par l'utilisateur depuis
    l'interface) : rien à faire."""
    cible = tour if tour is not None else _courant.get()
    if cible is not None:
        cible.marquer(source, detail)


def marquer_message(texte: str, tour: Tour | None = None, detail: str = "") -> None:
    """Un message qui porte la balise d'un contenu reçu (partage) : le lire, c'est lire ce contenu."""
    if BALISE_NON_FIABLE in texte:
        marquer("partage", detail, tour)


def agit(action: Action) -> bool:
    """L'action agit-elle (refusée dans un tour contaminé) ? Toute 🟡 🔴, et les 🟢 marquées `ecrit`."""
    return action.niveau != "vert" or action.ecrit


def pilotage_agit(type_action: str) -> bool:
    return type_action not in PILOTAGE_LECTURE


async def _journaliser(conn: Executant, t: Tour, action: str, acteur: str) -> None:
    await audit.journaliser(
        conn,
        acteur=acteur,
        action=ACTION_AUDIT,
        niveau="jaune",
        cible=action,
        details={"tour": t.genre, **({"tour_id": t.ident} if t.ident else {}), "sources": t.sources()},
        resultat="refuse",
    )


async def verifier(conn: Executant, action: Action, libelle: str, acteur: str, tour: Tour | None = None) -> None:
    """Refuse (ErreurAction) une action qui agit dans un tour contaminé ; journalise le refus."""
    t = tour if tour is not None else _courant.get()
    if t is None or not t.contamine or not agit(action):
        return
    t.bloquees.append(libelle)
    await _journaliser(conn, t, action.nom, acteur)
    from .permissions import ErreurAction  # import tardif : permissions importe ce module

    raise ErreurAction(t.raison())


async def bloquer_pilotage(conn: Executant, actions: Sequence[dict[str, Any]], acteur: str = "jarvis") -> int:
    """Propositions du pilotage d'un tour contaminé : celles qui agissent sont marquées `bloquee` (raison) ; jamais
    appliquées seules, le bouton devient « Lancer moi-même ». Renvoie le nombre d'actions bloquées."""
    t = _courant.get()
    if t is None or not t.contamine:
        return 0
    nombre = 0
    for a in actions:
        if pilotage_agit(str(a.get("type"))):
            a["bloquee"] = t.raison()
            t.bloquees.append(str(a.get("libelle") or a.get("type")))
            await _journaliser(conn, t, f"pilotage.{a.get('type')}", acteur)
            nombre += 1
    return nombre


# --- Ateliers (Claude Code) -----------------------------------------------------------------------------------

# Outils de Claude Code qui ramènent du contenu de l'extérieur (le préfixe mcp__ : tout outil MCP, hors celui de
# JARVIS lui-même) ; un Read hors du worktree (accordé par l'utilisateur) est un fichier externe.
OUTILS_EXTERNES: dict[str, str] = {"WebFetch": "web", "WebSearch": "web"}
OUTILS_LECTURE = frozenset({"Read", "Glob", "Grep", "LS", "TodoWrite", "ExitPlanMode", "Task"})
OUTIL_JARVIS = "mcp__jarvis__"


def source_outil(outil: str) -> str | None:
    if outil in OUTILS_EXTERNES:
        return OUTILS_EXTERNES[outil]
    if outil.startswith("mcp__") and not outil.startswith(OUTIL_JARVIS):
        return "mcp"
    return None


def outil_agit(outil: str) -> bool:
    """Outil de Claude Code qui agit : écriture, commande, outil MCP (effet inconnu), et tout outil non listé."""
    return outil not in OUTILS_LECTURE and outil not in OUTILS_EXTERNES


async def refus_outil(conn: Executant, t: Tour, outil: str, acteur: str) -> str | None:
    """Atelier : raison du refus si l'outil agit dans un tour contaminé (journalisé), sinon None."""
    if not t.contamine or not outil_agit(outil):
        return None
    t.bloquees.append(outil)
    await _journaliser(conn, t, f"atelier.{outil}", acteur)
    return t.raison()
