"""Fixtures : base de test `jarvis2_test` (créée par infra/postgres/initdb), migrée et vidée à chaque test."""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest

from jarvis2.config import Parametres
from jarvis2.db import appliquer_migrations, creer_pool

BASE_TEST = "jarvis2_test"


@pytest.fixture
def parametres() -> Parametres:
    return Parametres()


@pytest.fixture
async def url_proprio(parametres: Parametres) -> str:
    try:
        url = parametres.url_base("proprio", BASE_TEST)
        conn = await asyncpg.connect(url, timeout=3)
    except (OSError, RuntimeError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Base de test indisponible (docker compose up -d) : {exc}")
    await conn.close()
    return url


@pytest.fixture
async def pool(url_proprio: str, parametres: Parametres) -> AsyncIterator[asyncpg.Pool]:
    await appliquer_migrations(url_proprio)
    conn = await asyncpg.connect(url_proprio)
    try:
        await conn.execute(
            "TRUNCATE memory_block_versions, memory_blocks, telemetrie, imports, chantiers, creation_donnees,"
            " creation_versions, creations, missions, profil_reponses, messages, conversations, memoires,"
            " defis_webauthn, cles_acces, demandes, jumelages, appareils, connecteurs RESTART IDENTITY CASCADE"
        )
        # Le journal d'audit est en ajout seul, même pour les tests : on ne le vide jamais (assertions relatives).
        await conn.execute("UPDATE etat_systeme SET valeur = '{\"actif\": false}' WHERE cle = 'arret_urgence'")
    finally:
        await conn.close()
    p = await creer_pool(parametres.url_base("app", BASE_TEST), max_size=4)
    try:
        yield p
    finally:
        await p.close()
