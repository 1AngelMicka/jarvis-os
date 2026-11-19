-- 022 — Voix, lot K3 (jumelle SQLite de la migration PostgreSQL 022).

INSERT INTO etat_systeme (cle, valeur)
VALUES ('proprietaire', '{"actif": false, "seuil": 0.5}'),
       ('dictee', '{"actif": false, "corrections": [], "styles": {}}')
ON CONFLICT (cle) DO NOTHING;
