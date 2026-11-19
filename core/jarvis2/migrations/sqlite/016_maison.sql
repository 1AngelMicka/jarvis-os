-- 016 — Connecteurs maison facultatifs (jumelle SQLite de la migration PostgreSQL 016).

CREATE TABLE connecteurs_maison (
    id      TEXT PRIMARY KEY CHECK (id IN ('hue', 'obs')),
    actif   BOOLEAN NOT NULL DEFAULT FALSE,
    adresse TEXT CHECK (adresse IS NULL OR length(adresse) <= 120),
    maj_le  TIMESTAMPTZ NOT NULL DEFAULT (now())
);
