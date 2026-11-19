"""Fixtures : chaque test de base tourne sur les DEUX stockages.

- `pool` : SQLite (fichier neuf dans le dossier temporaire du test) puis PostgreSQL (base de test `jarvis2_test`,
  créée par infra/postgres/initdb, migrée et vidée à chaque test ; ignorée si Docker est arrêté).
- `pool_pg` : PostgreSQL seulement (rôles, droits, import depuis une sauvegarde PostgreSQL).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest

from jarvis2.config import Parametres
from jarvis2.db import Base
from jarvis2.db_postgres import BasePostgres, appliquer_migrations, creer_pool
from jarvis2.db_sqlite import BaseSQLite
from jarvis2.db_sqlite import appliquer_migrations as appliquer_sqlite

BASE_TEST = "jarvis2_test"


@pytest.fixture
def parametres() -> Parametres:
    return Parametres()


async def _url_proprio(parametres: Parametres) -> str:
    try:
        url = parametres.url_base("proprio", BASE_TEST)
        conn = await asyncpg.connect(url, timeout=3)
    except (OSError, RuntimeError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Base de test PostgreSQL indisponible (docker compose up -d) : {exc}")
    await conn.close()
    return url


@pytest.fixture
async def url_proprio(parametres: Parametres) -> str:
    return await _url_proprio(parametres)


async def _postgres(url_proprio: str, parametres: Parametres) -> BasePostgres:
    await appliquer_migrations(url_proprio)
    conn = await asyncpg.connect(url_proprio)
    try:
        await conn.execute(
            "TRUNCATE memory_block_versions, memory_blocks, telemetrie, imports, chantiers, creation_donnees,"
            " creation_versions, creations, missions, profil_reponses, messages, conversations, memoires,"
            " defis_webauthn, cles_acces, demandes, jumelages, appareils, connecteurs, executions_recettes, outils_mcp,"
            " fichiers_atelier, evenements_atelier, ateliers, memoire_vecteurs, domaines, fiches_concepts,"
            " questions_controle, extractions_domaines, journal_domaines, regles_protection, commandes_rapides,"
            " autorisations_permanentes, connecteurs_maison"
            " RESTART IDENTITY CASCADE"
        )
        # Le journal d'audit est en ajout seul, même pour les tests : on ne le vide jamais (assertions relatives).
        await conn.execute("UPDATE etat_systeme SET valeur = '{\"actif\": false}' WHERE cle = 'arret_urgence'")
        await conn.execute("UPDATE etat_systeme SET valeur = '{\"termine\": false}' WHERE cle = 'accueil'")
        await conn.execute('UPDATE etat_systeme SET valeur = \'{"mode": "parle", "vus": {}}\' WHERE cle = \'matin\'')
        await conn.execute(
            'UPDATE etat_systeme SET valeur = \'{"actif": false, "voix": false, "notification": true}\''
            " WHERE cle = 'veille_claude_code'"
        )
        await conn.execute(  # synthèse vocale (lot K2) : réglages par défaut
            'UPDATE etat_systeme SET valeur = \'{"moteur": "navigateur", "voix_piper": "fr_FR-siwis-medium",'
            ' "voix_elevenlabs": "21m00Tcm4TlvDq8ikWAM", "coupure": true}\' WHERE cle = \'synthese\''
        )
    finally:
        await conn.close()
    return BasePostgres(await creer_pool(parametres.url_base("app", BASE_TEST), max_size=4))


async def _sqlite(dossier: Path) -> BaseSQLite:
    chemin = dossier / "jarvis2.db"
    await appliquer_sqlite(chemin)
    return await BaseSQLite.ouvrir(chemin)


@pytest.fixture(params=["sqlite", "postgres"])
async def pool(request: pytest.FixtureRequest, parametres: Parametres, tmp_path: Path) -> AsyncIterator[Base]:
    base: Base
    if request.param == "sqlite":
        base = await _sqlite(tmp_path)
    else:
        base = await _postgres(await _url_proprio(parametres), parametres)
    try:
        yield base
    finally:
        await base.close()


@pytest.fixture
async def pool_pg(url_proprio: str, parametres: Parametres) -> AsyncIterator[BasePostgres]:
    base = await _postgres(url_proprio, parametres)
    try:
        yield base
    finally:
        await base.close()
