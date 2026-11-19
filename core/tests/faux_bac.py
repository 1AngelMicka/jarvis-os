"""Faux accès au système pour le bac à sable des ateliers : aucune commande réelle n'est jamais lancée."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from jarvis2.ateliers.bac_a_sable import Detecteur


class FauxLanceur:
    """`which` répond selon `outils`, `existe` selon `fichiers` (ou le vrai disque si `disque`), `executer` selon
    `codes` (préfixe de la commande → (code, sortie)) ; chaque appel est noté."""

    def __init__(
        self,
        outils: Sequence[str] = (),
        fichiers: Sequence[str] = (),
        codes: dict[str, tuple[int, str]] | None = None,
        disque: bool = False,
    ) -> None:
        self.outils = set(outils)
        self.fichiers = {str(Path(f)) for f in fichiers}
        self.codes = dict(codes or {})
        self.disque = disque
        self.appels: list[list[str]] = []

    def which(self, nom: str) -> str | None:
        return f"/usr/bin/{nom}" if nom in self.outils else None

    def existe(self, chemin: Path) -> bool:
        return str(Path(chemin)) in self.fichiers or (self.disque and Path(chemin).exists())

    async def executer(self, args: Sequence[str], delai: float) -> tuple[int, str]:
        self.appels.append(list(args))
        ligne = " ".join(args)
        for prefixe, resultat in self.codes.items():
            if ligne.startswith(prefixe):
                return resultat
        return 1, "inconnu"


def lanceur_docker(en_marche: bool = True, image: bool = True) -> FauxLanceur:
    return FauxLanceur(
        outils=["docker"],
        codes={
            "docker info": (0 if en_marche else 1, "27.0.1" if en_marche else "Cannot connect"),
            "docker image inspect": (0 if image else 1, "[]"),
        },
    )


def detecteur_disponible(plateforme: str = "linux") -> Detecteur:
    """Docker en marche avec son image : le bac « auto » est disponible (tests des ateliers sans Docker réel)."""
    return Detecteur(lanceur_docker(), plateforme=plateforme)
