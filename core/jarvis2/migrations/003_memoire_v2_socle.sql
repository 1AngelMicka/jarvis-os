-- 003 — Préparation de la mémoire v2, sans rien recalculer ni effacer.
--
-- 1. Modèle d'embedding stocké ligne par ligne : le jour où l'on change de modèle (ex. 1024 dimensions), une
--    nouvelle colonne de vecteurs est ajoutée et remplie en tâche de fond, puis la recherche bascule. Aucun code ne
--    suppose une dimension : la recherche ne compare que les vecteurs produits par le modèle de l'encodeur actif.
-- 2. Validité temporelle et remplacement sans DELETE : un souvenir dépassé reçoit `valid_to` et `superseded_by`.
--    Par défaut la recherche ne voit que `valid_to IS NULL` et `NOT archived`.
-- 3. Oubli et consolidation : importance, accès, archivage, provenance (`derived_from`).
-- 4. Blocs de mémoire éditables (à la Letta) avec historique des versions. Le « noyau » reste pour l'instant le tag
--    `noyau` des souvenirs ; sa conversion en blocs est prévue avec la mémoire v2.

ALTER TABLE memoires
    ADD COLUMN embedding_model  text,
    ADD COLUMN valid_from       timestamptz,
    ADD COLUMN valid_to         timestamptz,
    ADD COLUMN superseded_by    uuid REFERENCES memoires (id) ON DELETE SET NULL,
    ADD COLUMN observed_at      timestamptz,
    ADD COLUMN importance       real NOT NULL DEFAULT 0.5 CHECK (importance BETWEEN 0 AND 1),
    ADD COLUMN last_accessed_at timestamptz,
    ADD COLUMN access_count     integer NOT NULL DEFAULT 0 CHECK (access_count >= 0),
    ADD COLUMN archived         boolean NOT NULL DEFAULT false,
    ADD COLUMN derived_from     uuid[] NOT NULL DEFAULT '{}';

-- Jusqu'ici, tous les vecteurs venaient du modèle par défaut (384 dimensions) ; dates d'observation = création.
UPDATE memoires SET embedding_model = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
    WHERE embedding IS NOT NULL;
UPDATE memoires SET valid_from = cree_le, observed_at = cree_le;

ALTER TABLE memoires
    ADD CONSTRAINT memoires_validite_check CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    ADD CONSTRAINT memoires_embedding_model_check CHECK (embedding IS NULL OR embedding_model IS NOT NULL);

CREATE INDEX memoires_actifs_idx ON memoires (cree_le DESC) WHERE valid_to IS NULL AND NOT archived;

CREATE TABLE memory_blocks (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    label      text NOT NULL UNIQUE CHECK (label ~ '^[a-z0-9][a-z0-9_.:-]{0,63}$'),
    content    text NOT NULL DEFAULT '',
    char_limit integer NOT NULL DEFAULT 2000 CHECK (char_limit > 0),
    version    integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    cree_le    timestamptz NOT NULL DEFAULT now(),
    maj_le     timestamptz NOT NULL DEFAULT now(),
    CHECK (char_length(content) <= char_limit)
);

-- Historique : chaque version d'un bloc est gardée (ajout seul pour le rôle applicatif)
CREATE TABLE memory_block_versions (
    block_id   uuid NOT NULL REFERENCES memory_blocks (id) ON DELETE CASCADE,
    version    integer NOT NULL,
    content    text NOT NULL,
    auteur     text NOT NULL DEFAULT 'jarvis',
    cree_le    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (block_id, version)
);

GRANT SELECT, INSERT, UPDATE ON memory_blocks TO jarvis2_app;
GRANT SELECT, INSERT ON memory_block_versions TO jarvis2_app;
