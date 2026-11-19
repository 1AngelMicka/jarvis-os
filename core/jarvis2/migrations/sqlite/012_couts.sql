-- 012 — Coûts et transparence (jumelle SQLite de la migration PostgreSQL 012).

ALTER TABLE connecteurs ADD COLUMN plafond_mensuel_usd REAL
    CHECK (plafond_mensuel_usd IS NULL OR plafond_mensuel_usd >= 0);
