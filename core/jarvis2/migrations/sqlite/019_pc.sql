-- 019 — Ressources et contrôle du PC (jumelle SQLite de la migration PostgreSQL 019).

INSERT INTO etat_systeme (cle, valeur)
VALUES ('pc', '{"jeu": "automatique", "mode": "normal", "avant": null, "modifies": []}')
ON CONFLICT (cle) DO NOTHING;
