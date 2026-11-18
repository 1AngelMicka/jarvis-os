"""Import « jarvis_v1 » : base d'attente factice au schéma de JARVIS v1 -> base de test de JARVIS 2."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest

from jarvis2.config import Parametres
from jarvis2.config_locale import analyser
from jarvis2.db_postgres import BasePostgres
from jarvis2.importeurs.jarvis_v1 import importer

pytestmark = pytest.mark.base


@pytest.fixture
def pool(pool_pg: BasePostgres) -> BasePostgres:
    """Tests propres à PostgreSQL (rôles, droits, types, import) : jamais sur SQLite."""
    return pool_pg


ATTENTE_TEST = "import_jarvis_v1_test"
SCHEMA = Path(__file__).with_name("donnees") / "ancien_schema.sql"
VECTEUR = "[" + ",".join(["0.5", "-0.25"] + ["0"] * 382) + "]"

DONNEES = f"""
INSERT INTO memoires (id, contenu, type, tags, source, confidentialite, embedding, tsv, origine, canal_detail,
                      cree_le, maj_le)
VALUES ('11111111-1111-1111-1111-111111111111', 'L''utilisateur préfère le thé au café', 'fait', '{{noyau,gouts}}',
        NULL, 'local_uniquement', '{VECTEUR}', to_tsvector('french', 'thé café'), 'systeme', 'noyau',
        '2026-10-01 10:00+02', '2026-10-01 10:00+02'),
       ('22222222-2222-2222-2222-222222222222', 'Idée : un atelier de poterie', 'idee', '{{}}', 'interface', 'normal',
        NULL, to_tsvector('french', 'atelier poterie'), 'utilisateur', 'interface', '2026-10-02 10:00+02',
        '2026-10-02 10:00+02');
INSERT INTO conversations (id, titre, cree_le, maj_le, titre_source, epinglee, archivee, resume, resume_le,
                           resume_nb_messages, interne)
VALUES ('33333333-3333-3333-3333-333333333333', 'Thé', '2026-10-01', '2026-10-01', 'auto', true, false, 'Résumé', NULL,
        2, false);
INSERT INTO messages (id, conversation_id, role, contenu, horodatage, meta) VALUES
  (41, '33333333-3333-3333-3333-333333333333', 'utilisateur', 'Je préfère le thé', '2026-10-01 10:00+02', '{{}}'),
  (42, '33333333-3333-3333-3333-333333333333', 'jarvis', 'Noté, Monsieur.', '2026-10-01 10:01+02',
   '{{"modele": "claude-sonnet-5-5"}}');
INSERT INTO profil_reponses (question_id, reponse, commentaire, souvenir_id, cree_le, maj_le)
VALUES ('boisson', '"thé"', NULL, '11111111-1111-1111-1111-111111111111', now(), now());
INSERT INTO missions (id, type, objectif, parametres, statut, progression, etapes, resultat, erreur, cout_usd, acteur,
                      cree_le, demarre_le, termine_le)
VALUES ('55555555-5555-5555-5555-555555555555', 'recherche', 'Histoire du thé', '{{}}', 'terminee', 100, '[]',
        '{{"rapport": "…"}}', NULL, 0.12, 'utilisateur', now(), now(), now());
INSERT INTO creations (id, titre, description, version_courante, archive, cree_par, cree_le, maj_le)
VALUES ('66666666-6666-6666-6666-666666666666', 'Minuteur', NULL, 1, false, 'jarvis', now(), now());
INSERT INTO creation_versions (creation_id, version, html, demande, modele, avertissements, duree_ms, cree_le)
VALUES ('66666666-6666-6666-6666-666666666666', 1, '<p>minuteur</p>', 'un minuteur', NULL, '[]', 10, now());
INSERT INTO creation_donnees (id, creation_id, collection, donnees, cree_le, maj_le)
VALUES ('77777777-7777-7777-7777-777777777777', '66666666-6666-6666-6666-666666666666', 'reglages', '{{"s": 60}}',
        now(), now());
INSERT INTO taches (id, titre, description, categorie, statut, progression, etape_courante, etapes, responsable,
                    action_utilisateur, priorite, cree_par, cree_le, maj_le, termine_le, origine, type, proposition,
                    apercu, session_id, valide_par, motif, amelioration)
VALUES ('88888888-8888-8888-8888-888888888888', 'Ranger le garage', NULL, 'maison', 'a_faire', 0, NULL, '[]',
        'utilisateur', NULL, 2, 'jarvis', now(), '2026-10-03', NULL, 'jarvis', NULL, NULL, NULL, NULL, NULL, NULL,
        NULL);
"""


@pytest.fixture
async def url_attente(url_proprio: str, parametres: Parametres) -> AsyncIterator[str]:
    conn = await asyncpg.connect(url_proprio)
    try:
        await conn.execute(f"DROP DATABASE IF EXISTS {ATTENTE_TEST}")
        await conn.execute(f"CREATE DATABASE {ATTENTE_TEST}")
    finally:
        await conn.close()
    url = parametres.url_base("proprio", ATTENTE_TEST)
    conn = await asyncpg.connect(url)
    try:
        await conn.execute("CREATE EXTENSION vector")
        await conn.execute(SCHEMA.read_text(encoding="utf-8"))
        await conn.execute(DONNEES)
    finally:
        await conn.close()
    yield url


async def test_import_complet_et_fidele(url_attente: str, pool: BasePostgres, parametres: Parametres) -> None:
    url_app = parametres.url_base("app", "jarvis2_test")
    rapport = await importer(url_attente, url_app, "essai.dump", "abc")
    assert rapport.complet
    assert {t: c["source"] for t, c in rapport.comptes.items()} == {
        "memoires": 2,
        "conversations": 1,
        "messages": 2,
        "profil_reponses": 1,
        "missions": 1,
        "creations": 1,
        "creation_versions": 1,
        "creation_donnees": 1,
        "chantiers": 1,
    }
    assert all(c["nouveaux"] == c["source"] for c in rapport.comptes.values())

    # Mémoire : identifiant, vecteur, tags, confidentialité et dates intacts
    m = await pool.fetchrow(
        "SELECT tags, confidentialite, embedding::text AS v, cree_le, tsv::text AS tsv"
        " FROM memoires WHERE id = '11111111-1111-1111-1111-111111111111'"
    )
    assert m is not None
    assert m["tags"] == ["noyau", "gouts"] and m["confidentialite"] == "local_uniquement"
    assert m["v"].startswith("[0.5,-0.25,0,") and m["tsv"] == "'caf':2 'thé':1"
    assert await pool.fetchval("SELECT embedding IS NULL FROM memoires WHERE origine = 'utilisateur'") is True
    # Colonnes de la mémoire v2 : modèle du vecteur ligne par ligne, validité depuis la création
    v2 = await pool.fetch("SELECT embedding_model, valid_from = cree_le AS ok, valid_to FROM memoires ORDER BY id")
    assert [r["embedding_model"] for r in v2] == ["sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", None]
    assert all(r["ok"] and r["valid_to"] is None for r in v2)
    # Messages dans l'ordre, identifiant d'origine conservé, méta JSON intacte
    msgs = await pool.fetch("SELECT ancien_id, role, meta FROM messages ORDER BY id")
    assert [(r["ancien_id"], r["role"]) for r in msgs] == [(41, "utilisateur"), (42, "jarvis")]
    assert msgs[1]["meta"] == {"modele": "claude-sonnet-5-5"}
    assert await pool.fetchval("SELECT reponse FROM profil_reponses") == "thé"
    assert await pool.fetchval("SELECT titre FROM chantiers") == "Ranger le garage"
    journal_import = await pool.fetchrow("SELECT source, comptes FROM imports")
    assert journal_import is not None and journal_import["source"] == "jarvis_v1:essai.dump"


async def test_exclusions_de_la_configuration_locale(
    url_attente: str, pool: BasePostgres, parametres: Parametres
) -> None:
    """Données de tiers écartées : par source et par contenu, références nettoyées, rapport toujours complet."""
    config = analyser(
        {"import": {"jarvis_v1": {"exclure_sources": ["^interface$"], "exclure_contenus": ["thé"]}}}
    ).import_("jarvis_v1")
    rapport = await importer(url_attente, parametres.url_base("app", "jarvis2_test"), "x", "-", config.exclusions)
    assert rapport.complet
    assert rapport.comptes["memoires"] == {"source": 2, "presents": 0, "exclus": 2, "nouveaux": 0, "mis_a_jour": 0}
    assert rapport.comptes["messages"]["exclus"] == 1  # « Je préfère le thé »
    assert await pool.fetchval("SELECT count(*) FROM memoires") == 0
    assert [r["contenu"] for r in await pool.fetch("SELECT contenu FROM messages")] == ["Noté, Monsieur."]
    # La réponse de profil reste, sans lien vers le souvenir écarté
    assert await pool.fetchval("SELECT souvenir_id FROM profil_reponses") is None


def test_configuration_locale_invalide() -> None:
    with pytest.raises(ValueError, match="expression invalide"):
        analyser({"confidentialite": {"sujets_exclus": ["("]}})
    with pytest.raises(ValueError, match="liste"):
        analyser({"import": {"jarvis_v1": {"exclure_sources": "pas une liste"}}})
    assert analyser({}).import_("jarvis_v1").exclusions.exclut("doc:x", "y") is False


async def test_import_rejouable_et_rattrapage(url_attente: str, pool: BasePostgres, parametres: Parametres) -> None:
    url_app = parametres.url_base("app", "jarvis2_test")
    await importer(url_attente, url_app, "1", "-")
    # Rien n'a changé : aucun doublon, aucune mise à jour
    second = await importer(url_attente, url_app, "2", "-")
    assert second.complet
    assert all(c["nouveaux"] == 0 and c["mis_a_jour"] == 0 for c in second.comptes.values())
    assert await pool.fetchval("SELECT count(*) FROM messages") == 2
    # JARVIS v1 continue de vivre : nouveau message, chantier modifié -> rattrapés sans doublon
    conn = await asyncpg.connect(url_attente)
    try:
        await conn.execute(
            "INSERT INTO messages (id, conversation_id, role, contenu, horodatage, meta) VALUES"
            " (43, '33333333-3333-3333-3333-333333333333', 'utilisateur', 'Et le café ?', now(), '{}')"
        )
        await conn.execute("UPDATE taches SET statut = 'termine', maj_le = now()")
    finally:
        await conn.close()
    troisieme = await importer(url_attente, url_app, "3", "-")
    assert troisieme.comptes["messages"]["nouveaux"] == 1
    assert troisieme.comptes["chantiers"]["mis_a_jour"] == 1
    assert await pool.fetchval("SELECT statut FROM chantiers") == "termine"
    assert await pool.fetchval("SELECT count(*) FROM messages") == 3


async def test_import_tout_ou_rien(url_attente: str, pool: BasePostgres, parametres: Parametres) -> None:
    conn = await asyncpg.connect(url_attente)
    try:  # une colonne inconnue de JARVIS 2 : l'import doit refuser sans rien écrire
        await conn.execute("ALTER TABLE taches ADD COLUMN inconnue text")
    finally:
        await conn.close()
    with pytest.raises(RuntimeError, match="inconnue"):
        await importer(url_attente, parametres.url_base("app", "jarvis2_test"), "x", "-")
    assert await pool.fetchval("SELECT count(*) FROM memoires") == 0
    assert await pool.fetchval("SELECT count(*) FROM imports") == 0
