-- 032 — Missions « projet » en graphe de dépendances (lot 14 · B 10) : préparation (brainstorm, spécification,
-- plan à cases), validation par l'utilisateur, puis exécution des étapes (parallèles quand elles sont
-- indépendantes). Le graphe garde l'état d'exécution de chaque étape. Aucune donnée personnelle.

CREATE TABLE mission_plans (
    mission_id uuid PRIMARY KEY REFERENCES missions (id) ON DELETE CASCADE,
    phase      text NOT NULL CHECK (phase IN ('preparation', 'a_valider', 'execution', 'terminee', 'echec')),
    brainstorm text NOT NULL DEFAULT '',
    spec       text NOT NULL DEFAULT '',
    plan       text NOT NULL DEFAULT '',
    graphe     jsonb NOT NULL DEFAULT '{"etapes": []}',
    maj_le     timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE ON mission_plans TO jarvis2_app;

-- Réglages des missions : nombre d'étapes exécutées en même temps (le Core ne l'écrit que par UPDATE)
INSERT INTO etat_systeme (cle, valeur) VALUES ('missions', '{"parallele": 2}') ON CONFLICT (cle) DO NOTHING;
