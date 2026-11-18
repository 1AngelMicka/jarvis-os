-- 007 — Agents (jumelle SQLite de la migration PostgreSQL 007).

CREATE TABLE executions_recettes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    recette         TEXT NOT NULL,
    declencheur     TEXT NOT NULL CHECK (declencheur IN ('planification', 'manuel')),
    debut           TIMESTAMPTZ NOT NULL DEFAULT (now()),
    fin             TIMESTAMPTZ,
    statut          TEXT NOT NULL CHECK (statut IN ('en_cours', 'ok', 'erreur', 'ignoree')),
    conversation_id UUID REFERENCES conversations (id) ON DELETE SET NULL,
    resultat        TEXT,
    erreur          TEXT
);
CREATE INDEX executions_recettes_idx ON executions_recettes (recette, debut DESC);

CREATE TABLE outils_mcp (
    serveur TEXT NOT NULL,
    outil   TEXT NOT NULL,
    actif   BOOLEAN NOT NULL DEFAULT FALSE,
    maj_le  TIMESTAMPTZ NOT NULL DEFAULT (now()),
    PRIMARY KEY (serveur, outil)
);
