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

    sources: tuple[re.Pattern[str], ...] = ()  # source du souvenir (ex. « doc:export-messagerie.json »)
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
    # Connecteurs d'IA : réglages par connecteur ([connecteurs.<id>]) et points d'accès compatibles OpenAI
    # supplémentaires ([[connecteurs.compatibles]] : id, nom, url, local, cle)
    connecteurs: dict[str, dict[str, Any]] = field(default_factory=dict)
    compatibles: tuple[dict[str, Any], ...] = ()
    # Tarifs ($ par million de jetons, entrée et sortie) pour estimer le coût des API sans coût renvoyé
    tarifs: dict[str, tuple[float, float]] = field(default_factory=dict)
    # Sujets PRIVÉS : un message qui les nomme est confié à une IA locale par le routeur (rien ne sort du PC)
    sujets_prives: tuple[re.Pattern[str], ...] = ()
    # Serveurs MCP ([[mcp.serveurs]] : id, commande, args, env, outils autorisés)
    serveurs_mcp: tuple[dict[str, Any], ...] = ()
    # Recherche web privée : adresse d'une instance SearXNG ([recherche] searxng = "http://…")
    searxng: str | None = None
    # Projets ouverts aux ateliers Claude Code ([[ateliers.projets]] : id, nom, chemin d'un dépôt git)
    projets_ateliers: tuple[dict[str, Any], ...] = ()
    # Accueil du matin ([matin] : ville, ou latitude et longitude) : lieu PRIVÉ, jamais lu à voix haute
    matin: dict[str, Any] = field(default_factory=dict)

    def connecteur(self, ident: str) -> dict[str, Any]:
        return self.connecteurs.get(ident, {})

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
    blocs = dict(donnees.get("connecteurs") or {})
    compatibles = blocs.pop("compatibles", [])
    if not isinstance(compatibles, list) or not all(
        isinstance(c, dict) and {"id", "nom", "url"} <= set(c) for c in compatibles
    ):
        raise ValueError("connecteurs.compatibles : liste de tables avec id, nom et url attendue")
    tarifs: dict[str, tuple[float, float]] = {}
    for modele, prix in (donnees.get("tarifs") or {}).items():
        if not (isinstance(prix, list) and len(prix) == 2 and all(isinstance(x, int | float) for x in prix)):
            raise ValueError(f"tarifs.{modele} : [prix entrée, prix sortie] en $ par million de jetons attendu")
        tarifs[str(modele)] = (float(prix[0]), float(prix[1]))
    serveurs = (donnees.get("mcp") or {}).get("serveurs") or []
    if not isinstance(serveurs, list) or not all(
        isinstance(s, dict) and {"id", "commande"} <= set(s) for s in serveurs
    ):
        raise ValueError("mcp.serveurs : liste de tables avec id et commande attendue")
    searxng = (donnees.get("recherche") or {}).get("searxng")
    if searxng is not None and not (isinstance(searxng, str) and searxng.startswith(("http://", "https://"))):
        raise ValueError("recherche.searxng : adresse http(s) attendue")
    return ConfigLocale(
        chemin=chemin,
        sujets_exclus=_motifs(confidentialite.get("sujets_exclus"), "confidentialite.sujets_exclus"),
        imports=imports,
        connecteurs={str(k): dict(v) for k, v in blocs.items() if isinstance(v, dict)},
        compatibles=tuple(compatibles),
        tarifs=tarifs,
        sujets_prives=_motifs(confidentialite.get("sujets_prives"), "confidentialite.sujets_prives"),
        serveurs_mcp=tuple(serveurs),
        searxng=searxng.rstrip("/") if searxng else None,
        projets_ateliers=tuple(p for p in (donnees.get("ateliers") or {}).get("projets") or [] if isinstance(p, dict)),
        matin=dict(donnees.get("matin") or {}),
    )


def charger(chemin: Path | None = None) -> ConfigLocale:
    chemin = chemin or chemin_config()
    if not chemin.is_file():
        return ConfigLocale()
    with chemin.open("rb") as f:
        config = analyser(tomllib.load(f), chemin)
    journal.info("Configuration locale : %s", chemin)
    return config
