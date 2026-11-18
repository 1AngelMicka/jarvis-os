"""Configuration lue dans `.env` (racine du dépôt) et dans l'environnement.

Aucun secret n'a de valeur par défaut : sans `.env`, la connexion à la base échoue avec un message clair.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

RACINE_DEPOT = Path(__file__).resolve().parents[2]


def dossier_donnees_defaut() -> Path:
    """Dossier des données lourdes (journaux, modèles, imports) ; déplaçable par JARVIS2_DOSSIER_DONNEES."""
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "JARVIS2"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "jarvis2"


MODELE_EMBEDDINGS = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class Parametres(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=RACINE_DEPOT / ".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    # PostgreSQL
    postgres_user: str = Field("jarvis2_proprio", alias="POSTGRES_USER")
    postgres_password: SecretStr = Field(SecretStr(""), alias="POSTGRES_PASSWORD")
    postgres_db: str = Field("jarvis2", alias="POSTGRES_DB")
    pg_hote: str = Field("127.0.0.1", alias="JARVIS2_PG_HOTE")
    pg_port: int = Field(5433, alias="JARVIS2_PG_PORT")
    app_mot_de_passe: SecretStr = Field(SecretStr(""), alias="JARVIS2_APP_MOT_DE_PASSE")
    conteneur_pg: str = Field("jarvis2-postgres", alias="JARVIS2_CONTENEUR_PG")

    # Core
    hote: str = Field("127.0.0.1", alias="JARVIS2_HOTE")
    port: int = Field(8765, alias="JARVIS2_PORT")
    dossier_donnees: Path = Field(default_factory=lambda: dossier_donnees_defaut(), alias="JARVIS2_DOSSIER_DONNEES")
    niveau_journal: str = Field("INFO", alias="JARVIS2_NIVEAU_JOURNAL")

    # Moteurs
    moteur_defaut: str = Field("claude_code", alias="JARVIS2_MOTEUR_DEFAUT")
    claude_commande: str = Field("", alias="JARVIS2_CLAUDE_COMMANDE")
    claude_modele: str = Field("claude-sonnet-5-5", alias="JARVIS2_CLAUDE_MODELE")
    claude_effort: str = Field("medium", alias="JARVIS2_CLAUDE_EFFORT")
    ollama_url: str = Field("http://127.0.0.1:11434", alias="JARVIS2_OLLAMA_URL")

    # Mémoire
    modele_embeddings: str = Field(MODELE_EMBEDDINGS, alias="JARVIS2_MODELE_EMBEDDINGS")

    def url_base(self, role: str = "app", base: str | None = None) -> str:
        """URL de connexion : `role` = « app » (Core) ou « proprio » (migrations uniquement)."""
        if role == "proprio":
            utilisateur, mdp = self.postgres_user, self.postgres_password.get_secret_value()
        elif role == "app":
            utilisateur, mdp = "jarvis2_app", self.app_mot_de_passe.get_secret_value()
        else:
            raise ValueError(f"Rôle de base inconnu : {role}")
        if not mdp:
            raise RuntimeError("Mot de passe de la base absent : créer .env (python infra/creer_env.py)")
        return (
            f"postgresql://{quote(utilisateur)}:{quote(mdp, safe='')}@{self.pg_hote}:{self.pg_port}/"
            f"{base or self.postgres_db}"
        )

    @property
    def dossier_journaux(self) -> Path:
        return self.dossier_donnees / "journaux"

    @property
    def dossier_modeles(self) -> Path:
        """Cache des modèles d'embeddings (fastembed), dans le dossier des données."""
        return self.dossier_donnees / "modeles"

    @property
    def dossier_claude_vide(self) -> Path:
        """Dossier de travail vide de la CLI claude : elle n'y trouve aucun projet ni fichier."""
        return self.dossier_donnees / "claude-vide"

    @property
    def dossier_interface(self) -> Path:
        return RACINE_DEPOT / "interface" / "dist"


@lru_cache(maxsize=1)
def parametres() -> Parametres:
    return Parametres()
