"""Stockage : une seule interface (le sous-ensemble d'asyncpg dont le Core se sert), deux moteurs.

- **SQLite** (défaut, `db_sqlite.py`) : un fichier dans le dossier des données, aucune installation.
- **PostgreSQL + pgvector** (option, `db_postgres.py`) : rôles séparés, audit protégé par un rôle dédié.

Les requêtes sont écrites pour PostgreSQL (`$1`, `now()`, `::text`…) ; l'adaptateur SQLite les traduit. Les rares
requêtes sans équivalent direct (recherche mémoire, audit) ont une version par moteur (`base.dialecte`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

import asyncpg

if TYPE_CHECKING:
    from .config import Parametres

Dialecte = Literal["postgres", "sqlite"]

DOSSIER_MIGRATIONS = Path(__file__).parent / "migrations"

# Erreurs de base, quel que soit le moteur
ErreurBase = (asyncpg.PostgresError, sqlite3.Error)
ErreurBaseOuReseau = (asyncpg.PostgresError, sqlite3.Error, OSError)


class Ligne(Protocol):
    """Une ligne de résultat : accès par nom ou par position, `get`, `keys` (asyncpg.Record ou équivalent)."""

    def __getitem__(self, cle: str | int, /) -> Any: ...
    def get(self, cle: str, defaut: Any = None, /) -> Any: ...
    def keys(self) -> Iterable[str]: ...


class Executant(Protocol):
    """Ce qui exécute une requête : la base elle-même ou une connexion prêtée."""

    @property
    def dialecte(self) -> Dialecte: ...
    async def fetch(self, requete: str, *args: Any) -> list[Any]: ...
    async def fetchrow(self, requete: str, *args: Any) -> Any: ...
    async def fetchval(self, requete: str, *args: Any) -> Any: ...
    async def execute(self, requete: str, *args: Any) -> str: ...


class Connexion(Executant, Protocol):
    """Connexion prêtée par la base : transactions (imbriquées = points de sauvegarde) et verrou de transaction."""

    def transaction(self) -> AbstractAsyncContextManager[None]: ...
    async def verrouiller(self, cle: int) -> None: ...


class Base(Executant, Protocol):
    def acquire(self) -> AbstractAsyncContextManager[Connexion]: ...
    async def close(self) -> None: ...


def lister_migrations(dialecte: Dialecte = "postgres") -> list[tuple[str, Path]]:
    dossier = DOSSIER_MIGRATIONS / "sqlite" if dialecte == "sqlite" else DOSSIER_MIGRATIONS
    return [(f.stem, f) for f in sorted(dossier.glob("*.sql"))]


async def version_schema(base: Executant) -> str | None:
    valeur: Any = await base.fetchval("SELECT max(version) FROM schema_migrations")
    return str(valeur) if valeur is not None else None


async def ouvrir_base(p: Parametres, max_size: int = 10) -> Base:
    """Base du Core, selon `JARVIS2_STOCKAGE` (rôle applicatif pour PostgreSQL)."""
    if p.stockage_effectif == "postgres":
        from .db_postgres import BasePostgres, creer_pool

        return BasePostgres(await creer_pool(p.url_base("app"), max_size=max_size))
    from .db_sqlite import BaseSQLite

    return await BaseSQLite.ouvrir(p.chemin_sqlite)


async def migrer(p: Parametres, base_pg: str | None = None) -> list[str]:
    """Applique les migrations manquantes du stockage choisi (rôle propriétaire pour PostgreSQL)."""
    if p.stockage_effectif == "postgres":
        from .db_postgres import appliquer_migrations

        return await appliquer_migrations(p.url_base("proprio", base_pg))
    from .db_sqlite import appliquer_migrations as appliquer_sqlite

    return await appliquer_sqlite(p.chemin_sqlite)
