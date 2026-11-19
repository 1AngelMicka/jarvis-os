-- 025 — Empreinte des demandes et pile d'annulation (jumelle SQLite de la migration PostgreSQL 025).

ALTER TABLE demandes ADD COLUMN empreinte TEXT CHECK (empreinte IS NULL OR length(empreinte) = 64);

CREATE TABLE annulations (
    id         UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    action     TEXT NOT NULL,
    resume     TEXT NOT NULL,
    comment    TEXT NOT NULL,
    parametres JSONB NOT NULL DEFAULT '{}',
    resultat   JSONB NOT NULL DEFAULT '{}',
    demande_id UUID REFERENCES demandes (id) ON DELETE SET NULL,
    acteur     TEXT NOT NULL,
    statut     TEXT NOT NULL DEFAULT 'disponible' CHECK (statut IN ('disponible', 'annulee', 'echec', 'perimee')),
    cree_le    TIMESTAMPTZ NOT NULL DEFAULT (now()),
    expire_le  TIMESTAMPTZ NOT NULL,
    annule_le  TIMESTAMPTZ,
    annule_par TEXT,
    detail     TEXT
);
CREATE INDEX annulations_pile_idx ON annulations (statut, cree_le DESC);
