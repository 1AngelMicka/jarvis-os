-- 001 — Socle de JARVIS 2 : mémoire (compatible avec JARVIS v1), conversations, télémétrie.
-- Appliquée par le propriétaire (jarvis2_proprio). Le Core se connecte en jarvis2_app, qui n'a que des droits
-- sur les DONNÉES (aucun CREATE, ALTER, DROP, TRUNCATE) : il ne peut pas réécrire la structure.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Mémoire sémantique. Mêmes colonnes et mêmes valeurs que JARVIS v1 (migrations 001, 011, 012) :
-- les souvenirs et leurs vecteurs (fastembed paraphrase-multilingual-MiniLM-L12-v2, 384 dimensions)
-- s'importent tels quels en phase 3. `tsv` est calculé par le Core (to_tsvector('french', …)), comme avant.
CREATE TABLE memoires (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    contenu         text NOT NULL,
    type            text NOT NULL CHECK (type IN ('note', 'idee', 'decision', 'fait', 'projet')),
    tags            text[] NOT NULL DEFAULT '{}',
    source          text,
    confidentialite text NOT NULL DEFAULT 'normal' CHECK (confidentialite IN ('normal', 'local_uniquement')),
    embedding       vector(384),
    tsv             tsvector NOT NULL,
    origine         text NOT NULL DEFAULT 'autre'
        CHECK (origine IN ('conversation', 'mission', 'import_ia', 'import_google', 'profil', 'ecoute', 'creation',
                           'projet', 'systeme', 'utilisateur', 'connaissances', 'autre')),
    canal_detail    text,
    cree_le         timestamptz NOT NULL DEFAULT now(),
    maj_le          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX memoires_embedding_idx ON memoires USING hnsw (embedding vector_cosine_ops);
CREATE INDEX memoires_tsv_idx ON memoires USING gin (tsv);
CREATE INDEX memoires_tags_idx ON memoires USING gin (tags);
CREATE INDEX memoires_cree_le_idx ON memoires (cree_le DESC);
CREATE INDEX memoires_origine_idx ON memoires (origine, cree_le DESC);

-- Conversations (colonnes de JARVIS v1, migrations 001, 009 et 015, pour l'import de la phase 3)
CREATE TABLE conversations (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    titre              text NOT NULL,
    titre_source       text NOT NULL DEFAULT 'extrait' CHECK (titre_source IN ('extrait', 'auto', 'utilisateur')),
    epinglee           boolean NOT NULL DEFAULT false,
    archivee           boolean NOT NULL DEFAULT false,
    interne            boolean NOT NULL DEFAULT false,
    resume             text,
    resume_le          timestamptz,
    resume_nb_messages integer NOT NULL DEFAULT 0,
    cree_le            timestamptz NOT NULL DEFAULT now(),
    maj_le             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX conversations_liste_idx ON conversations (archivee, epinglee DESC, maj_le DESC);

CREATE TABLE messages (
    id              bigserial PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role            text NOT NULL CHECK (role IN ('utilisateur', 'jarvis')),
    contenu         text NOT NULL,
    horodatage      timestamptz NOT NULL DEFAULT now(),
    meta            jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX messages_conversation_idx ON messages (conversation_id, id);

-- Télémétrie des moteurs (idée d'OpenJarvis : InstrumentedEngine) : une ligne par appel.
CREATE TABLE telemetrie (
    id               bigserial PRIMARY KEY,
    moteur           text NOT NULL,
    modele           text,
    operation        text NOT NULL CHECK (operation IN ('generate', 'stream')),
    statut           text NOT NULL CHECK (statut IN ('ok', 'erreur', 'annule')),
    latence_ms       integer NOT NULL,
    premier_jeton_ms integer,
    jetons_entree    integer,
    jetons_sortie    integer,
    cout_usd         numeric(12, 6) NOT NULL DEFAULT 0,
    erreur           text,
    conversation_id  uuid REFERENCES conversations (id) ON DELETE SET NULL,
    meta             jsonb NOT NULL DEFAULT '{}',
    cree_le          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX telemetrie_cree_le_idx ON telemetrie (cree_le DESC);
CREATE INDEX telemetrie_moteur_idx ON telemetrie (moteur, cree_le DESC);

-- Droits du rôle applicatif : données seulement. La télémétrie est en ajout seul.
GRANT SELECT, INSERT, UPDATE, DELETE ON memoires, conversations, messages TO jarvis2_app;
GRANT SELECT, INSERT ON telemetrie TO jarvis2_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO jarvis2_app;
