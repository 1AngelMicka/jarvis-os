"""Accès à PostgreSQL : pool asyncpg (avec le type `vector`) et migrations versionnées.

asyncpg plutôt que psycopg : il fonctionne avec la boucle Proactor de Windows, indispensable pour lancer la
CLI claude en sous-processus depuis le même serveur.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import asyncpg
from pgvector.asyncpg import register_vector

journal = logging.getLogger("jarvis2.db")

# Une connexion (directe ou prêtée par le pool), ou le pool lui-même
Connexion = asyncpg.Connection | asyncpg.pool.PoolConnectionProxy
Executant = asyncpg.Pool | Connexion

DOSSIER_MIGRATIONS = Path(__file__).parent / "migrations"
VERROU_MIGRATIONS = 726_002  # verrou consultatif réservé aux migrations


def lister_migrations() -> list[tuple[str, Path]]:
    return [(f.stem, f) for f in sorted(DOSSIER_MIGRATIONS.glob("*.sql"))]


async def _initialiser_connexion(conn: asyncpg.Connection) -> None:
    await register_vector(conn)
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def creer_pool(url: str, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(url, min_size=min_size, max_size=max_size, init=_initialiser_connexion)
    if pool is None:  # pragma: no cover — create_pool ne renvoie None qu'avec un pool paresseux
        raise RuntimeError("Pool PostgreSQL indisponible")
    return pool


async def appliquer_migrations(url_proprio: str) -> list[str]:
    """Applique les migrations manquantes, chacune dans sa transaction (idempotent).

    Renvoie les versions appliquées lors de cet appel. Doit être lancé avec le rôle propriétaire.
    """
    appliquees: list[str] = []
    conn = await asyncpg.connect(url_proprio)
    try:
        await conn.execute("SELECT pg_advisory_lock($1)", VERROU_MIGRATIONS)
        try:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version text PRIMARY KEY, appliquee_le timestamptz NOT NULL DEFAULT now())"
            )
            deja = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}
            for version, chemin in lister_migrations():
                if version in deja:
                    continue
                journal.info("Migration %s…", version)
                async with conn.transaction():
                    await conn.execute(chemin.read_text(encoding="utf-8"))
                    await conn.execute("INSERT INTO schema_migrations (version) VALUES ($1)", version)
                appliquees.append(version)
            await conn.execute("GRANT SELECT ON schema_migrations TO jarvis2_app")
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", VERROU_MIGRATIONS)
    finally:
        await conn.close()
    return appliquees


async def version_schema(pool: asyncpg.Pool) -> str | None:
    valeur: Any = await pool.fetchval("SELECT max(version) FROM schema_migrations")
    return str(valeur) if valeur is not None else None
