-- 026 — Home Assistant, Wyoming, satellites, profils (jumelle SQLite de la migration PostgreSQL 026).

INSERT INTO etat_systeme (cle, valeur)
VALUES ('home_assistant', '{"actif": false, "adresse": null, "mode": "mcp"}'),
       ('wyoming', '{"actif": false, "hote": "127.0.0.1", "port": 10300, "clients": []}')
ON CONFLICT (cle) DO NOTHING;

CREATE TABLE satellites_maison (
    id            TEXT PRIMARY KEY CHECK (length(id) BETWEEN 4 AND 40),
    nom           TEXT NOT NULL CHECK (length(nom) BETWEEN 1 AND 60),
    piece         TEXT NOT NULL CHECK (length(piece) BETWEEN 1 AND 60),
    empreinte_cle TEXT NOT NULL CHECK (length(empreinte_cle) = 64),
    volume_max    INTEGER NOT NULL DEFAULT 70 CHECK (volume_max BETWEEN 0 AND 100),
    actif         BOOLEAN NOT NULL DEFAULT TRUE,
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT (now()),
    vu_le         TIMESTAMPTZ,
    personne      TEXT CHECK (personne IS NULL OR length(personne) <= 60)
);

CREATE TABLE profils_voix (
    id         TEXT PRIMARY KEY CHECK (length(id) BETWEEN 4 AND 40),
    nom        TEXT NOT NULL CHECK (length(nom) BETWEEN 1 AND 60),
    volume_max INTEGER NOT NULL DEFAULT 100 CHECK (volume_max BETWEEN 0 AND 100),
    cree_le    TIMESTAMPTZ NOT NULL DEFAULT (now())
);
