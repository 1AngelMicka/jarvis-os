"""Point d'entrée : `python -m jarvis2 <commande>`.

- `migrer`  : applique les migrations (rôle propriétaire)
- `serveur` : lance le Core sur JARVIS2_HOTE:JARVIS2_PORT (127.0.0.1:8765 par défaut)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .config import parametres
from .db import appliquer_migrations
from .journal import configurer_journal

journal = logging.getLogger("jarvis2")


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(prog="jarvis2", description="JARVIS 2 — Core")
    sous = analyseur.add_subparsers(dest="commande", required=True)
    m = sous.add_parser("migrer", help="appliquer les migrations")
    m.add_argument("--base", help="base cible (défaut : POSTGRES_DB)")
    sous.add_parser("serveur", help="lancer le Core")
    args = analyseur.parse_args(argv)

    p = parametres()
    configurer_journal(p.niveau_journal, p.dossier_journaux)

    if args.commande == "migrer":
        appliquees = asyncio.run(appliquer_migrations(p.url_base("proprio", args.base)))
        journal.info("Migrations appliquées : %s", ", ".join(appliquees) or "aucune (déjà à jour)")
        return 0

    if args.commande == "serveur":
        import uvicorn

        from .api import creer_app

        if p.hote not in ("127.0.0.1", "localhost", "::1"):
            journal.error("Refusé : sans authentification (phase 4), le Core n'écoute que sur 127.0.0.1")
            return 2
        uvicorn.run(creer_app(p), host=p.hote, port=p.port, log_config=None, access_log=False)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
