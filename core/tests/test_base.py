"""Socle : migrations, schéma mémoire compatible avec l'ancien JARVIS, séparation des rôles."""

from __future__ import annotations

import asyncpg
import pytest

from jarvis2.conversations import DepotConversations, titre_provisoire
from jarvis2.db import appliquer_migrations, lister_migrations

pytestmark = pytest.mark.base


async def test_migrations_idempotentes(url_proprio: str, pool: asyncpg.Pool) -> None:
    assert await appliquer_migrations(url_proprio) == []
    versions = [r["version"] for r in await pool.fetch("SELECT version FROM schema_migrations ORDER BY 1")]
    assert versions == [v for v, _ in lister_migrations()]


async def test_schema_memoires_compatible(pool: asyncpg.Pool) -> None:
    colonnes = {
        r["column_name"]: r["udt_name"]
        for r in await pool.fetch(
            "SELECT column_name, udt_name FROM information_schema.columns WHERE table_name = 'memoires'"
        )
    }
    assert colonnes == {
        "id": "uuid",
        "contenu": "text",
        "type": "text",
        "tags": "_text",
        "source": "text",
        "confidentialite": "text",
        "embedding": "vector",
        "tsv": "tsvector",
        "origine": "text",
        "canal_detail": "text",
        "cree_le": "timestamptz",
        "maj_le": "timestamptz",
    }
    dimension = await pool.fetchval(
        "SELECT atttypmod FROM pg_attribute WHERE attrelid = 'memoires'::regclass AND attname = 'embedding'"
    )
    assert dimension == 384
    index = await pool.fetchval("SELECT indexdef FROM pg_indexes WHERE indexname = 'memoires_embedding_idx'")
    assert "hnsw" in index and "vector_cosine_ops" in index


async def test_memoire_vecteur_et_texte_francais(pool: asyncpg.Pool) -> None:
    vecteur = [1.0] + [0.0] * 383
    await pool.execute(
        "INSERT INTO memoires (contenu, type, tags, confidentialite, embedding, tsv, origine)"
        " VALUES ($1, 'fait', $2, 'local_uniquement', $3, to_tsvector('french', $1), 'utilisateur')",
        "Les chevaux mangent du foin",
        ["test"],
        vecteur,
    )
    ligne = await pool.fetchrow(
        "SELECT contenu, embedding <=> $1 AS distance FROM memoires"
        " WHERE tsv @@ plainto_tsquery('french', 'cheval et foin')",
        vecteur,
    )
    assert ligne is not None and ligne["distance"] == pytest.approx(0.0)


@pytest.mark.parametrize(
    "instruction",
    [
        "CREATE TABLE intrus (x int)",
        "ALTER TABLE memoires ADD COLUMN intrus int",
        "DROP TABLE telemetrie",
        "TRUNCATE memoires",
        "DELETE FROM telemetrie",
        "UPDATE telemetrie SET statut = 'ok'",
        "INSERT INTO schema_migrations (version) VALUES ('999_intrus')",
    ],
)
async def test_role_applicatif_sans_droit_de_structure(pool: asyncpg.Pool, instruction: str) -> None:
    assert await pool.fetchval("SELECT current_user") == "jarvis2_app"
    with pytest.raises(asyncpg.PostgresError):
        await pool.execute(instruction)


async def test_conversations(pool: asyncpg.Pool) -> None:
    depot = DepotConversations(pool)
    conv = await depot.creer("Essai")
    await depot.ajouter_message(conv.id, "utilisateur", "Bonjour")
    await depot.ajouter_message(conv.id, "jarvis", "Bonjour, Monsieur.", {"moteur": "faux"})
    messages = await depot.messages(conv.id)
    assert [(m.role, m.contenu) for m in messages] == [("utilisateur", "Bonjour"), ("jarvis", "Bonjour, Monsieur.")]
    assert messages[1].meta == {"moteur": "faux"}
    (liste,) = await depot.lister()
    assert liste.id == conv.id and liste.nb_messages == 2
    with pytest.raises(asyncpg.PostgresError):
        await depot.ajouter_message(conv.id, "systeme", "rôle interdit")


def test_titre_provisoire() -> None:
    assert titre_provisoire("  Bonjour   JARVIS ") == "Bonjour JARVIS"
    long = titre_provisoire("mot " * 40)
    assert long.endswith("…") and len(long) <= 61
    assert titre_provisoire("") == "Nouvelle conversation"
