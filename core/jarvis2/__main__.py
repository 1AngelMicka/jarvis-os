"""Point d'entrée : `python -m jarvis2 <commande>`.

- `migrer`  : applique les migrations (rôle propriétaire)
- `serveur` : lance le Core sur JARVIS2_HOTE:JARVIS2_PORT (127.0.0.1:8765 par défaut)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .config import Parametres, parametres
from .config_locale import charger as charger_config_locale
from .db import appliquer_migrations
from .importeurs import SOURCES
from .journal import configurer_journal

journal = logging.getLogger("jarvis2")


async def _jumeler(p: Parametres, adresse: str | None) -> int:
    from .db import creer_pool
    from .securite import appareils, audit

    pool = await creer_pool(p.url_base("app"), max_size=1)
    try:
        code, expire = await appareils.creer_jumelage(pool, None, "navigateur")
        await audit.journaliser(pool, acteur="cli", action="jumelage.cree", details={"type": "navigateur"})
    finally:
        await pool.close()
    base = (adresse or f"http://localhost:{p.port}").rstrip("/")
    print(f"Ouvrez cette adresse sur l'appareil à associer (une seule fois, avant {expire:%H:%M:%S} UTC) :")
    print(f"{base}/#jumeler={code}")
    return 0


async def _verifier_audit(p: Parametres) -> int:
    from .db import creer_pool
    from .securite import audit

    pool = await creer_pool(p.url_base("app"), max_size=1)
    try:
        rompue = await audit.verifier(pool)
        total = await pool.fetchval("SELECT count(*) FROM audit")
    finally:
        await pool.close()
    if rompue is None:
        print(f"Journal d'audit intact : {total} entrées, chaîne d'empreintes vérifiée.")
        return 0
    print(f"ALTÉRATION du journal d'audit détectée à l'entrée {rompue}.")
    return 3


async def _lever_urgence(p: Parametres) -> int:
    """Secours local : exige les identifiants du PROPRIÉTAIRE de la base (fichier .env du PC), journalisé 🔴.

    Le Core en marche garde l'état en mémoire : le redémarrer après cette commande.
    """
    import asyncpg

    from .securite import audit
    from .securite.urgence import ArretUrgence

    conn = await asyncpg.connect(p.url_base("proprio"))
    try:
        urgence = ArretUrgence()
        await urgence.charger(conn)
        if not urgence.actif:
            print("L'arrêt d'urgence n'est pas actif.")
            return 0
        await urgence.lever(conn)
        await audit.journaliser(conn, acteur="cli:proprietaire", action="urgence.levee_secours", niveau="rouge")
    finally:
        await conn.close()
    print("Arrêt d'urgence levé (journalisé). Redémarrez le Core pour qu'il le prenne en compte.")
    return 0


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(prog="jarvis2", description="JARVIS 2 — Core")
    sous = analyseur.add_subparsers(dest="commande", required=True)
    m = sous.add_parser("migrer", help="appliquer les migrations")
    m.add_argument("--base", help="base cible (défaut : POSTGRES_DB)")
    sous.add_parser("serveur", help="lancer le Core")
    imp = sous.add_parser("importer", help="importer les données d'une autre source (lecture seule côté source)")
    imp.add_argument("source", choices=sorted(SOURCES), help="source d'import")
    imp.add_argument("--sauvegarde", type=Path, help="sauvegarde de la source (jarvis_v1 : pg_dump -Fc)")
    jum = sous.add_parser("jumeler", help="code de jumelage à usage unique (5 min) pour un nouvel appareil")
    jum.add_argument("--adresse", default=None, help="adresse de l'interface (défaut : http://localhost:<port>)")
    sous.add_parser("verifier-audit", help="vérifier la chaîne d'empreintes du journal d'audit")
    sous.add_parser(
        "lever-urgence", help="secours de l'administrateur du PC (clé d'accès perdue) : lever l'arrêt d'urgence"
    )
    ver = sous.add_parser("verifier-import", help="même modèle d'embeddings et mêmes résultats de recherche")
    ver.add_argument("source", choices=sorted(SOURCES), help="source d'import")
    args = analyseur.parse_args(argv)

    p = parametres()
    configurer_journal(p.niveau_journal, p.dossier_journaux)

    if args.commande == "migrer":
        appliquees = asyncio.run(appliquer_migrations(p.url_base("proprio", args.base)))
        journal.info("Migrations appliquées : %s", ", ".join(appliquees) or "aucune (déjà à jour)")
        return 0

    if args.commande == "importer":
        module = SOURCES[args.source]
        locale = charger_config_locale().import_(args.source)
        if args.sauvegarde:
            if not args.sauvegarde.is_file():
                journal.error("Sauvegarde introuvable : %s", args.sauvegarde)
                return 2
            module.restaurer_sauvegarde(args.sauvegarde, p.conteneur_pg, p.postgres_user)
            source, empreinte = args.sauvegarde.name, module.empreinte(args.sauvegarde)
        else:
            source, empreinte = "base d'attente existante", "-"
        asyncio.run(appliquer_migrations(p.url_base("proprio")))
        rapport = asyncio.run(
            module.importer(
                p.url_base("proprio", module.BASE_ATTENTE), p.url_base("app"), source, empreinte, locale.exclusions
            )
        )
        print(rapport.texte())
        return 0 if rapport.complet else 3

    if args.commande == "verifier-import":
        from .embeddings import EncodeurFastEmbed

        module = SOURCES[args.source]
        locale = charger_config_locale().import_(args.source)
        encodeur = EncodeurFastEmbed(p.dossier_modeles, p.modele_embeddings)
        verification = asyncio.run(
            module.verifier(
                p.url_base("proprio", module.BASE_ATTENTE), p.url_base("app"), encodeur, locale.requetes_temoins
            )
        )
        print(verification.texte())
        return 0 if verification.vecteurs_identiques and verification.recherches_identiques else 3

    if args.commande == "jumeler":
        return asyncio.run(_jumeler(p, args.adresse))

    if args.commande == "verifier-audit":
        return asyncio.run(_verifier_audit(p))

    if args.commande == "lever-urgence":
        return asyncio.run(_lever_urgence(p))

    if args.commande == "serveur":
        import uvicorn

        from .api import creer_app

        if p.hote not in ("127.0.0.1", "localhost", "::1") and not p.ouverture_reseau:
            journal.error("Refusé : le Core n'écoute que sur 127.0.0.1, sauf JARVIS2_OUVERTURE_RESEAU=true")
            return 2
        uvicorn.run(creer_app(p), host=p.hote, port=p.port, log_config=None, access_log=False)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
