-- 032 — Missions « projet » en graphe de dépendances (jumelle SQLite de la migration PostgreSQL 032).

CREATE TABLE mission_plans (
    mission_id UUID PRIMARY KEY REFERENCES missions (id) ON DELETE CASCADE,
    phase      TEXT NOT NULL CHECK (phase IN ('preparation', 'a_valider', 'execution', 'terminee', 'echec')),
    brainstorm TEXT NOT NULL DEFAULT '',
    spec       TEXT NOT NULL DEFAULT '',
    plan       TEXT NOT NULL DEFAULT '',
    graphe     JSONB NOT NULL DEFAULT '{"etapes": []}',
    maj_le     TIMESTAMPTZ NOT NULL DEFAULT (now())
);

INSERT INTO etat_systeme (cle, valeur) VALUES ('missions', '{"parallele": 2}') ON CONFLICT (cle) DO NOTHING;
