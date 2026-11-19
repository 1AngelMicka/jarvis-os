-- 026 — Home Assistant, le PC restant le cerveau (lot 14-D18) : connecteur, serveur Wyoming, satellites, profils.
-- Désactivés par défaut. Les jetons (OAuth, jeton longue durée), le code d'alarme et les clés des satellites ne sont
-- JAMAIS ici : jetons et code dans le coffre local, et seule l'empreinte SHA-256 de la clé de chaque satellite.

INSERT INTO etat_systeme (cle, valeur)
VALUES ('home_assistant', '{"actif": false, "adresse": null, "mode": "mcp"}'),
       ('wyoming', '{"actif": false, "hote": "127.0.0.1", "port": 10300, "clients": []}')
ON CONFLICT (cle) DO NOTHING;

-- Satellites vocaux (Home Assistant Voice, ESP32-S3 sous ESPHome…) : une clé par appareil, une pièce, un plafond
-- de volume ; `vu_le` et `personne` donnent la présence par pièce (dernière phrase entendue).
CREATE TABLE satellites_maison (
    id            text PRIMARY KEY CHECK (id ~ '^[a-z0-9-]{4,40}$'),
    nom           text NOT NULL CHECK (length(nom) BETWEEN 1 AND 60),
    piece         text NOT NULL CHECK (length(piece) BETWEEN 1 AND 60),
    empreinte_cle text NOT NULL CHECK (length(empreinte_cle) = 64),
    volume_max    integer NOT NULL DEFAULT 70 CHECK (volume_max BETWEEN 0 AND 100),
    actif         boolean NOT NULL DEFAULT true,
    cree_le       timestamptz NOT NULL DEFAULT now(),
    vu_le         timestamptz,
    personne      text CHECK (personne IS NULL OR length(personne) <= 60)
);

-- Profils par personne, liés à la reconnaissance de voix (empreintes dans le dossier des données, jamais ici)
CREATE TABLE profils_voix (
    id         text PRIMARY KEY CHECK (id ~ '^[a-z0-9-]{4,40}$'),
    nom        text NOT NULL CHECK (length(nom) BETWEEN 1 AND 60),
    volume_max integer NOT NULL DEFAULT 100 CHECK (volume_max BETWEEN 0 AND 100),
    cree_le    timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE, DELETE ON satellites_maison TO jarvis2_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON profils_voix TO jarvis2_app;
