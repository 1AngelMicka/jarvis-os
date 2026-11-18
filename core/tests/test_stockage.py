"""Stockage SQLite (défaut) : traduction, transactions, concurrence, plein texte, parité avec PostgreSQL."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import numpy as np
import pytest

from jarvis2 import memoire
from jarvis2.config import Parametres
from jarvis2.conversations import DepotConversations
from jarvis2.db import lister_migrations, version_schema
from jarvis2.db_sqlite import BaseSQLite, _cosinus_python, appliquer_migrations, traduire

from .test_memoire import MODELE, EncodeurFactice


@pytest.fixture
async def base(tmp_path: Path) -> AsyncIterator[BaseSQLite]:
    await appliquer_migrations(tmp_path / "j.db")
    b = await BaseSQLite.ouvrir(tmp_path / "j.db")
    yield b
    await b.close()


def test_traduction() -> None:
    assert traduire("SELECT $1::text::jsonb, $12::int FROM t WHERE x = ANY($2::text[]) FOR UPDATE") == (
        "SELECT ?1, ?12 FROM t WHERE x = ANY(?2)"
    )


def test_versions_alignees_sur_postgres() -> None:
    assert [v for v, _ in lister_migrations("sqlite")] == [v for v, _ in lister_migrations("postgres")]


async def test_migrations_idempotentes(tmp_path: Path) -> None:
    assert len(await appliquer_migrations(tmp_path / "j.db")) == len(lister_migrations("sqlite"))
    assert await appliquer_migrations(tmp_path / "j.db") == []
    b = await BaseSQLite.ouvrir(tmp_path / "j.db")
    try:
        assert await version_schema(b) == lister_migrations("postgres")[-1][0]
    finally:
        await b.close()


async def test_types_et_contraintes(base: BaseSQLite) -> None:
    depot = DepotConversations(base)
    conv = await depot.creer("Essai")
    assert isinstance(conv.id, UUID) and conv.cree_le.tzinfo is not None and conv.epinglee is False
    message = await depot.ajouter_message(conv.id, "jarvis", "Bonjour", {"moteur": "faux", "n": [1, 2]})
    assert message.meta == {"moteur": "faux", "n": [1, 2]} and isinstance(message.id, int)
    with pytest.raises(sqlite3.IntegrityError):  # CHECK du rôle
        await depot.ajouter_message(conv.id, "systeme", "interdit")
    with pytest.raises(sqlite3.IntegrityError):  # clé étrangère
        await depot.ajouter_message(UUID(int=1), "jarvis", "orphelin")
    with pytest.raises(sqlite3.IntegrityError):  # expression régulière (fonction regexp)
        await base.execute("INSERT INTO connecteurs (id, actif) VALUES ('Pas Valide', 1)")
    assert await base.execute("UPDATE conversations SET titre = 'x' WHERE id = $1", conv.id) == "UPDATE 1"


async def test_transactions_imbriquees(base: BaseSQLite) -> None:
    async with base.acquire() as conn, conn.transaction():
        await conn.execute("INSERT INTO conversations (titre) VALUES ('gardée')")
        with pytest.raises(RuntimeError):
            async with conn.transaction():  # point de sauvegarde annulé seul
                await conn.execute("INSERT INTO conversations (titre) VALUES ('annulée')")
                raise RuntimeError
    assert [r["titre"] for r in await base.fetch("SELECT titre FROM conversations")] == ["gardée"]


async def test_annulation_d_une_tache_annule_sa_transaction(base: BaseSQLite) -> None:
    commencee = asyncio.Event()

    async def longue() -> None:
        async with base.acquire() as conn, conn.transaction():
            await conn.execute("INSERT INTO conversations (titre) VALUES ('jamais')")
            commencee.set()
            await asyncio.sleep(10)

    tache = asyncio.create_task(longue())
    await commencee.wait()
    tache.cancel()  # arrêt d'urgence : la réponse en cours est annulée
    with pytest.raises(asyncio.CancelledError):
        await tache
    assert await base.fetchval("SELECT count(*) FROM conversations") == 0
    await base.execute("INSERT INTO conversations (titre) VALUES ('ensuite')")  # la base reste utilisable


async def test_ecritures_concurrentes_serialisees(base: BaseSQLite) -> None:
    depot = DepotConversations(base)
    conv = await depot.creer("Concurrence")
    await asyncio.gather(*(depot.ajouter_message(conv.id, "jarvis", f"m{i}") for i in range(40)))
    assert await base.fetchval("SELECT count(*) FROM messages") == 40


async def test_plein_texte_sans_accents(base: BaseSQLite) -> None:
    enc = EncodeurFactice()
    ete = await memoire.ajouter(
        base, "Les tomates mûrissent en été", vecteur=await enc.encoder("x"), modele=MODELE, origine="utilisateur"
    )
    await memoire.ajouter(base, "La voiture est au garage", vecteur=await enc.encoder("y"), modele=MODELE)
    resultats = await memoire.rechercher(base, enc, "tomates ete murissent", limite=5)
    assert resultats[0].souvenir.id == ete and resultats[0].score > resultats[1].score
    # Souvenir modifié : l'index plein texte suit (déclencheurs)
    await base.execute("UPDATE memoires SET contenu = 'Les courgettes poussent' WHERE id = $1", ete)
    assert (await memoire.rechercher(base, enc, "courgettes", limite=1))[0].souvenir.id == ete


def test_cosinus_de_secours_identique_a_sqlite_vec() -> None:
    a = np.array([1.0, 0.0, 1.0], dtype=np.float32)
    b = np.array([0.5, 0.5, 0.0], dtype=np.float32)
    attendu = 1 - float(a @ b) / float(np.linalg.norm(a) * np.linalg.norm(b))
    assert _cosinus_python(a.tobytes(), b.tobytes()) == pytest.approx(attendu, abs=1e-6)
    connexion = sqlite3.connect(":memory:")
    try:
        import sqlite_vec

        connexion.enable_load_extension(True)
        sqlite_vec.load(connexion)
    except (ImportError, AttributeError, sqlite3.OperationalError):
        pytest.skip("sqlite-vec indisponible")
    (valeur,) = connexion.execute("SELECT vec_distance_cosine(?, ?)", (a.tobytes(), b.tobytes())).fetchone()
    assert valeur == pytest.approx(attendu, abs=1e-6)


def test_choix_du_stockage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for variable in ("JARVIS2_STOCKAGE", "JARVIS2_APP_MOT_DE_PASSE", "JARVIS2_SQLITE"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("JARVIS2_DOSSIER_DONNEES", str(tmp_path))
    neuve = Parametres(_env_file=None)
    assert neuve.stockage_effectif == "sqlite" and neuve.chemin_sqlite == tmp_path / "jarvis2.db"
    monkeypatch.setenv("JARVIS2_APP_MOT_DE_PASSE", "m")
    assert Parametres(_env_file=None).stockage_effectif == "postgres"
    monkeypatch.setenv("JARVIS2_STOCKAGE", "sqlite")
    assert Parametres(_env_file=None).stockage_effectif == "sqlite"
    monkeypatch.setenv("JARVIS2_STOCKAGE", "mysql")
    with pytest.raises(ValueError, match="inconnu"):
        _ = Parametres(_env_file=None).stockage_effectif
