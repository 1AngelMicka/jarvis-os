-- 013 — Accord images vers le cloud (jumelle SQLite de la migration PostgreSQL 013).

ALTER TABLE connecteurs ADD COLUMN images_accordees_le TIMESTAMPTZ;
