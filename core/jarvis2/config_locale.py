"""Configuration locale de l'utilisateur, **hors du dépôt** : tout ce qui est personnel vit ici.

Fichier TOML lu à cet endroit (le premier trouvé) :
- `JARVIS2_CONFIG` (variable d'environnement) ;
- Windows : `%APPDATA%\\JARVIS2\\config.toml` ;
- ailleurs : `$XDG_CONFIG_HOME/jarvis2/config.toml` (par défaut `~/.config/jarvis2/config.toml`).

Exemple commenté : `config.exemple.toml` à la racine du dépôt. Sans fichier, tout fonctionne avec des listes vides.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

journal = logging.getLogger("jarvis2.config_locale")


def chemin_config() -> Path:
    if os.environ.get("JARVIS2_CONFIG"):
        return Path(os.environ["JARVIS2_CONFIG"])
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "JARVIS2" / "config.toml"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "jarvis2" / "config.toml"


def _motifs(valeurs: Any, cle: str) -> tuple[re.Pattern[str], ...]:
    if valeurs is None:
        return ()
    if not isinstance(valeurs, list) or not all(isinstance(v, str) for v in valeurs):
        raise ValueError(f"{cle} : liste d'expressions régulières attendue")
    try:
        return tuple(re.compile(v, re.IGNORECASE) for v in valeurs)
    except re.error as exc:
        raise ValueError(f"{cle} : expression invalide ({exc})") from exc


@dataclass(frozen=True)
class ExclusionsImport:
    """Ce qu'un import ne doit jamais faire entrer en mémoire (données de tiers, sujets exclus…)."""

    sources: tuple[re.Pattern[str], ...] = ()  # source du souvenir (ex. « doc:export-tiers.jsonl »)
    contenus: tuple[re.Pattern[str], ...] = ()  # contenu d'un souvenir ou d'un message

    def exclut(self, source: str | None, contenu: str | None) -> bool:
        return any(m.search(source or "") for m in self.sources) or any(m.search(contenu or "") for m in self.contenus)


@dataclass(frozen=True)
class ConfigImport:
    exclusions: ExclusionsImport = field(default_factory=ExclusionsImport)
    requetes_temoins: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConfigLocale:
    chemin: Path | None = None
    # Sujets que JARVIS ne doit jamais aborder : toute phrase qui les nomme est retirée des textes de mémoire
    # injectés au modèle (noyau, souvenirs). Les garde-fous d'action relèvent de la sécurité (phase 4).
    sujets_exclus: tuple[re.Pattern[str], ...] = ()
    imports: dict[str, ConfigImport] = field(default_factory=dict)

    def import_(self, source: str) -> ConfigImport:
        return self.imports.get(source, ConfigImport())


def analyser(donnees: dict[str, Any], chemin: Path | None = None) -> ConfigLocale:
    confidentialite = donnees.get("confidentialite", {})
    imports: dict[str, ConfigImport] = {}
    for nom, bloc in (donnees.get("import") or {}).items():
        exclusions = ExclusionsImport(
            sources=_motifs(bloc.get("exclure_sources"), f"import.{nom}.exclure_sources"),
            contenus=_motifs(bloc.get("exclure_contenus"), f"import.{nom}.exclure_contenus"),
        )
        temoins = bloc.get("requetes_temoins") or []
        if not isinstance(temoins, list) or not all(isinstance(q, str) for q in temoins):
            raise ValueError(f"import.{nom}.requetes_temoins : liste de textes attendue")
        imports[nom] = ConfigImport(exclusions, tuple(temoins))
    return ConfigLocale(
        chemin=chemin,
        sujets_exclus=_motifs(confidentialite.get("sujets_exclus"), "confidentialite.sujets_exclus"),
        imports=imports,
    )


def charger(chemin: Path | None = None) -> ConfigLocale:
    chemin = chemin or chemin_config()
    if not chemin.is_file():
        return ConfigLocale()
    with chemin.open("rb") as f:
        config = analyser(tomllib.load(f), chemin)
    journal.info("Configuration locale : %s", chemin)
    return config
