"""Journalisation : console + fichier tournant dans le dossier des données, avec masquage des secrets."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

FORMAT = "%(asctime)s %(levelname)-7s %(name)s : %(message)s"

# Formes de secrets courantes : jamais écrites en clair dans un journal.
MOTIFS_SECRETS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),  # clés de type OpenAI / Anthropic / OpenRouter
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),  # clés Google
    re.compile(r"(?i)(postgres(?:ql)?://[^:\s/]+:)[^@\s]+(@)"),  # mot de passe dans une URL de base
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-]{16,}"),
)


def masquer(texte: str) -> str:
    for motif in MOTIFS_SECRETS:
        if motif.groups >= 2:
            texte = motif.sub(r"\1***\2", texte)
        elif motif.groups == 1:
            texte = motif.sub(r"\1***", texte)
        else:
            texte = motif.sub("***", texte)
    return texte


class FiltreSecrets(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        masque = masquer(message)
        if masque != message:
            record.msg, record.args = masque, None
        return True


def configurer_journal(niveau: str = "INFO", dossier: Path | None = None) -> None:
    racine = logging.getLogger()
    racine.setLevel(niveau.upper())
    for gestionnaire in list(racine.handlers):
        racine.removeHandler(gestionnaire)
    filtre = FiltreSecrets()
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(FORMAT))
    console.addFilter(filtre)
    racine.addHandler(console)
    if dossier is not None:
        dossier.mkdir(parents=True, exist_ok=True)
        fichier = RotatingFileHandler(dossier / "jarvis2.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
        fichier.setFormatter(logging.Formatter(FORMAT))
        fichier.addFilter(filtre)
        racine.addHandler(fichier)
