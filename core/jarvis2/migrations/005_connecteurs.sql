-- 005 — Connecteurs d'IA : état choisi par l'utilisateur (activé, conditions acceptées, membre du conseil).
-- Les clés d'API n'y sont JAMAIS : elles vivent dans le coffre local (securite/coffre.py).

CREATE TABLE connecteurs (
    id                      text PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9_-]{0,39}$'),
    actif                   boolean NOT NULL,
    dans_conseil            boolean NOT NULL DEFAULT false,
    conditions_version      text,                -- avertissement accepté (connecteurs à risque)
    conditions_acceptees_le timestamptz,
    maj_le                  timestamptz NOT NULL DEFAULT now(),
    CHECK (conditions_version IS NULL OR conditions_acceptees_le IS NOT NULL)
);

-- Choix imposé par conversation : le connecteur et le modèle retenus par l'utilisateur pour cette conversation
ALTER TABLE conversations ADD COLUMN connecteur text, ADD COLUMN modele text;

GRANT SELECT, INSERT, UPDATE ON connecteurs TO jarvis2_app;
