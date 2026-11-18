"""Stockage SQLite (défaut) : un fichier, aucune installation, même interface que PostgreSQL.

- **Une connexion**, sur un fil d'exécution dédié : les requêtes passent l'une après l'autre ; une connexion prêtée
  (`acquire`) garde la base pour sa tâche, et les transactions imbriquées deviennent des points de sauvegarde.
  `BEGIN IMMEDIATE` : une transaction prend tout de suite le verrou d'écriture (pas d'interblocage).
- **Traduction** des requêtes écrites pour PostgreSQL : `$1` → `?1`, conversions `::type` retirées, `FOR UPDATE`
  retiré (inutile : une seule écriture à la fois). `now()`, `gen_random_uuid()` et `regexp` sont des fonctions
  ajoutées à chaque connexion.
- **Types** par les types déclarés du schéma (`migrations/sqlite`) : UUID, TIMESTAMPTZ (texte UTC à largeur fixe, donc
  comparable), BOOLEAN, JSONB, TEXTLIST et UUIDLIST (tableaux JSON), VECTOR (float32).
- **Vecteurs** : extension sqlite-vec (`vec_distance_cosine`) ; à défaut (Python sans extensions), même fonction en
  Python.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import uuid
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, TypeVar

import numpy as np

from .db import Connexion, Dialecte, lister_migrations

journal = logging.getLogger("jarvis2.db")

T = TypeVar("T")
Mode = Literal["tout", "ligne", "valeur", "executer"]

FORMAT_DATE = "%Y-%m-%dT%H:%M:%S.%f+00:00"  # largeur fixe : l'ordre du texte est l'ordre chronologique


def date_texte(d: datetime) -> str:
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(UTC).strftime(FORMAT_DATE)


def vecteur_octets(v: Any) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


# --- Conversions Python ⇄ SQLite (globales au module sqlite3) ---------------------------------------------
sqlite3.register_adapter(uuid.UUID, str)
sqlite3.register_adapter(datetime, date_texte)
sqlite3.register_adapter(dict, lambda v: json.dumps(v, ensure_ascii=False))
sqlite3.register_adapter(list, lambda v: json.dumps(v, ensure_ascii=False, default=str))
sqlite3.register_adapter(tuple, lambda v: json.dumps(list(v), ensure_ascii=False, default=str))
sqlite3.register_adapter(np.ndarray, vecteur_octets)
sqlite3.register_converter("UUID", lambda b: uuid.UUID(b.decode()))
sqlite3.register_converter("TIMESTAMPTZ", lambda b: datetime.fromisoformat(b.decode()))
sqlite3.register_converter("BOOLEAN", lambda b: b not in (b"0", b""))
sqlite3.register_converter("JSONB", json.loads)
sqlite3.register_converter("TEXTLIST", json.loads)
sqlite3.register_converter("UUIDLIST", lambda b: [uuid.UUID(x) for x in json.loads(b)])
sqlite3.register_converter("VECTOR", lambda b: np.frombuffer(b, dtype=np.float32).copy())

_PARAM = re.compile(r"\$(\d+)")
_CONVERSION = re.compile(
    r"::(?:text|jsonb|json|int|integer|bigint|float|real|uuid|vector|boolean|bool|timestamptz)(?:\[\])?", re.IGNORECASE
)
_FOR_UPDATE = re.compile(r"\s+FOR\s+UPDATE\b", re.IGNORECASE)
_VERBE = re.compile(r"\s*(?:WITH\b.*?\)\s*)?(\w+)", re.IGNORECASE | re.DOTALL)


@lru_cache(maxsize=1024)
def traduire(requete: str) -> str:
    """Requête écrite pour PostgreSQL → SQLite."""
    requete = _CONVERSION.sub("", requete)
    requete = _FOR_UPDATE.sub("", requete)
    return _PARAM.sub(r"?\1", requete)


class LigneSQLite(dict[str, Any]):
    """Ligne de résultat : accès par nom ou par position (comme asyncpg.Record)."""

    def __getitem__(self, cle: str | int) -> Any:
        if isinstance(cle, int):
            return list(self.values())[cle]
        return super().__getitem__(cle)


def _cosinus_python(a: bytes | None, b: bytes | str | None) -> float | None:
    if a is None or b is None:
        return None
    va = np.frombuffer(a, dtype=np.float32)
    vb = np.asarray(json.loads(b), dtype=np.float32) if isinstance(b, str) else np.frombuffer(b, dtype=np.float32)
    n = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return 1.0 - float(np.dot(va, vb)) / n if n else None


def _regexp(motif: str, valeur: str | None) -> bool:
    return valeur is not None and re.search(motif, valeur) is not None


def _connecter(chemin: Path) -> sqlite3.Connection:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(chemin), detect_types=sqlite3.PARSE_DECLTYPES, check_same_thread=False, isolation_level=None
    )
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.create_function("now", 0, lambda: date_texte(datetime.now(UTC)))
    conn.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))
    conn.create_function("regexp", 2, _regexp, deterministic=True)
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except (ImportError, AttributeError, sqlite3.OperationalError) as exc:  # Python sans extensions SQLite
        journal.info("sqlite-vec indisponible (%s) : distance cosinus calculée en Python", exc)
        conn.create_function("vec_distance_cosine", 2, _cosinus_python, deterministic=True)
    return conn


def _statut(requete: str, nombre: int) -> str:
    m = _VERBE.match(requete)
    verbe = (m.group(1) if m else "").upper()
    return f"INSERT 0 {nombre}" if verbe == "INSERT" else f"{verbe} {max(nombre, 0)}"


class BaseSQLite:
    dialecte: Dialecte = "sqlite"

    def __init__(self, conn: sqlite3.Connection, executeur: ThreadPoolExecutor, chemin: Path) -> None:
        self._conn = conn
        self._executeur = executeur
        self.chemin = chemin
        self._verrou = asyncio.Lock()
        self._tenue: ContextVar[ConnexionSQLite | None] = ContextVar(f"sqlite_{id(self)}", default=None)

    @classmethod
    async def ouvrir(cls, chemin: Path) -> BaseSQLite:
        executeur = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jarvis2-sqlite")
        conn = await asyncio.get_running_loop().run_in_executor(executeur, _connecter, chemin)
        return cls(conn, executeur, chemin)

    async def _fil(self, fonction: Callable[[], T]) -> T:
        return await asyncio.get_running_loop().run_in_executor(self._executeur, fonction)

    async def _executer(self, requete: str, args: tuple[Any, ...], mode: Mode) -> Any:
        sql = traduire(requete)

        def travail() -> Any:
            curseur = self._conn.execute(sql, args)
            try:
                if mode == "executer":
                    curseur.fetchall()
                    return _statut(requete, curseur.rowcount)
                colonnes = [d[0] for d in curseur.description or ()]
                lignes = [LigneSQLite(zip(colonnes, r, strict=True)) for r in curseur.fetchall()]
            finally:
                curseur.close()
            if mode == "tout":
                return lignes
            if mode == "ligne":
                return lignes[0] if lignes else None
            return lignes[0][0] if lignes and colonnes else None

        tenue = self._tenue.get()
        if tenue is not None and tenue.base is self:  # la tâche tient déjà la base (connexion prêtée)
            return await self._fil(travail)
        async with self._verrou:
            return await self._fil(travail)

    async def fetch(self, requete: str, *args: Any) -> list[Any]:
        lignes: list[Any] = await self._executer(requete, args, "tout")
        return lignes

    async def fetchrow(self, requete: str, *args: Any) -> Any:
        return await self._executer(requete, args, "ligne")

    async def fetchval(self, requete: str, *args: Any) -> Any:
        return await self._executer(requete, args, "valeur")

    async def execute(self, requete: str, *args: Any) -> str:
        statut: str = await self._executer(requete, args, "executer")
        return statut

    async def script(self, sql: str) -> None:
        """Plusieurs instructions (sans paramètres, sans traduction) : migrations, outils."""
        async with self._verrou:
            await self._fil(lambda: self._conn.executescript(sql))

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Connexion]:
        tenue = self._tenue.get()
        if tenue is not None and tenue.base is self:
            yield tenue
            return
        async with self._verrou:
            connexion = ConnexionSQLite(self)
            jeton = self._tenue.set(connexion)
            try:
                yield connexion
            finally:
                self._tenue.reset(jeton)
                if self._conn.in_transaction:  # transaction laissée ouverte (annulation) : annulée
                    await self._fil(lambda: self._conn.execute("ROLLBACK"))

    async def close(self) -> None:
        async with self._verrou:
            await self._fil(self._conn.close)
        self._executeur.shutdown(wait=True)


class ConnexionSQLite:
    """Connexion prêtée : la base est tenue par la tâche jusqu'à la fin du bloc `acquire`."""

    dialecte: Dialecte = "sqlite"

    def __init__(self, base: BaseSQLite) -> None:
        self.base = base
        self._profondeur = 0

    async def fetch(self, requete: str, *args: Any) -> list[Any]:
        return await self.base.fetch(requete, *args)

    async def fetchrow(self, requete: str, *args: Any) -> Any:
        return await self.base.fetchrow(requete, *args)

    async def fetchval(self, requete: str, *args: Any) -> Any:
        return await self.base.fetchval(requete, *args)

    async def execute(self, requete: str, *args: Any) -> str:
        return await self.base.execute(requete, *args)

    async def _brut(self, sql: str) -> None:
        await self.base._fil(lambda: self.base._conn.execute(sql))

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        niveau = self._profondeur
        point = f"jarvis2_{niveau}"
        await self._brut("BEGIN IMMEDIATE" if niveau == 0 else f"SAVEPOINT {point}")
        self._profondeur += 1
        try:
            yield
        except BaseException:
            self._profondeur = niveau
            await self._brut("ROLLBACK" if niveau == 0 else f"ROLLBACK TO {point}")
            if niveau:
                await self._brut(f"RELEASE {point}")
            raise
        self._profondeur = niveau
        await self._brut("COMMIT" if niveau == 0 else f"RELEASE {point}")

    async def verrouiller(self, cle: int) -> None:
        """Rien à faire : `BEGIN IMMEDIATE` sérialise déjà les transactions d'écriture."""


async def appliquer_migrations(chemin: Path) -> list[str]:
    """Applique les migrations SQLite manquantes, chacune dans sa transaction (idempotent)."""
    base = await BaseSQLite.ouvrir(chemin)
    appliquees: list[str] = []
    try:
        await base.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version TEXT PRIMARY KEY, appliquee_le TIMESTAMPTZ NOT NULL DEFAULT (now()))"
        )
        deja = {r["version"] for r in await base.fetch("SELECT version FROM schema_migrations")}
        for version, fichier in lister_migrations("sqlite"):
            if version in deja:
                continue
            journal.info("Migration SQLite %s…", version)
            sql = fichier.read_text(encoding="utf-8")
            if not re.fullmatch(r"\d{3}_[a-z0-9_]+", version):  # pragma: no cover — noms de fichiers du dépôt
                raise ValueError(f"Nom de migration invalide : {version}")
            try:
                await base.script(  # version validée ci-dessus ; un script SQLite n'accepte pas de paramètres
                    f"BEGIN IMMEDIATE;\n{sql}\n;INSERT INTO schema_migrations (version) VALUES ('{version}');\nCOMMIT;"  # noqa: S608
                )
            except sqlite3.Error:
                if base._conn.in_transaction:
                    await base._fil(lambda: base._conn.execute("ROLLBACK"))
                raise
            appliquees.append(version)
    finally:
        await base.close()
    return appliquees
