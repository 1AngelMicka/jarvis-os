"""Copie PostgreSQL → SQLite → PostgreSQL : tout arrive, à l'identique, et la chaîne d'audit reste vérifiable."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import numpy as np
import pytest

from jarvis2 import memoire
from jarvis2.config import Parametres
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.db_postgres import BasePostgres, appliquer_migrations, creer_pool
from jarvis2.db_sqlite import BaseSQLite
from jarvis2.db_sqlite import appliquer_migrations as migrer_sqlite
from jarvis2.securite import appareils, audit
from jarvis2.stockage_copie import ErreurCopie, copier

from .test_memoire import MODELE, EncodeurFactice

pytestmark = pytest.mark.base
BASE_COPIE = "jarvis2_copie_test"


@pytest.fixture
async def pg_vierge(url_proprio: str, parametres: Parametres) -> AsyncIterator[BasePostgres]:
    """Base PostgreSQL neuve et migrée (journal d'audit vide), effacée après le test."""
    conn = await asyncpg.connect(url_proprio)
    try:
        await conn.execute(f"DROP DATABASE IF EXISTS {BASE_COPIE} WITH (FORCE)")
        await conn.execute(f"CREATE DATABASE {BASE_COPIE}")
    finally:
        await conn.close()
    url = parametres.url_base("proprio", BASE_COPIE)
    await appliquer_migrations(url)
    base = BasePostgres(await creer_pool(url, max_size=2))
    try:
        yield base
    finally:
        await base.close()
        conn = await asyncpg.connect(url_proprio)
        try:
            await conn.execute(f"DROP DATABASE IF EXISTS {BASE_COPIE} WITH (FORCE)")
        finally:
            await conn.close()


async def _remplir(base: Base) -> dict[str, str]:
    depot = DepotConversations(base)
    conv = await depot.creer("Voyage à Lyon")
    await depot.ajouter_message(conv.id, "utilisateur", "Où dormir à Lyon ?")
    await depot.ajouter_message(conv.id, "jarvis", "Près de la place Bellecour.", {"moteur": "faux", "cout": 0.5})
    enc = EncodeurFactice()
    souvenir = await memoire.ajouter(
        base,
        "Le train pour Lyon part à 8 h de la gare de l'Est",
        type_="fait",
        tags=["voyage", "noyau"],
        origine="utilisateur",
        vecteur=await enc.encoder("train Lyon"),
        modele=MODELE,
    )
    appareil, _ = await appareils.creer(base, "Téléphone", "telephone")
    await audit.journaliser(base, acteur="test", action="copie.essai", details={"é": "àç", "liste": [1, 2]})
    await base.execute("INSERT INTO connecteurs (id, actif) VALUES ('ollama', true)")
    return {"conversation": str(conv.id), "souvenir": souvenir, "appareil": str(appareil.id)}


async def _verifier(base: Base, ids: dict[str, str]) -> None:
    depot = DepotConversations(base)
    messages = await depot.messages(ids["conversation"])  # type: ignore[arg-type]
    assert [m.contenu for m in messages][1] == "Près de la place Bellecour."
    assert messages[1].meta == {"moteur": "faux", "cout": 0.5}
    resultats = await memoire.rechercher(base, EncodeurFactice(), "train pour Lyon", limite=3)
    assert resultats and resultats[0].souvenir.id == ids["souvenir"]
    assert resultats[0].souvenir.tags == ("voyage", "noyau")
    vecteur = await base.fetchval("SELECT embedding FROM memoires WHERE id = $1", ids["souvenir"])
    vecteur = vecteur.to_numpy() if hasattr(vecteur, "to_numpy") else vecteur  # pgvector.Vector
    attendu = np.asarray(await EncodeurFactice().encoder("train Lyon"), dtype=np.float32)
    assert np.allclose(np.asarray(vecteur, dtype=np.float32), attendu, atol=1e-6)
    (noyau,) = await memoire.lire_noyau(base, exclure_local=False)
    assert noyau.contenu.startswith("Le train")
    assert await base.fetchval("SELECT nom FROM appareils WHERE id = $1", ids["appareil"]) == "Téléphone"
    assert await audit.verifier(base) is None


async def test_aller_retour_postgres_sqlite_postgres(
    pool_pg: BasePostgres, pg_vierge: BasePostgres, tmp_path: Path
) -> None:
    ids = await _remplir(pool_pg)
    await migrer_sqlite(tmp_path / "copie.db")
    sqlite = await BaseSQLite.ouvrir(tmp_path / "copie.db")
    try:
        rapport = await copier(pool_pg, sqlite)
        assert rapport.complet, rapport.texte()
        assert rapport.lignes["messages"] == 2 and rapport.lignes["audit"] >= 2
        await _verifier(sqlite, ids)
        # La nouvelle entrée d'audit se chaîne à la dernière copiée
        await audit.journaliser(sqlite, acteur="test", action="apres.copie")
        assert await audit.verifier(sqlite) is None
        # Message suivant : l'identifiant auto-incrémenté continue après les messages copiés
        suivant = await DepotConversations(sqlite).ajouter_message(ids["conversation"], "jarvis", "Encore")  # type: ignore[arg-type]
        assert suivant.id > max(m.id for m in await DepotConversations(pool_pg).messages(ids["conversation"]))  # type: ignore[arg-type]

        retour = await copier(sqlite, pg_vierge)
        assert retour.complet, retour.texte()
        await _verifier(pg_vierge, ids)
        await audit.journaliser(pg_vierge, acteur="test", action="apres.retour")
        assert await audit.verifier(pg_vierge) is None
        with pytest.raises(ErreurCopie, match="pas vide"):
            await copier(pool_pg, sqlite)
    finally:
        await sqlite.close()
