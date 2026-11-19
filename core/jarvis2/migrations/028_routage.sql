-- 028 — Routeur par type de tâche (14 · B 11) : route par type (code, raisonnement, rapide, privé), petit modèle de
-- classement facultatif, mesures ignorées avant un rétablissement, rétrogradations en cours et leur historique.
-- Scores : table telemetrie (meta.route) ; avis de l'utilisateur : lignes operation = 'retour' (contraintes élargies).
INSERT INTO etat_systeme (cle, valeur)
VALUES ('routage', '{"routes": {}, "classifieur": null, "retablies": {}, "actives": {}, "historique": []}')
ON CONFLICT (cle) DO NOTHING;

-- Avis de l'utilisateur sur une réponse routée : une ligne de télémétrie de plus (table toujours en ajout seul).
ALTER TABLE telemetrie DROP CONSTRAINT telemetrie_operation_check;
ALTER TABLE telemetrie ADD CONSTRAINT telemetrie_operation_check
    CHECK (operation IN ('generate', 'stream', 'retour'));
ALTER TABLE telemetrie DROP CONSTRAINT telemetrie_statut_check;
ALTER TABLE telemetrie ADD CONSTRAINT telemetrie_statut_check
    CHECK (statut IN ('ok', 'erreur', 'annule', 'positif', 'negatif', 'retire'));
