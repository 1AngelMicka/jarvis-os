-- 008 — Mémoire v2 (jumelle SQLite de la migration PostgreSQL 008).

CREATE TABLE memoire_vecteurs (
    memoire_id UUID NOT NULL REFERENCES memoires (id) ON DELETE CASCADE,
    modele     TEXT NOT NULL,
    vecteur    VECTOR NOT NULL,
    cree_le    TIMESTAMPTZ NOT NULL DEFAULT (now()),
    PRIMARY KEY (memoire_id, modele)
);

ALTER TABLE memory_blocks ADD COLUMN confidentialite TEXT NOT NULL DEFAULT 'normal'
    CHECK (confidentialite IN ('normal', 'local_uniquement'));

INSERT INTO etat_systeme (cle, valeur) VALUES ('memoire_modele', '{}') ON CONFLICT (cle) DO NOTHING;
