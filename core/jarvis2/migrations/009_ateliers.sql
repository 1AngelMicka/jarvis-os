-- 009 — Ateliers Claude Code : un atelier = un worktree git d'un projet de l'utilisateur, sur sa propre branche.

CREATE TABLE ateliers (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    projet     text NOT NULL,
    nom        text NOT NULL CHECK (char_length(nom) BETWEEN 1 AND 120),
    branche    text NOT NULL,
    chemin     text NOT NULL,
    statut     text NOT NULL DEFAULT 'pret'
        CHECK (statut IN ('pret', 'en_cours', 'arrete', 'fusionne', 'abandonne', 'erreur')),
    session    text,               -- session Claude Code (reprise)
    cree_par   text NOT NULL,
    cree_le    timestamptz NOT NULL DEFAULT now(),
    maj_le     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ateliers_projet_idx ON ateliers (projet, cree_le DESC);

-- Fil de chaque atelier : consignes, messages et outils de Claude Code, décisions d'autorisation
CREATE TABLE evenements_atelier (
    id         bigserial PRIMARY KEY,
    atelier_id uuid NOT NULL REFERENCES ateliers (id) ON DELETE CASCADE,
    horodatage timestamptz NOT NULL DEFAULT now(),
    type       text NOT NULL,
    contenu    jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX evenements_atelier_idx ON evenements_atelier (atelier_id, id);

GRANT SELECT, INSERT, UPDATE ON ateliers TO jarvis2_app;
GRANT SELECT, INSERT ON evenements_atelier TO jarvis2_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO jarvis2_app;
