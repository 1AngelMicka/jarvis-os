-- 002 — Données héritées de JARVIS v1 : profil, missions, créations, chantiers, journal des imports.
-- Mêmes colonnes et mêmes contraintes que l'ancien Core (lu le 18 nov. 2026 dans sa sauvegarde) : les lignes
-- s'importent telles quelles, identifiants compris. Les modules qui s'en serviront arrivent en phases 5 à 7.

-- Messages importés : identifiant d'origine, pour qu'un nouvel import (rattrapage, phase 9) ne les double pas.
ALTER TABLE messages ADD COLUMN ancien_id bigint;
CREATE UNIQUE INDEX messages_ancien_id_idx ON messages (ancien_id) WHERE ancien_id IS NOT NULL;

-- Profil : une réponse par question (questions : jarvis2/donnees/profil_questions.json)
CREATE TABLE profil_reponses (
    question_id text PRIMARY KEY,
    reponse     jsonb NOT NULL,
    commentaire text,
    souvenir_id uuid REFERENCES memoires (id) ON DELETE SET NULL,
    cree_le     timestamptz NOT NULL DEFAULT now(),
    maj_le      timestamptz NOT NULL DEFAULT now()
);

-- Missions de fond (recherche, brainstorm, revue)
CREATE TABLE missions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    type        text NOT NULL,
    objectif    text NOT NULL,
    parametres  jsonb NOT NULL DEFAULT '{}',
    statut      text NOT NULL CHECK (statut IN ('en_file', 'en_cours', 'terminee', 'echec', 'annulee')),
    progression smallint NOT NULL DEFAULT 0 CHECK (progression BETWEEN 0 AND 100),
    etapes      jsonb NOT NULL DEFAULT '[]',
    resultat    jsonb,
    erreur      text,
    cout_usd    numeric,
    acteur      text NOT NULL,
    cree_le     timestamptz NOT NULL DEFAULT now(),
    demarre_le  timestamptz,
    termine_le  timestamptz
);
CREATE INDEX missions_cree_le_idx ON missions (cree_le DESC);
CREATE INDEX missions_statut_idx ON missions (statut, cree_le);

-- Créations (pages en bac à sable), leurs versions et leurs données
CREATE TABLE creations (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    titre            text NOT NULL CHECK (char_length(titre) BETWEEN 1 AND 200),
    description      text,
    version_courante integer NOT NULL DEFAULT 0 CHECK (version_courante >= 0),
    archive          boolean NOT NULL DEFAULT false,
    cree_par         text NOT NULL,
    cree_le          timestamptz NOT NULL DEFAULT now(),
    maj_le           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX creations_liste_idx ON creations (archive, maj_le DESC);

CREATE TABLE creation_versions (
    creation_id    uuid NOT NULL REFERENCES creations (id) ON DELETE CASCADE,
    version        integer NOT NULL CHECK (version >= 1),
    html           text NOT NULL,
    demande        text NOT NULL,
    modele         text,
    avertissements jsonb NOT NULL DEFAULT '[]',
    duree_ms       integer,
    cree_le        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (creation_id, version)
);

CREATE TABLE creation_donnees (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    creation_id uuid NOT NULL REFERENCES creations (id) ON DELETE CASCADE,
    collection  text NOT NULL CHECK (collection ~ '^[A-Za-z0-9_-]{1,64}$'),
    donnees     jsonb NOT NULL,
    cree_le     timestamptz NOT NULL DEFAULT now(),
    maj_le      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX creation_donnees_idx ON creation_donnees (creation_id, collection, cree_le);

-- Chantiers (table « taches » de JARVIS v1). `session_id` désignait une session d'atelier de l'ancien
-- JARVIS : gardé tel quel, sans clé étrangère (les ateliers sont refaits en phase 6).
CREATE TABLE chantiers (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    titre              text NOT NULL CHECK (char_length(titre) BETWEEN 1 AND 300),
    description        text,
    categorie          text NOT NULL,
    statut             text NOT NULL CHECK (statut IN ('propose', 'a_faire', 'en_cours', 'en_attente_utilisateur',
                                                       'termine', 'bloque', 'abandonne')),
    progression        smallint NOT NULL DEFAULT 0 CHECK (progression BETWEEN 0 AND 100),
    etape_courante     text,
    etapes             jsonb NOT NULL DEFAULT '[]',
    responsable        text NOT NULL,
    action_utilisateur text,
    priorite           smallint NOT NULL DEFAULT 2 CHECK (priorite BETWEEN 1 AND 3),
    cree_par           text NOT NULL,
    cree_le            timestamptz NOT NULL DEFAULT now(),
    maj_le             timestamptz NOT NULL DEFAULT now(),
    termine_le         timestamptz,
    origine            text NOT NULL CHECK (origine IN ('utilisateur', 'jarvis', 'claude')),
    type               text CHECK (type IS NULL OR type ~ '^[a-z0-9][a-z0-9_-]{0,39}$'),
    proposition        jsonb,
    apercu             jsonb,
    session_id         uuid,
    valide_par         text,
    motif              text,
    amelioration       jsonb
);
CREATE INDEX chantiers_statut_idx ON chantiers (statut, priorite, maj_le DESC);

-- Journal des imports : d'où viennent les données, et combien (ajout seul pour le rôle applicatif)
CREATE TABLE imports (
    id          bigserial PRIMARY KEY,
    source      text NOT NULL,
    empreinte   text NOT NULL,           -- SHA-256 du fichier importé
    comptes     jsonb NOT NULL,          -- {table: {"source": n, "importes": n, "nouveaux": n}}
    cree_le     timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE, DELETE ON profil_reponses, missions, creations, creation_versions, creation_donnees,
    chantiers TO jarvis2_app;
GRANT SELECT, INSERT ON imports TO jarvis2_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO jarvis2_app;
