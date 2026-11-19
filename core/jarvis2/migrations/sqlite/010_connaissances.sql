-- 010 — Connaissances par domaine (jumelle SQLite de la migration PostgreSQL 010).

CREATE TABLE domaines (
    id          UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    nom         TEXT NOT NULL CHECK (length(nom) BETWEEN 1 AND 80),
    description TEXT NOT NULL DEFAULT '',
    mots_cles   JSONB NOT NULL DEFAULT '[]',
    prive       BOOLEAN NOT NULL DEFAULT FALSE,
    carte       TEXT NOT NULL DEFAULT '',
    niveau      INTEGER NOT NULL DEFAULT 0 CHECK (niveau BETWEEN 0 AND 10),
    lacunes     JSONB NOT NULL DEFAULT '[]',
    extrait_le  TIMESTAMPTZ,
    revu_le     TIMESTAMPTZ,
    cree_le     TIMESTAMPTZ NOT NULL DEFAULT (now()),
    maj_le      TIMESTAMPTZ NOT NULL DEFAULT (now())
);
CREATE UNIQUE INDEX domaines_nom_idx ON domaines (lower(nom));

CREATE TABLE fiches_concepts (
    id         UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    domaine_id UUID NOT NULL REFERENCES domaines (id) ON DELETE CASCADE,
    concept    TEXT NOT NULL CHECK (length(concept) BETWEEN 1 AND 120),
    contenu    TEXT NOT NULL,
    sources    JSONB NOT NULL DEFAULT '[]',
    maj_le     TIMESTAMPTZ NOT NULL DEFAULT (now()),
    UNIQUE (domaine_id, concept)
);

CREATE TABLE questions_controle (
    id         UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    domaine_id UUID NOT NULL REFERENCES domaines (id) ON DELETE CASCADE,
    question   TEXT NOT NULL,
    reponse    TEXT NOT NULL,
    sources    JSONB NOT NULL DEFAULT '[]',
    cree_le    TIMESTAMPTZ NOT NULL DEFAULT (now()),
    UNIQUE (domaine_id, question)
);

CREATE TABLE extractions_domaines (
    domaine_id UUID NOT NULL REFERENCES domaines (id) ON DELETE CASCADE,
    mission_id UUID NOT NULL REFERENCES missions (id) ON DELETE CASCADE,
    statut     TEXT NOT NULL DEFAULT 'en_attente' CHECK (statut IN ('en_attente', 'faite', 'echec')),
    erreur     TEXT,
    cree_le    TIMESTAMPTZ NOT NULL DEFAULT (now()),
    faite_le   TIMESTAMPTZ,
    PRIMARY KEY (domaine_id, mission_id)
);

CREATE TABLE journal_domaines (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    domaine_id UUID NOT NULL REFERENCES domaines (id) ON DELETE CASCADE,
    horodatage TIMESTAMPTZ NOT NULL DEFAULT (now()),
    type       TEXT NOT NULL CHECK (type IN ('creation', 'modification', 'extraction', 'report', 'revue', 'erreur')),
    resume     TEXT NOT NULL,
    contenu    JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX journal_domaines_idx ON journal_domaines (domaine_id, id DESC);
