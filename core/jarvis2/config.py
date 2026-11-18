"""Configuration lue dans `.env` (racine du dépôt) et dans l'environnement.

Aucun secret n'a de valeur par défaut : sans `.env`, la connexion à la base échoue avec un message clair.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal
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


def dossier_config() -> Path:
    """Dossier de la configuration locale (même règle que `config_locale.chemin_config`)."""
    if os.environ.get("JARVIS2_CONFIG"):
        return Path(os.environ["JARVIS2_CONFIG"]).parent
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "JARVIS2"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "jarvis2"


class Parametres(BaseSettings):
    # `.env` du dépôt (développement), sinon `jarvis2.env` du dossier de configuration (installation) ; tout est
    # facultatif : sans fichier, JARVIS 2 démarre avec SQLite sur 127.0.0.1:8765.
    model_config = SettingsConfigDict(
        env_file=(dossier_config() / "jarvis2.env", RACINE_DEPOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Stockage : « sqlite » (défaut, aucune installation) ou « postgres ». Vide : PostgreSQL si son mot de passe
    # applicatif est configuré (installation existante), sinon SQLite.
    stockage: str = Field("", alias="JARVIS2_STOCKAGE")
    sqlite: Path | None = Field(None, alias="JARVIS2_SQLITE")  # défaut : <dossier des données>/jarvis2.db

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
    # Ouvrir l'interface dans le navigateur au démarrage (`jarvis2 serveur --ouvrir`, ou `jarvis2` seul)
    ouvrir_navigateur: bool = Field(False, alias="JARVIS2_OUVRIR")
    # Ouvrir le Core au réseau (autre que 127.0.0.1) : choix explicite, jamais par défaut
    ouverture_reseau: bool = Field(False, alias="JARVIS2_OUVERTURE_RESEAU")
    # Origines web supplémentaires autorisées (ex. l'adresse Tailscale du PC), en liste JSON
    origines_supplementaires: list[str] = Field(default_factory=list, alias="JARVIS2_ORIGINES")

    # Moteurs
    moteur_defaut: str = Field("claude_code", alias="JARVIS2_MOTEUR_DEFAUT")
    claude_commande: str = Field("", alias="JARVIS2_CLAUDE_COMMANDE")
    claude_modele: str = Field("claude-sonnet-5-5", alias="JARVIS2_CLAUDE_MODELE")
    claude_effort: str = Field("medium", alias="JARVIS2_CLAUDE_EFFORT")
    ollama_url: str = Field("http://127.0.0.1:11434", alias="JARVIS2_OLLAMA_URL")

    # Mémoire
    modele_embeddings: str = Field(MODELE_EMBEDDINGS, alias="JARVIS2_MODELE_EMBEDDINGS")
    # Voix : modèle Whisper de la transcription locale (tiny, base, small, medium…)
    modele_voix: str = Field("base", alias="JARVIS2_MODELE_VOIX")

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
    def stockage_effectif(self) -> Literal["postgres", "sqlite"]:
        choix = self.stockage.strip().lower()
        if choix in ("postgres", "postgresql"):
            return "postgres"
        if choix == "sqlite":
            return "sqlite"
        if choix:
            raise ValueError(f"JARVIS2_STOCKAGE inconnu : {self.stockage!r} (sqlite ou postgres)")
        return "postgres" if self.app_mot_de_passe.get_secret_value() else "sqlite"

    @property
    def chemin_sqlite(self) -> Path:
        return self.sqlite or self.dossier_donnees / "jarvis2.db"

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
        """Interface compilée : livrée dans le paquet installé (`jarvis2/web`), sinon celle du dépôt."""
        livree = Path(__file__).parent / "web"
        return livree if (livree / "index.html").is_file() else RACINE_DEPOT / "interface" / "dist"


@lru_cache(maxsize=1)
def parametres() -> Parametres:
    return Parametres()
