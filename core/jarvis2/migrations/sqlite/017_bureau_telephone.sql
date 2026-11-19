-- 017 — Bureau et téléphone (jumelle SQLite de la migration PostgreSQL 017).

CREATE TABLE abonnements_push (
    id            UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    appareil_id   UUID NOT NULL REFERENCES appareils (id) ON DELETE CASCADE,
    endpoint      TEXT NOT NULL UNIQUE CHECK (length(endpoint) <= 1000),
    p256dh        TEXT NOT NULL CHECK (length(p256dh) <= 200),
    auth          TEXT NOT NULL CHECK (length(auth) <= 100),
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT (now()),
    dernier_envoi TIMESTAMPTZ,
    echecs        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE partages (
    id          UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    appareil_id UUID REFERENCES appareils (id) ON DELETE SET NULL,
    titre       TEXT NOT NULL DEFAULT '' CHECK (length(titre) <= 300),
    texte       TEXT NOT NULL DEFAULT '' CHECK (length(texte) <= 20000),
    url         TEXT NOT NULL DEFAULT '' CHECK (length(url) <= 2000),
    recu_le     TIMESTAMPTZ NOT NULL DEFAULT (now()),
    traite_le   TIMESTAMPTZ
);
CREATE INDEX partages_recu_idx ON partages (recu_le DESC);

CREATE TABLE liens_fichiers (
    id         UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    code_hash  TEXT NOT NULL UNIQUE,
    chemin     TEXT NOT NULL CHECK (length(chemin) <= 500),
    cree_par   UUID REFERENCES appareils (id) ON DELETE SET NULL,
    cree_le    TIMESTAMPTZ NOT NULL DEFAULT (now()),
    expire_le  TIMESTAMPTZ NOT NULL,
    utilise_le TIMESTAMPTZ
);

CREATE TABLE tentatives_jumelage (
    id     UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    source TEXT NOT NULL CHECK (length(source) <= 100),
    le     TIMESTAMPTZ NOT NULL DEFAULT (now())
);
CREATE INDEX tentatives_jumelage_le_idx ON tentatives_jumelage (le);

ALTER TABLE demandes ADD COLUMN rappel_le TIMESTAMPTZ;
ALTER TABLE demandes ADD COLUMN reports INTEGER NOT NULL DEFAULT 0;
