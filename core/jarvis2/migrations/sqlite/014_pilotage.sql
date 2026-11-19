-- 014 — JARVIS pilote l'interface (jumelle SQLite de la migration PostgreSQL 014).

CREATE TABLE regles_protection (
    id       UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    genre    TEXT NOT NULL CHECK (genre IN ('interdire', 'demander')),
    motif    TEXT NOT NULL CHECK (length(motif) BETWEEN 2 AND 200),
    libelle  TEXT NOT NULL CHECK (length(libelle) BETWEEN 1 AND 200),
    origine  TEXT NOT NULL DEFAULT 'utilisateur' CHECK (origine IN ('utilisateur', 'jarvis')),
    cree_par TEXT NOT NULL,
    cree_le  TIMESTAMPTZ NOT NULL DEFAULT (now())
);

CREATE TABLE commandes_rapides (
    id                   UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    motif                TEXT NOT NULL CHECK (length(motif) BETWEEN 2 AND 200),
    cible                TEXT NOT NULL CHECK (cible IN ('interface', 'core')),
    action               TEXT NOT NULL CHECK (length(action) BETWEEN 1 AND 80),
    parametres           JSONB NOT NULL DEFAULT '{}',
    priorite             INTEGER NOT NULL DEFAULT 0 CHECK (priorite BETWEEN -100 AND 100),
    phrase_test          TEXT NOT NULL CHECK (length(phrase_test) BETWEEN 1 AND 200),
    actif                BOOLEAN NOT NULL DEFAULT TRUE,
    utilisations         INTEGER NOT NULL DEFAULT 0,
    derniere_utilisation TIMESTAMPTZ,
    cree_le              TIMESTAMPTZ NOT NULL DEFAULT (now()),
    maj_le               TIMESTAMPTZ NOT NULL DEFAULT (now())
);

CREATE TABLE autorisations_permanentes (
    action               TEXT PRIMARY KEY,
    cree_par             UUID REFERENCES appareils (id) ON DELETE SET NULL,
    cree_le              TIMESTAMPTZ NOT NULL DEFAULT (now()),
    utilisations         INTEGER NOT NULL DEFAULT 0,
    derniere_utilisation TIMESTAMPTZ
);

INSERT INTO etat_systeme (cle, valeur) VALUES ('pilotage', '{"mode": "demander"}') ON CONFLICT (cle) DO NOTHING;
