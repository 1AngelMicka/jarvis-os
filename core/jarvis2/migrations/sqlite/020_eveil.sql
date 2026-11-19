-- 020 — Éveil « Dis Jarvis » (jumelle SQLite de la migration PostgreSQL 020).

INSERT INTO etat_systeme (cle, valeur)
VALUES ('eveil', '{"ambiance": false, "openwakeword": false, "relance_s": 6}')
ON CONFLICT (cle) DO NOTHING;
