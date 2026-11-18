"""Crée `.env` à partir de `.env.example` avec des mots de passe aléatoires, sans rien afficher.

Usage : uv run --python 3.13 infra/creer_env.py
Ne remplace jamais un `.env` existant.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
A_GENERER = ("POSTGRES_PASSWORD", "JARVIS2_APP_MOT_DE_PASSE")


def main() -> int:
    cible = RACINE / ".env"
    if cible.exists():
        print(".env existe déjà : rien n'a été modifié.")
        return 0
    lignes = []
    for ligne in (RACINE / ".env.example").read_text(encoding="utf-8").splitlines():
        cle = ligne.split("=", 1)[0]
        if cle in A_GENERER:
            ligne = f"{cle}={secrets.token_urlsafe(32)}"
        lignes.append(ligne)
    cible.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    print(".env créé (mots de passe générés, non affichés).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
