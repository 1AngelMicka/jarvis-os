"""Stockage PostgreSQL : pool asyncpg (types `vector` et `jsonb`), migrations versionnées, rôles séparés.

asyncpg plutôt que psycopg : il fonctionne avec la boucle Proactor de Windows, indispensable pour lancer les CLI en
sous-processus depuis le même serveur.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
from pgvector.asyncpg import register_vector

from .db import Connexion, Dialecte, lister_migrations

journal = logging.getLogger("jarvis2.db")

VERROU_MIGRATIONS = 726_002  # verrou consultatif réservé aux migrations


async def _initialiser_connexion(conn: asyncpg.Connection) -> None:
    await register_vector(conn)
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def creer_pool(url: str, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(url, min_size=min_size, max_size=max_size, init=_initialiser_connexion)
    if pool is None:  # pragma: no cover — create_pool ne renvoie None qu'avec un pool paresseux
        raise RuntimeError("Pool PostgreSQL indisponible")
    return pool


class ConnexionPostgres:
    """Connexion asyncpg (directe ou prêtée par le pool) vue à travers l'interface commune."""

    dialecte: Dialecte = "postgres"

    def __init__(self, conn: asyncpg.Connection | asyncpg.pool.PoolConnectionProxy) -> None:
        self.brute = conn

    async def fetch(self, requete: str, *args: Any) -> list[Any]:
        return list(await self.brute.fetch(requete, *args))

    async def fetchrow(self, requete: str, *args: Any) -> Any:
        return await self.brute.fetchrow(requete, *args)

    async def fetchval(self, requete: str, *args: Any) -> Any:
        return await self.brute.fetchval(requete, *args)

    async def execute(self, requete: str, *args: Any) -> str:
        return await self.brute.execute(requete, *args)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        async with self.brute.transaction():
            yield

    async def verrouiller(self, cle: int) -> None:
        await self.brute.execute("SELECT pg_advisory_xact_lock($1)", cle)


class BasePostgres:
    dialecte: Dialecte = "postgres"

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def fetch(self, requete: str, *args: Any) -> list[Any]:
        return list(await self.pool.fetch(requete, *args))

    async def fetchrow(self, requete: str, *args: Any) -> Any:
        return await self.pool.fetchrow(requete, *args)

    async def fetchval(self, requete: str, *args: Any) -> Any:
        return await self.pool.fetchval(requete, *args)

    async def execute(self, requete: str, *args: Any) -> str:
        return await self.pool.execute(requete, *args)

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Connexion]:
        async with self.pool.acquire() as conn:
            yield ConnexionPostgres(conn)

    async def close(self) -> None:
        await self.pool.close()


@asynccontextmanager
async def connexion_directe(url: str) -> AsyncIterator[ConnexionPostgres]:
    """Connexion unique (ex. rôle propriétaire pour un secours en ligne de commande)."""
    conn = await asyncpg.connect(url)
    try:
        await _initialiser_connexion(conn)
        yield ConnexionPostgres(conn)
    finally:
        await conn.close()


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
            for version, chemin in lister_migrations("postgres"):
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
