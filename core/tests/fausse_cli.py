"""Fausse CLI d'IA (Codex ou Antigravity) pour les tests : rejoue un flux JSONL enregistré et note son appel.

Variables : FAUSSE_CLI_FLUX (fichier .jsonl à rejouer), FAUSSE_CLI_NOTE (fichier où écrire un compte rendu JSON :
arguments, dossier de travail et son contenu, variables sensibles présentes, entrée standard reçue).
`login status` / `--version` / `models` répondent comme la vraie CLI ; FAUSSE_CLI_DECONNECTE=1 simule un compte
non connecté.
"""

from __future__ import annotations

import json
import os
import sys

SENSIBLES = ("OPENAI_API_KEY", "CODEX_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "DATABASE_URL")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # comme les vraies CLI
    args = sys.argv[1:]
    if args[:2] == ["login", "status"]:
        if os.environ.get("FAUSSE_CLI_DECONNECTE"):
            print("Not logged in")
            return 1
        print("Logged in using ChatGPT")
        return 0
    if args == ["--version"]:
        print("9.9.9")
        return 0
    if args == ["models"]:
        print("Modèles disponibles :\n  gemini-3.8-pro   (défaut)\n  gemini-3.8-flash")
        return 0
    entree = sys.stdin.read()
    note = os.environ.get("FAUSSE_CLI_NOTE")
    if note:
        with open(note, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "args": args,
                    "cwd": os.getcwd(),
                    "contenu_cwd": os.listdir("."),
                    "sensibles": [k for k in SENSIBLES if k in os.environ],
                    "entree": entree,
                },
                f,
            )
    with open(os.environ["FAUSSE_CLI_FLUX"], encoding="utf-8") as f:
        for ligne in f:
            sys.stdout.write(ligne)
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
