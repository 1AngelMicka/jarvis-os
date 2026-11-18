-- 009 — Ateliers Claude Code (jumelle SQLite de la migration PostgreSQL 009).

CREATE TABLE ateliers (
    id         UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    projet     TEXT NOT NULL,
    nom        TEXT NOT NULL CHECK (length(nom) BETWEEN 1 AND 120),
    branche    TEXT NOT NULL,
    chemin     TEXT NOT NULL,
    statut     TEXT NOT NULL DEFAULT 'pret'
        CHECK (statut IN ('pret', 'en_cours', 'arrete', 'fusionne', 'abandonne', 'erreur')),
    session    TEXT,
    cree_par   TEXT NOT NULL,
    cree_le    TIMESTAMPTZ NOT NULL DEFAULT (now()),
    maj_le     TIMESTAMPTZ NOT NULL DEFAULT (now())
);
CREATE INDEX ateliers_projet_idx ON ateliers (projet, cree_le DESC);

CREATE TABLE evenements_atelier (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    atelier_id UUID NOT NULL REFERENCES ateliers (id) ON DELETE CASCADE,
    horodatage TIMESTAMPTZ NOT NULL DEFAULT (now()),
    type       TEXT NOT NULL,
    contenu    JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX evenements_atelier_idx ON evenements_atelier (atelier_id, id);
