-- 028 — Routeur par type de tâche (14 · B 11) : route par type (code, raisonnement, rapide, privé), petit modèle de
-- classement facultatif, mesures ignorées avant un rétablissement, rétrogradations en cours et leur historique.
-- Scores : table telemetrie (meta.route) ; avis de l'utilisateur : lignes operation = 'retour' (contraintes élargies).
INSERT INTO etat_systeme (cle, valeur)
VALUES ('routage', '{"routes": {}, "classifieur": null, "retablies": {}, "actives": {}, "historique": []}')
ON CONFLICT (cle) DO NOTHING;

-- Avis de l'utilisateur sur une réponse routée : une ligne de télémétrie de plus. SQLite ne modifie pas une
-- contrainte CHECK : la table est reconstruite à l'identique, contraintes élargies, données gardées.
CREATE TABLE telemetrie_028 (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    moteur           TEXT NOT NULL,
    modele           TEXT,
    operation        TEXT NOT NULL CHECK (operation IN ('generate', 'stream', 'retour')),
    statut           TEXT NOT NULL CHECK (statut IN ('ok', 'erreur', 'annule', 'positif', 'negatif', 'retire')),
    latence_ms       INTEGER NOT NULL,
    premier_jeton_ms INTEGER,
    jetons_entree    INTEGER,
    jetons_sortie    INTEGER,
    cout_usd         REAL NOT NULL DEFAULT 0,
    erreur           TEXT,
    conversation_id  UUID REFERENCES conversations (id) ON DELETE SET NULL,
    meta             JSONB NOT NULL DEFAULT '{}',
    cree_le          TIMESTAMPTZ NOT NULL DEFAULT (now())
);
INSERT INTO telemetrie_028 SELECT id, moteur, modele, operation, statut, latence_ms, premier_jeton_ms, jetons_entree,
    jetons_sortie, cout_usd, erreur, conversation_id, meta, cree_le FROM telemetrie;
DROP TABLE telemetrie;
ALTER TABLE telemetrie_028 RENAME TO telemetrie;
CREATE INDEX telemetrie_cree_le_idx ON telemetrie (cree_le DESC);
CREATE INDEX telemetrie_moteur_idx ON telemetrie (moteur, cree_le DESC);
