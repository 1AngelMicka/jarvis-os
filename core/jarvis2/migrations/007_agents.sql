-- 007 — Agents : exécutions des recettes planifiées, interrupteur par outil MCP.
-- Les missions utilisent la table « missions » (migration 002).

CREATE TABLE executions_recettes (
    id              bigserial PRIMARY KEY,
    recette         text NOT NULL,
    declencheur     text NOT NULL CHECK (declencheur IN ('planification', 'manuel')),
    debut           timestamptz NOT NULL DEFAULT now(),
    fin             timestamptz,
    statut          text NOT NULL CHECK (statut IN ('en_cours', 'ok', 'erreur', 'ignoree')),
    conversation_id uuid REFERENCES conversations (id) ON DELETE SET NULL,
    resultat        text,
    erreur          text
);
CREATE INDEX executions_recettes_idx ON executions_recettes (recette, debut DESC);

-- Un outil MCP ne peut être appelé que s'il est activé ici (inactif par défaut), et toujours après approbation
CREATE TABLE outils_mcp (
    serveur text NOT NULL,
    outil   text NOT NULL,
    actif   boolean NOT NULL DEFAULT false,
    maj_le  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (serveur, outil)
);

GRANT SELECT, INSERT, UPDATE ON executions_recettes, outils_mcp TO jarvis2_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO jarvis2_app;
