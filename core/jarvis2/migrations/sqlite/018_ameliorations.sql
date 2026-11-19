-- 018 — Amélioration continue (jumelle SQLite de la migration PostgreSQL 018).

CREATE TABLE ameliorations (
    id             UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    titre          TEXT NOT NULL CHECK (length(titre) BETWEEN 1 AND 200),
    raison         TEXT NOT NULL CHECK (length(raison) BETWEEN 1 AND 2000),
    description    TEXT NOT NULL DEFAULT '' CHECK (length(description) <= 10000),
    origine        TEXT NOT NULL CHECK (origine IN ('jarvis', 'utilisateur')),
    projet         TEXT NOT NULL,
    statut         TEXT NOT NULL DEFAULT 'proposee'
        CHECK (statut IN ('proposee', 'en_atelier', 'en_service', 'retiree', 'rejetee')),
    atelier_id     UUID REFERENCES ateliers (id) ON DELETE SET NULL,
    tests          JSONB,
    commit_avant   TEXT,
    commit_service TEXT,
    commit_retour  TEXT,
    cree_par       TEXT NOT NULL,
    cree_le        TIMESTAMPTZ NOT NULL DEFAULT (now()),
    maj_le         TIMESTAMPTZ NOT NULL DEFAULT (now()),
    en_service_le  TIMESTAMPTZ,
    retiree_le     TIMESTAMPTZ
);
CREATE INDEX ameliorations_statut_idx ON ameliorations (statut, cree_le DESC);
