"""Embeddings locaux : fastembed. Modèle par défaut : le même que JARVIS v1 (vecteurs importés tels quels).

Le modèle est chargé à la première demande (≈ 2 s), dans un fil à part pour ne pas bloquer le serveur, et mis en
cache dans le dossier des données. Les vecteurs importés de JARVIS v1 sont donc directement comparables aux nouveaux.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from pathlib import Path
from typing import Any, Protocol

from .config import MODELE_EMBEDDINGS

journal = logging.getLogger("jarvis2.embeddings")


class Encodeur(Protocol):
    """Tout encodeur dit quel modèle il est : chaque vecteur stocké garde le nom de son modèle."""

    @property
    def nom_modele(self) -> str: ...

    async def encoder(self, texte: str) -> list[float]: ...


class EncodeurFastEmbed:
    def __init__(self, dossier_cache: Path, nom_modele: str = MODELE_EMBEDDINGS) -> None:
        self.dossier_cache = dossier_cache
        self.nom_modele = nom_modele
        self._modele: Any = None
        self._verrou = threading.Lock()

    def _charger(self) -> Any:
        with self._verrou:
            if self._modele is None:
                # Sans liens symboliques (Windows, exFAT) le cache reste fonctionnel : avertissement inutile
                os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
                from fastembed import TextEmbedding

                self.dossier_cache.mkdir(parents=True, exist_ok=True)
                journal.info("Chargement du modèle d'embeddings %s…", self.nom_modele)
                self._modele = TextEmbedding(self.nom_modele, cache_dir=str(self.dossier_cache))
            return self._modele

    def encoder_sync(self, texte: str) -> list[float]:
        vecteur = next(iter(self._charger().embed([texte])))
        return [float(x) for x in vecteur]

    async def encoder(self, texte: str) -> list[float]:
        return await asyncio.to_thread(self.encoder_sync, texte)


def vecteur_sql(vecteur: list[float]) -> str:
    """Littéral `vector` de pgvector : « [0.1,0.2,…] »."""
    return "[" + ",".join(f"{x:.7g}" for x in vecteur) + "]"
