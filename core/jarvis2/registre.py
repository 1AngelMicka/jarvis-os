"""Registres à décorateur (idée d'OpenJarvis : `RegistryBase`).

Chaque sous-classe a son propre stockage : un enregistrement dans un registre ne fuit jamais dans un autre.

    @MoteurRegistry.register("ollama")
    class MoteurOllama(Moteur): ...

    MoteurRegistry.create("ollama", url=...)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from .moteurs.base import Moteur


class RegistryBase[T]:
    _entrees: ClassVar[dict[str, Any]]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._entrees = {}

    @classmethod
    def register(cls, cle: str) -> Callable[[T], T]:
        def decorateur(entree: T) -> T:
            if cle in cls._entrees:
                raise ValueError(f"{cls.__name__} a déjà une entrée « {cle} »")
            cls._entrees[cle] = entree
            return entree

        return decorateur

    @classmethod
    def get(cls, cle: str) -> T:
        try:
            entree: T = cls._entrees[cle]
        except KeyError as exc:
            raise KeyError(f"{cls.__name__} n'a pas d'entrée « {cle} »") from exc
        return entree

    @classmethod
    def create(cls, cle: str, *args: Any, **kwargs: Any) -> Any:
        entree = cls.get(cle)
        if not callable(entree):
            raise TypeError(f"L'entrée « {cle} » de {cls.__name__} n'est pas instanciable")
        return entree(*args, **kwargs)

    @classmethod
    def keys(cls) -> tuple[str, ...]:
        return tuple(cls._entrees)

    @classmethod
    def contains(cls, cle: str) -> bool:
        return cle in cls._entrees

    @classmethod
    def unregister(cls, cle: str) -> None:
        cls._entrees.pop(cle, None)


class MoteurRegistry(RegistryBase[type["Moteur"]]):
    """Moteurs d'inférence interchangeables (claude_code, ollama…)."""
