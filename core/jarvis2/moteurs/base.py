"""Contrat commun des moteurs d'inférence (idée d'OpenJarvis : `InferenceEngine`).

Un moteur sait :
- `generate`    : produire une réponse complète ;
- `stream`      : diffuser la réponse morceau par morceau (`Delta`), puis un `Fin` qui porte la réponse entière ;
- `list_models` : lister ses modèles ;
- `health`      : dire s'il est joignable, sans jamais démarrer de service.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

Role = Literal["systeme", "utilisateur", "assistant"]


class ErreurMoteur(Exception):
    """Erreur d'un moteur, avec un message en français affichable tel quel."""


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    contenu: str


@dataclass(frozen=True, slots=True)
class Options:
    modele: str | None = None
    effort: str | None = None
    temperature: float | None = None


@dataclass(slots=True)
class Usage:
    jetons_entree: int | None = None
    jetons_sortie: int | None = None


@dataclass(slots=True)
class Reponse:
    texte: str
    modele: str | None
    usage: Usage = field(default_factory=Usage)
    cout_usd: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Delta:
    texte: str


@dataclass(frozen=True, slots=True)
class Fin:
    reponse: Reponse


Evenement = Delta | Fin


@dataclass(frozen=True, slots=True)
class InfoModele:
    id: str
    nom: str
    defaut: bool = False


@dataclass(frozen=True, slots=True)
class EtatSante:
    disponible: bool
    detail: str = ""


class Moteur(ABC):
    """Classe de base : chaque moteur s'inscrit avec `@MoteurRegistry.register("<id>")`."""

    id: ClassVar[str]
    nom: ClassVar[str]
    externe: ClassVar[bool] = False  # True : les données quittent le PC (filtre de sécurité en phase 4)
    efforts: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        """Diffuse des `Delta`, puis exactement un `Fin`."""

    async def generate(self, messages: Sequence[Message], options: Options | None = None) -> Reponse:
        """Par défaut : consomme `stream` jusqu'au `Fin`."""
        async for evenement in self.stream(messages, options):
            if isinstance(evenement, Fin):
                return evenement.reponse
        raise ErreurMoteur(f"Le moteur {self.id} n'a pas terminé sa réponse")

    @abstractmethod
    async def list_models(self) -> list[InfoModele]: ...

    @abstractmethod
    async def health(self) -> EtatSante: ...

    async def fermer(self) -> None:  # noqa: B027 — crochet facultatif
        """Libère les ressources (clients HTTP…)."""
