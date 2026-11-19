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


_MODELES_AJOUTES = False


def _ajouter_modeles(text_embedding: Any) -> None:
    """Modèles absents du catalogue de fastembed mais proposés par JARVIS (export ONNX officiel du modèle)."""
    global _MODELES_AJOUTES
    if _MODELES_AJOUTES:
        return
    from fastembed.common.model_description import ModelSource, PoolingType

    connus = {m["model"] for m in text_embedding.list_supported_models()}
    if "BAAI/bge-m3" not in connus:
        text_embedding.add_custom_model(
            model="BAAI/bge-m3",
            pooling=PoolingType.CLS,
            normalization=True,
            sources=ModelSource(hf="BAAI/bge-m3"),
            dim=1024,
            model_file="onnx/model.onnx",
            additional_files=["onnx/model.onnx_data"],
            description="Multilingue, 1024 dimensions (8192 jetons)",
            license="mit",
            size_in_gb=2.27,
        )
    _MODELES_AJOUTES = True


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

                from .telechargements import ModeleAbsent, dossier_embeddings, est_pret

                _ajouter_modeles(TextEmbedding)
                propre = dossier_embeddings(self.dossier_cache, self.nom_modele)
                journal.info("Chargement du modèle d'embeddings %s…", self.nom_modele)
                if est_pret(propre):  # téléchargé par jarvis2.telechargements
                    self._modele = TextEmbedding(
                        self.nom_modele, cache_dir=str(self.dossier_cache), specific_model_path=str(propre)
                    )
                else:  # ancien cache fastembed (installations antérieures) ; jamais de téléchargement implicite
                    try:
                        self._modele = TextEmbedding(
                            self.nom_modele, cache_dir=str(self.dossier_cache), local_files_only=True
                        )
                    except Exception as exc:
                        raise ModeleAbsent(
                            f"Modèle d'embeddings {self.nom_modele} non téléchargé : acceptez son téléchargement "
                            "(page Mémoire ou diagnostic, ou `jarvis2 docteur --reparer`)"
                        ) from exc
            return self._modele

    def present(self) -> bool:
        """Modèle sur le disque (téléchargé par JARVIS ou ancien cache), sans rien télécharger."""
        from .diagnostic import modele_present
        from .telechargements import dossier_embeddings, est_pret

        return est_pret(dossier_embeddings(self.dossier_cache, self.nom_modele)) or modele_present(
            self.dossier_cache, self.nom_modele
        )

    def encoder_sync(self, texte: str) -> list[float]:
        vecteur = next(iter(self._charger().embed([texte])))
        return [float(x) for x in vecteur]

    async def encoder(self, texte: str) -> list[float]:
        return await asyncio.to_thread(self.encoder_sync, texte)


def vecteur_sql(vecteur: list[float]) -> str:
    """Littéral `vector` de pgvector : « [0.1,0.2,…] »."""
    return "[" + ",".join(f"{x:.7g}" for x in vecteur) + "]"
