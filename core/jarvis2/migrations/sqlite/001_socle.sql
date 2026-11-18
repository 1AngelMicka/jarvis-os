-- SQLite — schéma de JARVIS 2, équivalent des migrations PostgreSQL 001 à 005 (le fichier SQLite démarre à neuf).
-- Types déclarés lus par db_sqlite.py : UUID, TIMESTAMPTZ, BOOLEAN, JSONB, TEXTLIST, UUIDLIST, VECTOR.
-- now(), gen_random_uuid() et regexp sont des fonctions de l'application, ajoutées à chaque connexion.
-- Pas de rôles dans SQLite : la protection de l'audit tient aux déclencheurs et à la chaîne d'empreintes
-- (voir docs/DECISIONS.md, « Stockage »).

-- --- Mémoire ------------------------------------------------------------------------------------------------
CREATE TABLE memoires (
    id               UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    contenu          TEXT NOT NULL,
    type             TEXT NOT NULL CHECK (type IN ('note', 'idee', 'decision', 'fait', 'projet')),
    tags             TEXTLIST NOT NULL DEFAULT '[]',
    source           TEXT,
    confidentialite  TEXT NOT NULL DEFAULT 'normal' CHECK (confidentialite IN ('normal', 'local_uniquement')),
    embedding        VECTOR,
    origine          TEXT NOT NULL DEFAULT 'autre'
        CHECK (origine IN ('conversation', 'mission', 'import_ia', 'import_google', 'profil', 'ecoute', 'creation',
                           'projet', 'systeme', 'utilisateur', 'connaissances', 'autre')),
    canal_detail     TEXT,
    cree_le          TIMESTAMPTZ NOT NULL DEFAULT (now()),
    maj_le           TIMESTAMPTZ NOT NULL DEFAULT (now()),
    embedding_model  TEXT,
    valid_from       TIMESTAMPTZ,
    valid_to         TIMESTAMPTZ,
    superseded_by    UUID REFERENCES memoires (id) ON DELETE SET NULL,
    observed_at      TIMESTAMPTZ,
    importance       REAL NOT NULL DEFAULT 0.5 CHECK (importance BETWEEN 0 AND 1),
    last_accessed_at TIMESTAMPTZ,
    access_count     INTEGER NOT NULL DEFAULT 0 CHECK (access_count >= 0),
    archived         BOOLEAN NOT NULL DEFAULT FALSE,
    derived_from     UUIDLIST NOT NULL DEFAULT '[]',
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    CHECK (embedding IS NULL OR embedding_model IS NOT NULL)
);
CREATE INDEX memoires_cree_le_idx ON memoires (cree_le DESC);
CREATE INDEX memoires_origine_idx ON memoires (origine, cree_le DESC);
CREATE INDEX memoires_actifs_idx ON memoires (cree_le DESC) WHERE valid_to IS NULL AND NOT archived;

-- Plein texte : FTS5, accents ignorés (pas de racinisation française, contrairement à PostgreSQL)
CREATE VIRTUAL TABLE memoires_fts USING fts5(id UNINDEXED, contenu, tokenize = 'unicode61 remove_diacritics 2');
CREATE TRIGGER memoires_fts_ajout AFTER INSERT ON memoires BEGIN
    INSERT INTO memoires_fts (id, contenu) VALUES (new.id, new.contenu);
END;
CREATE TRIGGER memoires_fts_maj AFTER UPDATE OF contenu ON memoires BEGIN
    DELETE FROM memoires_fts WHERE id = old.id;
    INSERT INTO memoires_fts (id, contenu) VALUES (new.id, new.contenu);
END;
CREATE TRIGGER memoires_fts_retrait AFTER DELETE ON memoires BEGIN
    DELETE FROM memoires_fts WHERE id = old.id;
END;

CREATE TABLE memory_blocks (
    id         UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    label      TEXT NOT NULL UNIQUE CHECK (label REGEXP '^[a-z0-9][a-z0-9_.:-]{0,63}$'),
    content    TEXT NOT NULL DEFAULT '',
    char_limit INTEGER NOT NULL DEFAULT 2000 CHECK (char_limit > 0),
    version    INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    cree_le    TIMESTAMPTZ NOT NULL DEFAULT (now()),
    maj_le     TIMESTAMPTZ NOT NULL DEFAULT (now()),
    CHECK (length(content) <= char_limit)
);

CREATE TABLE memory_block_versions (
    block_id UUID NOT NULL REFERENCES memory_blocks (id) ON DELETE CASCADE,
    version  INTEGER NOT NULL,
    content  TEXT NOT NULL,
    auteur   TEXT NOT NULL DEFAULT 'jarvis',
    cree_le  TIMESTAMPTZ NOT NULL DEFAULT (now()),
    PRIMARY KEY (block_id, version)
);

-- --- Conversations et télémétrie ----------------------------------------------------------------------------
CREATE TABLE conversations (
    id                 UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    titre              TEXT NOT NULL,
    titre_source       TEXT NOT NULL DEFAULT 'extrait' CHECK (titre_source IN ('extrait', 'auto', 'utilisateur')),
    epinglee           BOOLEAN NOT NULL DEFAULT FALSE,
    archivee           BOOLEAN NOT NULL DEFAULT FALSE,
    interne            BOOLEAN NOT NULL DEFAULT FALSE,
    resume             TEXT,
    resume_le          TIMESTAMPTZ,
    resume_nb_messages INTEGER NOT NULL DEFAULT 0,
    cree_le            TIMESTAMPTZ NOT NULL DEFAULT (now()),
    maj_le             TIMESTAMPTZ NOT NULL DEFAULT (now()),
    connecteur         TEXT,
    modele             TEXT
);
CREATE INDEX conversations_liste_idx ON conversations (archivee, epinglee DESC, maj_le DESC);

CREATE TABLE messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id UUID NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('utilisateur', 'jarvis')),
    contenu         TEXT NOT NULL,
    horodatage      TIMESTAMPTZ NOT NULL DEFAULT (now()),
    meta            JSONB NOT NULL DEFAULT '{}',
    ancien_id       INTEGER
);
CREATE INDEX messages_conversation_idx ON messages (conversation_id, id);
CREATE UNIQUE INDEX messages_ancien_id_idx ON messages (ancien_id) WHERE ancien_id IS NOT NULL;

CREATE TABLE telemetrie (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    moteur           TEXT NOT NULL,
    modele           TEXT,
    operation        TEXT NOT NULL CHECK (operation IN ('generate', 'stream')),
    statut           TEXT NOT NULL CHECK (statut IN ('ok', 'erreur', 'annule')),
    latence_ms       INTEGER NOT NULL,
    premier_jeton_ms INTEGER,
    jetons_entree    INTEGER,
    jetons_sortie    INTEGER,
    cout_usd         REAL NOT NULL DEFAULT 0,
    erreur           TEXT,
    conversation_id  UUID REFERENCES conversations (id) ON DELETE SET NULL,
    meta             JSONB NOT NULL DEFAULT '{}',
    cree_le          TIMESTAMPTZ NOT NULL DEFAULT (now())
);
CREATE INDEX telemetrie_cree_le_idx ON telemetrie (cree_le DESC);
CREATE INDEX telemetrie_moteur_idx ON telemetrie (moteur, cree_le DESC);

-- --- Données héritées (profil, missions, créations, chantiers, imports) -------------------------------------
CREATE TABLE profil_reponses (
    question_id TEXT PRIMARY KEY,
    reponse     JSONB NOT NULL,
    commentaire TEXT,
    souvenir_id UUID REFERENCES memoires (id) ON DELETE SET NULL,
    cree_le     TIMESTAMPTZ NOT NULL DEFAULT (now()),
    maj_le      TIMESTAMPTZ NOT NULL DEFAULT (now())
);

CREATE TABLE missions (
    id          UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    type        TEXT NOT NULL,
    objectif    TEXT NOT NULL,
    parametres  JSONB NOT NULL DEFAULT '{}',
    statut      TEXT NOT NULL CHECK (statut IN ('en_file', 'en_cours', 'terminee', 'echec', 'annulee')),
    progression INTEGER NOT NULL DEFAULT 0 CHECK (progression BETWEEN 0 AND 100),
    etapes      JSONB NOT NULL DEFAULT '[]',
    resultat    JSONB,
    erreur      TEXT,
    cout_usd    REAL,
    acteur      TEXT NOT NULL,
    cree_le     TIMESTAMPTZ NOT NULL DEFAULT (now()),
    demarre_le  TIMESTAMPTZ,
    termine_le  TIMESTAMPTZ
);
CREATE INDEX missions_cree_le_idx ON missions (cree_le DESC);
CREATE INDEX missions_statut_idx ON missions (statut, cree_le);

CREATE TABLE creations (
    id               UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    titre            TEXT NOT NULL CHECK (length(titre) BETWEEN 1 AND 200),
    description      TEXT,
    version_courante INTEGER NOT NULL DEFAULT 0 CHECK (version_courante >= 0),
    archive          BOOLEAN NOT NULL DEFAULT FALSE,
    cree_par         TEXT NOT NULL,
    cree_le          TIMESTAMPTZ NOT NULL DEFAULT (now()),
    maj_le           TIMESTAMPTZ NOT NULL DEFAULT (now())
);
CREATE INDEX creations_liste_idx ON creations (archive, maj_le DESC);

CREATE TABLE creation_versions (
    creation_id    UUID NOT NULL REFERENCES creations (id) ON DELETE CASCADE,
    version        INTEGER NOT NULL CHECK (version >= 1),
    html           TEXT NOT NULL,
    demande        TEXT NOT NULL,
    modele         TEXT,
    avertissements JSONB NOT NULL DEFAULT '[]',
    duree_ms       INTEGER,
    cree_le        TIMESTAMPTZ NOT NULL DEFAULT (now()),
    PRIMARY KEY (creation_id, version)
);

CREATE TABLE creation_donnees (
    id          UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    creation_id UUID NOT NULL REFERENCES creations (id) ON DELETE CASCADE,
    collection  TEXT NOT NULL CHECK (collection REGEXP '^[A-Za-z0-9_-]{1,64}$'),
    donnees     JSONB NOT NULL,
    cree_le     TIMESTAMPTZ NOT NULL DEFAULT (now()),
    maj_le      TIMESTAMPTZ NOT NULL DEFAULT (now())
);
CREATE INDEX creation_donnees_idx ON creation_donnees (creation_id, collection, cree_le);

CREATE TABLE chantiers (
    id                 UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    titre              TEXT NOT NULL CHECK (length(titre) BETWEEN 1 AND 300),
    description        TEXT,
    categorie          TEXT NOT NULL,
    statut             TEXT NOT NULL CHECK (statut IN ('propose', 'a_faire', 'en_cours', 'en_attente_utilisateur',
                                                       'termine', 'bloque', 'abandonne')),
    progression        INTEGER NOT NULL DEFAULT 0 CHECK (progression BETWEEN 0 AND 100),
    etape_courante     TEXT,
    etapes             JSONB NOT NULL DEFAULT '[]',
    responsable        TEXT NOT NULL,
    action_utilisateur TEXT,
    priorite           INTEGER NOT NULL DEFAULT 2 CHECK (priorite BETWEEN 1 AND 3),
    cree_par           TEXT NOT NULL,
    cree_le            TIMESTAMPTZ NOT NULL DEFAULT (now()),
    maj_le             TIMESTAMPTZ NOT NULL DEFAULT (now()),
    termine_le         TIMESTAMPTZ,
    origine            TEXT NOT NULL CHECK (origine IN ('utilisateur', 'jarvis', 'claude')),
    type               TEXT CHECK (type IS NULL OR type REGEXP '^[a-z0-9][a-z0-9_-]{0,39}$'),
    proposition        JSONB,
    apercu             JSONB,
    session_id         UUID,
    valide_par         TEXT,
    motif              TEXT,
    amelioration       JSONB
);
CREATE INDEX chantiers_statut_idx ON chantiers (statut, priorite, maj_le DESC);

CREATE TABLE imports (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    source    TEXT NOT NULL,
    empreinte TEXT NOT NULL,
    comptes   JSONB NOT NULL,
    cree_le   TIMESTAMPTZ NOT NULL DEFAULT (now())
);

-- --- Sécurité -----------------------------------------------------------------------------------------------
-- Journal d'audit chaîné : écrit par securite/audit.py (empreinte calculée comme audit_canonique de PostgreSQL),
-- jamais modifié ni effacé (déclencheurs).
CREATE TABLE audit (
    id         INTEGER PRIMARY KEY,
    horodatage TIMESTAMPTZ NOT NULL,
    acteur     TEXT NOT NULL,
    action     TEXT NOT NULL,
    niveau     TEXT NOT NULL CHECK (niveau IN ('vert', 'jaune', 'rouge')),
    cible      TEXT,
    details    JSONB NOT NULL DEFAULT '{}',
    resultat   TEXT NOT NULL,
    hash_prec  TEXT NOT NULL,
    hash       TEXT NOT NULL UNIQUE
);
CREATE INDEX audit_horodatage_idx ON audit (horodatage DESC);
CREATE TRIGGER audit_sans_modification BEFORE UPDATE ON audit BEGIN
    SELECT RAISE(ABORT, 'Journal d''audit en ajout seul : UPDATE interdit');
END;
CREATE TRIGGER audit_sans_effacement BEFORE DELETE ON audit BEGIN
    SELECT RAISE(ABORT, 'Journal d''audit en ajout seul : DELETE interdit');
END;

CREATE TABLE appareils (
    id            UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    nom           TEXT NOT NULL CHECK (length(nom) BETWEEN 1 AND 80),
    type          TEXT NOT NULL DEFAULT 'navigateur' CHECK (type IN ('navigateur', 'telephone', 'pc', 'cli')),
    jeton_hash    TEXT NOT NULL UNIQUE,
    cree_par      UUID REFERENCES appareils (id) ON DELETE SET NULL,
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT (now()),
    dernier_acces TIMESTAMPTZ,
    revoque_le    TIMESTAMPTZ
);

CREATE TABLE jumelages (
    code_hash  TEXT PRIMARY KEY,
    cree_par   UUID REFERENCES appareils (id) ON DELETE CASCADE,
    type       TEXT NOT NULL DEFAULT 'telephone' CHECK (type IN ('navigateur', 'telephone', 'pc')),
    expire_le  TIMESTAMPTZ NOT NULL,
    utilise_le TIMESTAMPTZ,
    appareil   UUID REFERENCES appareils (id) ON DELETE SET NULL
);

CREATE TABLE cles_acces (
    id            TEXT PRIMARY KEY,
    appareil_id   UUID NOT NULL REFERENCES appareils (id) ON DELETE CASCADE,
    nom           TEXT NOT NULL,
    cle_publique  BLOB NOT NULL,
    compteur      INTEGER NOT NULL DEFAULT 0,
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT (now()),
    dernier_usage TIMESTAMPTZ
);

CREATE TABLE defis_webauthn (
    defi        TEXT PRIMARY KEY,
    type        TEXT NOT NULL CHECK (type IN ('enregistrement', 'approbation')),
    appareil_id UUID NOT NULL REFERENCES appareils (id) ON DELETE CASCADE,
    demande_id  UUID,
    expire_le   TIMESTAMPTZ NOT NULL
);

CREATE TABLE demandes (
    id         UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    action     TEXT NOT NULL,
    niveau     TEXT NOT NULL CHECK (niveau IN ('jaune', 'rouge')),
    resume     TEXT NOT NULL,
    parametres JSONB NOT NULL DEFAULT '{}',
    statut     TEXT NOT NULL DEFAULT 'en_attente'
        CHECK (statut IN ('en_attente', 'approuvee', 'refusee', 'expiree', 'executee', 'echec')),
    demandeur  TEXT NOT NULL,
    cree_le    TIMESTAMPTZ NOT NULL DEFAULT (now()),
    expire_le  TIMESTAMPTZ NOT NULL,
    decide_le  TIMESTAMPTZ,
    decide_par UUID REFERENCES appareils (id) ON DELETE SET NULL,
    methode    TEXT CHECK (methode IN ('clic', 'cle_acces')),
    resultat   JSONB
);
CREATE INDEX demandes_attente_idx ON demandes (statut, cree_le DESC);

CREATE TABLE etat_systeme (
    cle    TEXT PRIMARY KEY,
    valeur JSONB NOT NULL,
    maj_le TIMESTAMPTZ NOT NULL DEFAULT (now())
);
INSERT INTO etat_systeme (cle, valeur) VALUES ('arret_urgence', '{"actif": false}');

-- --- Connecteurs d'IA ---------------------------------------------------------------------------------------
CREATE TABLE connecteurs (
    id                      TEXT PRIMARY KEY CHECK (id REGEXP '^[a-z0-9][a-z0-9_-]{0,39}$'),
    actif                   BOOLEAN NOT NULL,
    dans_conseil            BOOLEAN NOT NULL DEFAULT FALSE,
    conditions_version      TEXT,
    conditions_acceptees_le TIMESTAMPTZ,
    maj_le                  TIMESTAMPTZ NOT NULL DEFAULT (now()),
    CHECK (conditions_version IS NULL OR conditions_acceptees_le IS NOT NULL)
);
