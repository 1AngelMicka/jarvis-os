-- 017 — Bureau et téléphone : notifications Web Push, « Partager vers JARVIS », liens de fichiers à usage unique,
-- limite de tentatives au jumelage, « plus tard » sur une demande (rappel poussé au téléphone).
-- Les clés VAPID ne sont PAS en base : elles vivent dans le dossier des données (push/vapid.json), jamais dans git.

-- Abonnements Web Push d'un appareil (adresse du service de notification du navigateur + clés de chiffrement).
CREATE TABLE abonnements_push (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    appareil_id   uuid NOT NULL REFERENCES appareils (id) ON DELETE CASCADE,
    endpoint      text NOT NULL UNIQUE CHECK (length(endpoint) <= 1000),
    p256dh        text NOT NULL CHECK (length(p256dh) <= 200),
    auth          text NOT NULL CHECK (length(auth) <= 100),
    cree_le       timestamptz NOT NULL DEFAULT now(),
    dernier_envoi timestamptz,
    echecs        integer NOT NULL DEFAULT 0
);

-- Contenus reçus par « Partager vers JARVIS » : TOUJOURS non fiables (donnée, jamais instruction).
CREATE TABLE partages (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    appareil_id uuid REFERENCES appareils (id) ON DELETE SET NULL,
    titre       text NOT NULL DEFAULT '' CHECK (length(titre) <= 300),
    texte       text NOT NULL DEFAULT '' CHECK (length(texte) <= 20000),
    url         text NOT NULL DEFAULT '' CHECK (length(url) <= 2000),
    recu_le     timestamptz NOT NULL DEFAULT now(),
    traite_le   timestamptz
);
CREATE INDEX partages_recu_idx ON partages (recu_le DESC);

-- Liens de fichiers à usage unique (seule l'empreinte du code est gardée ; expiration courte).
CREATE TABLE liens_fichiers (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code_hash  text NOT NULL UNIQUE,
    chemin     text NOT NULL CHECK (length(chemin) <= 500),
    cree_par   uuid REFERENCES appareils (id) ON DELETE SET NULL,
    cree_le    timestamptz NOT NULL DEFAULT now(),
    expire_le  timestamptz NOT NULL,
    utilise_le timestamptz
);

-- Échecs d'échange d'un code de jumelage (limite par source et globale).
CREATE TABLE tentatives_jumelage (
    id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source text NOT NULL CHECK (length(source) <= 100),
    le     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX tentatives_jumelage_le_idx ON tentatives_jumelage (le);

-- « Plus tard » : la demande reste en attente, un rappel est poussé à `rappel_le` (3 reports au plus).
ALTER TABLE demandes ADD COLUMN rappel_le timestamptz;
ALTER TABLE demandes ADD COLUMN reports integer NOT NULL DEFAULT 0;

GRANT SELECT, INSERT, UPDATE, DELETE ON abonnements_push, partages, liens_fichiers, tentatives_jumelage TO jarvis2_app;
