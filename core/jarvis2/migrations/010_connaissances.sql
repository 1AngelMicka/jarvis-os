-- 010 — Connaissances par domaine : carte conceptuelle, fiches par concept, questions de contrôle, niveau, journal.
-- Carte, fiches et questions sont aussi rangées en mémoire (origine « connaissances »), resynchronisées à chaque
-- extraction. Un domaine privé n'est traité que par une IA locale et reste « local_uniquement » en mémoire.

CREATE TABLE domaines (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    nom         text NOT NULL CHECK (char_length(nom) BETWEEN 1 AND 80),
    description text NOT NULL DEFAULT '',
    mots_cles   jsonb NOT NULL DEFAULT '[]',   -- termes qui signalent le domaine (missions, dialogue)
    prive       boolean NOT NULL DEFAULT false,
    carte       text NOT NULL DEFAULT '',      -- carte conceptuelle (Markdown)
    niveau      smallint NOT NULL DEFAULT 0 CHECK (niveau BETWEEN 0 AND 10),
    lacunes     jsonb NOT NULL DEFAULT '[]',
    extrait_le  timestamptz,
    revu_le     timestamptz,
    cree_le     timestamptz NOT NULL DEFAULT now(),
    maj_le      timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX domaines_nom_idx ON domaines (lower(nom));

CREATE TABLE fiches_concepts (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    domaine_id uuid NOT NULL REFERENCES domaines (id) ON DELETE CASCADE,
    concept    text NOT NULL CHECK (char_length(concept) BETWEEN 1 AND 120),
    contenu    text NOT NULL,
    sources    jsonb NOT NULL DEFAULT '[]',     -- [{titre, url}] : toujours issues des missions, jamais inventées
    maj_le     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (domaine_id, concept)
);

CREATE TABLE questions_controle (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    domaine_id uuid NOT NULL REFERENCES domaines (id) ON DELETE CASCADE,
    question   text NOT NULL,
    reponse    text NOT NULL,
    sources    jsonb NOT NULL DEFAULT '[]',
    cree_le    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (domaine_id, question)
);

-- Missions de recherche à verser dans un domaine : en attente (aucune IA disponible), faites ou en échec
CREATE TABLE extractions_domaines (
    domaine_id uuid NOT NULL REFERENCES domaines (id) ON DELETE CASCADE,
    mission_id uuid NOT NULL REFERENCES missions (id) ON DELETE CASCADE,
    statut     text NOT NULL DEFAULT 'en_attente' CHECK (statut IN ('en_attente', 'faite', 'echec')),
    erreur     text,
    cree_le    timestamptz NOT NULL DEFAULT now(),
    faite_le   timestamptz,
    PRIMARY KEY (domaine_id, mission_id)
);

-- Journal de chaque domaine : création, extractions, reports, révisions (score, lacunes, missions suggérées)
CREATE TABLE journal_domaines (
    id         bigserial PRIMARY KEY,
    domaine_id uuid NOT NULL REFERENCES domaines (id) ON DELETE CASCADE,
    horodatage timestamptz NOT NULL DEFAULT now(),
    type       text NOT NULL CHECK (type IN ('creation', 'modification', 'extraction', 'report', 'revue', 'erreur')),
    resume     text NOT NULL,
    contenu    jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX journal_domaines_idx ON journal_domaines (domaine_id, id DESC);

GRANT SELECT, INSERT, UPDATE ON domaines, fiches_concepts, questions_controle, extractions_domaines TO jarvis2_app;
GRANT DELETE ON fiches_concepts, questions_controle TO jarvis2_app;
GRANT SELECT, INSERT ON journal_domaines TO jarvis2_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO jarvis2_app;
