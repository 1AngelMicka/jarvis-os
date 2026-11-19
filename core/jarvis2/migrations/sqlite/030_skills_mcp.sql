-- 030 — Skills SKILL.md et réglages du client MCP (jumelle SQLite de la migration PostgreSQL 030).

CREATE TABLE skills (
    id                   UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    nom                  TEXT NOT NULL UNIQUE CHECK (length(nom) BETWEEN 1 AND 64),
    description          TEXT NOT NULL CHECK (length(description) BETWEEN 1 AND 1024),
    origine              TEXT NOT NULL CHECK (origine IN ('dossier', 'archive')),
    source               TEXT NOT NULL CHECK (length(source) <= 500),
    dossier              TEXT NOT NULL,
    confiance            TEXT NOT NULL DEFAULT 'non_fiable'
        CHECK (confiance IN ('non_fiable', 'instructions', 'capacites')),
    statut               TEXT NOT NULL DEFAULT 'a_revoir' CHECK (statut IN ('a_revoir', 'approuve', 'bloque')),
    capacites            JSONB NOT NULL DEFAULT '[]',
    capacites_acceptees  JSONB NOT NULL DEFAULT '[]',
    fichiers             JSONB NOT NULL DEFAULT '[]',
    empreinte            TEXT NOT NULL,
    empreinte_approuvee  TEXT,
    raison_blocage       TEXT,
    importe_par          TEXT NOT NULL,
    approuve_par         TEXT,
    cree_le              TIMESTAMPTZ NOT NULL DEFAULT (now()),
    maj_le               TIMESTAMPTZ NOT NULL DEFAULT (now()),
    approuve_le          TIMESTAMPTZ,
    bloque_le            TIMESTAMPTZ
);
CREATE INDEX skills_statut_idx ON skills (statut, nom);

INSERT INTO etat_systeme (cle, valeur)
VALUES ('mcp', '{"max_outils": 8, "par_le_sens": true, "relance_auto": true}')
ON CONFLICT (cle) DO NOTHING;
