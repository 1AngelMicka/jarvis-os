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
from typing import Any, Literal

Role = Literal["systeme", "utilisateur", "assistant"]


class ErreurMoteur(Exception):
    """Erreur d'un moteur, avec un message en français affichable tel quel."""


@dataclass(frozen=True, slots=True)
class Image:
    """Image jointe par l'utilisateur, gardée en mémoire le temps de la réponse seulement (jamais en base)."""

    type_mime: str  # image/jpeg | image/png | image/webp | image/gif
    donnees: bytes

    @property
    def extension(self) -> str:
        return {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(
            self.type_mime, "bin"
        )

    def base64(self) -> str:
        import base64

        return base64.b64encode(self.donnees).decode("ascii")

    def data_url(self) -> str:
        return f"data:{self.type_mime};base64,{self.base64()}"


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    contenu: str
    images: tuple[Image, ...] = ()  # seulement sur le dernier message de l'utilisateur


@dataclass(frozen=True, slots=True)
class Options:
    modele: str | None = None
    effort: str | None = None
    temperature: float | None = None
    rapide: bool = False  # petite tâche utilitaire (titre, résumé) : pas de réflexion longue, réponse courte
    route: str | None = None  # type de tâche choisi par le routeur (routage.py) : noté dans la télémétrie


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
    installe: bool = True  # le programme ou le service existe sur ce PC
    connecte: bool | None = None  # compte connecté / clé valide (None : sans objet)


Famille = Literal["cli", "api", "local"]


class Moteur(ABC):
    """Classe de base d'un connecteur d'IA. Les attributs peuvent être redéfinis par instance : une même classe
    (ex. compatible OpenAI) sert plusieurs connecteurs (OpenAI, OpenRouter, LM Studio…)."""

    id: str
    nom: str
    famille: Famille = "local"
    externe: bool = False  # True : les données quittent le PC (filtre de sécurité, souvenirs privés exclus)
    risque: bool = False  # conditions du fournisseur défavorables : jamais choisi par le routeur
    actif_par_defaut: bool = True
    installation_url: str | None = None  # « Comment installer »
    conditions_url: str | None = None
    efforts: tuple[str, ...] = ()
    vision: bool = False  # sait lire les images jointes (sinon : message clair, rien n'est envoyé)

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
