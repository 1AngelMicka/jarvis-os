"""Point d'entrée : `jarvis2 <commande>` (ou `python -m jarvis2 <commande>`).

- `migrer`  : applique les migrations du stockage choisi (SQLite par défaut, PostgreSQL en option)
- `serveur` : lance le Core sur JARVIS2_HOTE:JARVIS2_PORT (127.0.0.1:8765 par défaut) ; `--sans-ecran` pour un
  serveur domestique (capture, clics et contrôle de l'écran refusés, voix par le micro du navigateur)
"""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

from .config import Parametres, parametres
from .config_locale import charger as charger_config_locale
from .db import Base, Executant, migrer, ouvrir_base
from .importeurs import SOURCES
from .journal import configurer_journal

journal = logging.getLogger("jarvis2")


@asynccontextmanager
async def _base(p: Parametres) -> AsyncIterator[Base]:
    base = await ouvrir_base(p, max_size=1)
    try:
        yield base
    finally:
        await base.close()


async def _jumeler(p: Parametres, adresse: str | None) -> int:
    from .securite import appareils, audit

    async with _base(p) as base:
        code, expire = await appareils.creer_jumelage(base, None, "navigateur")
        await audit.journaliser(base, acteur="cli", action="jumelage.cree", details={"type": "navigateur"})
    adresse_base = (adresse or f"http://localhost:{p.port}").rstrip("/")
    print(f"Ouvrez cette adresse sur l'appareil à associer (une seule fois, avant {expire:%H:%M:%S} UTC) :")
    print(f"{adresse_base}/#jumeler={code}")
    return 0


async def _verifier_audit(p: Parametres) -> int:
    from .securite import audit

    async with _base(p) as base:
        rompue = await audit.verifier(base)
        total = await base.fetchval("SELECT count(*) FROM audit")
    if rompue is None:
        print(f"Journal d'audit intact : {total} entrées, chaîne d'empreintes vérifiée.")
        return 0
    print(f"ALTÉRATION du journal d'audit détectée à l'entrée {rompue}.")
    return 3


async def _lever_urgence(p: Parametres) -> int:
    """Secours local, journalisé 🔴. PostgreSQL : exige les identifiants du PROPRIÉTAIRE de la base (`.env` du PC).
    SQLite : exige l'accès au fichier de la base, donc à la session de l'utilisateur sur le PC.

    Le Core en marche garde l'état en mémoire : le redémarrer après cette commande.
    """
    from .securite import audit
    from .securite.urgence import ArretUrgence

    acces: AbstractAsyncContextManager[Executant]
    if p.stockage_effectif == "postgres":
        from .db_postgres import connexion_directe

        acces = connexion_directe(p.url_base("proprio"))
    else:
        acces = _base(p)
    async with acces as conn:
        urgence = ArretUrgence()
        await urgence.charger(conn)
        if not urgence.actif:
            print("L'arrêt d'urgence n'est pas actif.")
            return 0
        await urgence.lever(conn)
        await audit.journaliser(conn, acteur="cli:proprietaire", action="urgence.levee_secours", niveau="rouge")
    print("Arrêt d'urgence levé (journalisé). Redémarrez le Core pour qu'il le prenne en compte.")
    return 0


async def _copier_stockage(p: Parametres, vers: str, fichier: Path | None) -> int:
    """Copie le stockage PostgreSQL vers SQLite, ou l'inverse (cible migrée puis vérifiée vide)."""
    from .db_postgres import BasePostgres, creer_pool
    from .db_postgres import appliquer_migrations as migrer_pg
    from .db_sqlite import BaseSQLite
    from .db_sqlite import appliquer_migrations as migrer_sqlite
    from .stockage_copie import ErreurCopie, copier

    chemin = fichier or p.chemin_sqlite
    if vers == "sqlite":
        await migrer_sqlite(chemin)
        source: Base = BasePostgres(await creer_pool(p.url_base("app"), max_size=2))
        cible: Base = await BaseSQLite.ouvrir(chemin)
    else:
        await migrer_pg(p.url_base("proprio"))
        source = await BaseSQLite.ouvrir(chemin)
        cible = BasePostgres(await creer_pool(p.url_base("proprio"), max_size=2))
    try:
        rapport = await copier(source, cible)
    except ErreurCopie as exc:
        journal.error("%s", exc)
        return 2
    finally:
        await source.close()
        await cible.close()
    print(rapport.texte())
    if rapport.complet:
        print(
            f"Pour utiliser ce stockage : JARVIS2_STOCKAGE={vers}"
            + (f" (fichier {chemin})" if vers == "sqlite" else "")
        )
    return 0 if rapport.complet else 3


async def _docteur(p: Parametres, en_json: bool, reparer: bool, latence: bool = False) -> int:
    """Diagnostic de l'installation ; `--reparer` applique les réparations sûres (schéma SQLite, modèle)."""
    import contextlib
    import json

    import httpx

    from . import diagnostic
    from .config_locale import chemin_config
    from .connecteurs import Connecteurs, construire_catalogue
    from .db import ErreurBaseOuReseau
    from .moteurs.telemetrie import EnregistreurBase
    from .securite.coffre import Coffre
    from .tailscale import lire_etat as lire_tailscale

    if reparer and p.stockage_effectif == "sqlite":
        await migrer(p)
    if reparer:  # « --reparer » vaut accord : seul le modèle d'embeddings, indispensable à la mémoire
        from . import telechargements

        modele = telechargements.modele_embeddings(p.dossier_modeles, p.modele_embeddings)
        if not telechargements.est_pret(modele) and not diagnostic.modele_present(
            p.dossier_modeles, p.modele_embeddings
        ):
            print("Téléchargement du modèle d'embeddings (une seule fois, reprise possible)…")
            with telechargements.nouveau_client() as client:
                etat = await asyncio.to_thread(telechargements.telecharger, modele, client)
            print(f"  {diagnostic.decrire_telechargement(etat)}")
    base: Base | None
    try:
        base = await ouvrir_base(p, max_size=1)
    except (*ErreurBaseOuReseau, RuntimeError):
        base = None
    try:
        connecteurs = None
        if base is not None:
            coffre = Coffre(chemin_config().parent / "coffre.json")
            catalogue = construire_catalogue(p, charger_config_locale(), coffre, EnregistreurBase(base))
            connecteurs = Connecteurs(base, catalogue, coffre, prefere=p.moteur_defaut)
            with contextlib.suppress(*ErreurBaseOuReseau):  # base pas encore créée : réglages par défaut
                await connecteurs.charger()
        # Core en marche : son mode sans écran fait foi (il peut venir de `serveur --sans-ecran`, pas de .env)
        en_marche, sans_ecran = False, p.sans_ecran
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                rep = await client.get(f"http://127.0.0.1:{p.port}/v1/sante")
            en_marche = rep.status_code == 200
            if en_marche:
                sans_ecran = sans_ecran or bool(rep.json().get("sans_ecran"))
        except (httpx.HTTPError, ValueError):
            pass
        verifications = await diagnostic.diagnostiquer(
            p, base, connecteurs, await lire_tailscale(p.port), sans_ecran=sans_ecran
        )
    finally:
        if base is not None:
            await base.close()
    verifications.append(
        diagnostic.Verification(
            "core",
            "Core",
            "ok" if en_marche else "info",
            f"en marche sur http://localhost:{p.port}" if en_marche else "arrêté",
            aide=None if en_marche else "jarvis2 (démarre le Core et ouvre l'interface)",
        )
    )
    from .latence import mesurer as mesurer_latence

    verifications.extend(await mesurer_latence(p, latence))  # voix : étape par étape (lot K3)
    if en_json:
        print(json.dumps([v.en_dict() for v in verifications], ensure_ascii=False, indent=2))
    else:
        print(f"JARVIS 2 — diagnostic ({p.stockage_effectif})\n{diagnostic.texte(verifications)}")
    return 1 if any(v.statut == "erreur" for v in verifications) else 0


async def _memoire(p: Parametres, action: str, fichier: Path | None, dossier: Path | None) -> int:
    """Commandes de la mémoire v2 (banc d'évaluation, export Markdown, noyau en blocs, oubli)."""
    import yaml

    from . import blocs, memoire_v2
    from .embeddings import EncodeurFastEmbed

    async with _base(p) as base:
        if action == "banc":
            if fichier is None or not await asyncio.to_thread(fichier.is_file):
                journal.error("Banc : indiquez --fichier <questions.yaml> (question, attendus)")
                return 2
            questions = memoire_v2.lire_banc(yaml.safe_load(await asyncio.to_thread(fichier.read_text, "utf-8")))
            encodeur = EncodeurFastEmbed(p.dossier_modeles, p.modele_embeddings)
            for classement in ("v1", "v2"):  # même banc, deux classements
                print((await memoire_v2.evaluer(base, encodeur, questions, classement)).texte())
        elif action == "exporter":
            cible = dossier or p.dossier_donnees / "memoire-md"
            fichiers = await memoire_v2.exporter_markdown(base, cible, await blocs.lister(base))
            print(f"{len(fichiers)} fichiers écrits dans {cible}")
        elif action == "noyau-en-blocs":
            print(f"Noyau converti en blocs : {await blocs.noyau_en_blocs(base, 'cli')}")
        elif action == "oublier":
            print(f"Souvenirs archivés (jamais effacés) : {await memoire_v2.oublier(base)}")
    return 0


def _phrase(confirmer: bool) -> str:
    import getpass
    import os

    phrase = os.environ.get("JARVIS2_PHRASE_SAUVEGARDE") or getpass.getpass("Phrase de passe de la sauvegarde : ")
    saisie = not os.environ.get("JARVIS2_PHRASE_SAUVEGARDE")
    if confirmer and saisie and getpass.getpass("Confirmez la phrase : ") != phrase:
        raise SystemExit("Les deux phrases diffèrent.")
    return phrase


async def _comptes_postgres(p: Parametres) -> tuple[dict[str, int], str | None]:
    from .sauvegarde import TABLES

    async with _base(p) as base:
        comptes = {t: int(await base.fetchval(f"SELECT count(*) FROM {t}")) for t in TABLES}  # noqa: S608
        dernier = await base.fetchval("SELECT hash FROM audit ORDER BY id DESC LIMIT 1")
    return comptes, dernier


def _sauvegarde(p: Parametres, action: str, dossier: Path | None, fichier: Path | None, garder: int) -> int:
    """Sauvegarde chiffrée (à garder hors du PC) et vérification par restauration réelle."""
    from .config import dossier_config
    from .sauvegarde import ErreurSauvegarde, creer, rotation, verifier_postgres, verifier_sqlite

    try:
        if action == "creer":
            if dossier is None:
                journal.error("Indiquez --dossier (disque externe, dossier synchronisé hors du PC…)")
                return 2
            phrase = _phrase(confirmer=True)
            if p.stockage_effectif == "sqlite":
                cree = creer(dossier, phrase, "sqlite", p.chemin_sqlite, dossier_config())
            else:
                comptes, dernier = asyncio.run(_comptes_postgres(p))
                pg = (p.conteneur_pg, p.postgres_user, p.postgres_db)
                cree = creer(dossier, phrase, "postgres", None, dossier_config(), pg, comptes, dernier)
            retirees = rotation(dossier, garder)
            print(f"Sauvegarde écrite : {cree} ({cree.stat().st_size / 1024**2:.1f} Mo)")
            if retirees:
                print(f"Anciennes sauvegardes retirées : {len(retirees)} (gardées : {garder})")
            print("Vérifiez-la : jarvis2 sauvegarde verifier --fichier <ce fichier>")
            return 0
        if fichier is None or not fichier.is_file():
            journal.error("Indiquez --fichier <sauvegarde .jarvis2>")
            return 2
        phrase = _phrase(confirmer=False)
        if p.stockage_effectif == "sqlite":
            rapport = verifier_sqlite(fichier, phrase)
        else:
            rapport = verifier_postgres(fichier, phrase, p.conteneur_pg, p.postgres_user)
    except ErreurSauvegarde as exc:
        journal.error("%s", exc)
        return 3
    etat = "VALIDE" if rapport["valide"] else "INVALIDE"
    print(f"Sauvegarde du {rapport['date']} (JARVIS {rapport['version']}) : {etat}")
    print(f"  Lignes restaurées : {rapport['comptes']}")
    print(f"  Journal d'audit : {'chaîne intacte' if rapport['audit_intact'] else 'ALTÉRÉ ou différent'}")
    for table, (attendu, trouve) in rapport["ecarts"].items():
        print(f"  ÉCART {table} : {attendu} attendus, {trouve} restaurés")
    return 0 if rapport["valide"] else 3


def _sorties_tolerantes() -> None:
    """Sortie redirigée sous Windows (cp1252) : un caractère hors de la page de code (✔, ⇄) est remplacé au lieu
    de faire planter la commande (`jarvis2 --help > fichier`, `jarvis2 docteur | more`)."""
    for flux in (sys.stdout, sys.stderr):
        encodage = (getattr(flux, "encoding", None) or "").lower().replace("-", "")
        if encodage != "utf8" and isinstance(flux, io.TextIOWrapper):
            flux.reconfigure(errors="replace")


def main(argv: list[str] | None = None) -> int:
    _sorties_tolerantes()
    analyseur = argparse.ArgumentParser(prog="jarvis2", description="JARVIS 2 — Core")
    sous = analyseur.add_subparsers(dest="commande")
    m = sous.add_parser("migrer", help="appliquer les migrations")
    m.add_argument("--base", help="PostgreSQL : base cible (défaut : POSTGRES_DB)")
    srv = sous.add_parser("serveur", help="lancer le Core")
    srv.add_argument("--ouvrir", action="store_true", help="ouvrir l'interface dans le navigateur")
    srv.add_argument(
        "--sans-ecran",
        action="store_true",
        help="serveur sans écran : capture, clics et contrôle de l'écran refusés ; voix par le micro du navigateur",
    )
    doc = sous.add_parser("docteur", aliases=["doctor"], help="diagnostic de l'installation")
    doc.add_argument("--json", action="store_true", help="résultat en JSON")
    doc.add_argument("--reparer", action="store_true", help="appliquer les réparations sûres (schéma, modèle)")
    doc.add_argument(
        "--latence", action="store_true", help="voix : préchauffer et mesurer chaque étape (Whisper, Ollama)"
    )
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
    sto = sous.add_parser("stockage", help="stockage : copier PostgreSQL ⇄ SQLite")
    sto_sous = sto.add_subparsers(dest="action", required=True)
    cop = sto_sous.add_parser("copier", help="tout copier vers un stockage vide de l'autre moteur (source lue seule)")
    cop.add_argument("--vers", choices=["sqlite", "postgres"], required=True, help="moteur cible")
    cop.add_argument("--fichier", type=Path, default=None, help="fichier SQLite (défaut : JARVIS2_SQLITE)")
    mem = sous.add_parser("memoire", help="mémoire v2 : banc, export Markdown, noyau en blocs, oubli")
    mem.add_argument("action", choices=["banc", "exporter", "noyau-en-blocs", "oublier"])
    mem.add_argument("--fichier", type=Path, default=None, help="banc : questions YAML (question, attendus)")
    mem.add_argument("--dossier", type=Path, default=None, help="exporter : dossier (défaut : données/memoire-md)")
    sau = sous.add_parser("sauvegarde", help="sauvegarde chiffrée hors du PC, et vérification par restauration")
    sau.add_argument("action", choices=["creer", "verifier"])
    sau.add_argument("--dossier", type=Path, default=None, help="creer : dossier de destination (hors du PC)")
    sau.add_argument("--fichier", type=Path, default=None, help="verifier : sauvegarde .jarvis2")
    sau.add_argument("--garder", type=int, default=7, help="creer : nombre de sauvegardes gardées (défaut 7)")
    sous.add_parser("atelier-mcp", help="(interne) outil d'autorisation des ateliers, lancé par Claude Code")
    args = analyseur.parse_args(argv)
    if args.commande == "atelier-mcp":  # serveur MCP stdio : aucun journal sur la sortie standard
        from .ateliers.mcp_autorisation import main as main_mcp

        return main_mcp()
    if args.commande is None:  # `jarvis2` seul : démarrer et ouvrir l'interface
        args = analyseur.parse_args(["serveur", "--ouvrir"])

    p = parametres()
    configurer_journal(p.niveau_journal, p.dossier_journaux)

    if args.commande == "migrer":
        appliquees = asyncio.run(migrer(p, args.base))
        journal.info("Migrations appliquées : %s", ", ".join(appliquees) or "aucune (déjà à jour)")
        return 0

    if args.commande in ("importer", "verifier-import") and p.stockage_effectif != "postgres":
        journal.error(
            "L'import %s passe par une base d'attente PostgreSQL : lancez-le avec JARVIS2_STOCKAGE=postgres, puis"
            " copiez les données vers SQLite avec `jarvis2 stockage copier` si vous le souhaitez.",
            args.source,
        )
        return 2

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
        asyncio.run(migrer(p))
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

    if args.commande in ("docteur", "doctor"):
        for bavard in ("httpx", "huggingface_hub", "jarvis2.config_locale", "jarvis2.embeddings"):
            logging.getLogger(bavard).setLevel(logging.WARNING)  # le diagnostic se lit seul
        return asyncio.run(_docteur(p, args.json, args.reparer, args.latence))

    if args.commande == "sauvegarde":
        return _sauvegarde(p, args.action, args.dossier, args.fichier, args.garder)

    if args.commande == "memoire":
        return asyncio.run(_memoire(p, args.action, args.fichier, args.dossier))

    if args.commande == "stockage":
        return asyncio.run(_copier_stockage(p, args.vers, args.fichier))

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
        if p.stockage_effectif == "sqlite":  # aucune installation : le fichier est créé ou mis à jour ici
            appliquees = asyncio.run(migrer(p))
            if appliquees:
                journal.info("Stockage SQLite %s : migrations %s", p.chemin_sqlite, ", ".join(appliquees))
        if args.sans_ecran:
            p = p.model_copy(update={"sans_ecran": True})
        if args.ouvrir and not p.sans_ecran:  # sans écran : aucun navigateur à ouvrir sur ce PC
            p = p.model_copy(update={"ouvrir_navigateur": True})
        uvicorn.run(creer_app(p), host=p.hote, port=p.port, log_config=None, access_log=False)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
