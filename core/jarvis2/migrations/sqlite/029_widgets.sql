-- 029 — Widgets épinglés dans le HUD (jumelle SQLite de la migration PostgreSQL 029).

CREATE TABLE widgets_epingles (
    id        UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    empreinte TEXT NOT NULL UNIQUE CHECK (length(empreinte) BETWEEN 8 AND 64),
    titre     TEXT NOT NULL CHECK (length(titre) BETWEEN 1 AND 60),
    html      TEXT NOT NULL CHECK (length(html) BETWEEN 1 AND 8000),
    cree_le   TIMESTAMPTZ NOT NULL DEFAULT (now())
);
