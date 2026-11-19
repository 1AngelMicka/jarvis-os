-- 033 — Mises à jour : vérification quotidienne des nouvelles versions (désactivable) et dernière version connue.
INSERT INTO etat_systeme (cle, valeur) VALUES ('mises_a_jour', '{"verifier": true}') ON CONFLICT (cle) DO NOTHING;
