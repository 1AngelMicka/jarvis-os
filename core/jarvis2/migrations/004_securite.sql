-- 004 — Sécurité : journal d'audit chaîné en ajout seul, appareils, jumelage, clés d'accès, demandes, arrêt d'urgence.

-- --- Journal d'audit ----------------------------------------------------------------------------------------
-- Propriété d'un rôle dédié sans connexion (`jarvis2_audit`), distinct du propriétaire de la base et du rôle
-- applicatif. Le rôle applicatif n'écrit QUE par `audit_ajouter()` (SECURITY DEFINER) et ne peut rien modifier ni
-- effacer. Des déclencheurs refusent UPDATE, DELETE et TRUNCATE à tous. Chaque entrée porte l'empreinte SHA-256 de
-- l'entrée précédente : toute altération (même par un super-utilisateur) est détectée par `audit_verifier()`.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis2_audit') THEN
        CREATE ROLE jarvis2_audit NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END $$;
GRANT USAGE ON SCHEMA public TO jarvis2_audit;
GRANT CREATE ON SCHEMA public TO jarvis2_audit;

CREATE TABLE audit (
    id          bigserial PRIMARY KEY,
    horodatage  timestamptz NOT NULL DEFAULT clock_timestamp(),
    acteur      text NOT NULL,                  -- appareil, « systeme », « cli »
    action      text NOT NULL,
    niveau      text NOT NULL CHECK (niveau IN ('vert', 'jaune', 'rouge')),
    cible       text,
    details     jsonb NOT NULL DEFAULT '{}',
    resultat    text NOT NULL,
    hash_prec   text NOT NULL,
    hash        text NOT NULL UNIQUE
);
ALTER TABLE audit OWNER TO jarvis2_audit;
ALTER SEQUENCE audit_id_seq OWNER TO jarvis2_audit;
CREATE INDEX audit_horodatage_idx ON audit (horodatage DESC);

-- Texte canonique d'une entrée (le même pour l'ajout et la vérification)
CREATE FUNCTION audit_canonique(a audit) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT concat_ws('|', a.id, to_char(a.horodatage AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
                     a.acteur, a.action, a.niveau, coalesce(a.cible, ''), a.details::text, a.resultat, a.hash_prec)
$$;
ALTER FUNCTION audit_canonique(audit) OWNER TO jarvis2_audit;

CREATE FUNCTION audit_ajouter(p_acteur text, p_action text, p_niveau text, p_cible text, p_details jsonb,
                              p_resultat text) RETURNS audit
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    e audit;
BEGIN
    PERFORM pg_advisory_xact_lock(726004);  -- une seule écriture à la fois : la chaîne reste linéaire
    e.id := nextval('audit_id_seq');
    e.horodatage := clock_timestamp();
    e.acteur := p_acteur; e.action := p_action; e.niveau := p_niveau; e.cible := p_cible;
    e.details := coalesce(p_details, '{}'); e.resultat := p_resultat;
    e.hash_prec := coalesce((SELECT hash FROM audit ORDER BY id DESC LIMIT 1), repeat('0', 64));
    e.hash := encode(digest(audit_canonique(e), 'sha256'), 'hex');
    INSERT INTO audit VALUES (e.*);
    RETURN e;
END $$;
ALTER FUNCTION audit_ajouter(text, text, text, text, jsonb, text) OWNER TO jarvis2_audit;

-- Première entrée dont la chaîne est rompue (NULL si le journal est intact)
CREATE FUNCTION audit_verifier() RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp AS $$
    SELECT min(id) FROM (
        SELECT a.id, a.hash, a.hash_prec,
               lag(a.hash, 1, repeat('0', 64)) OVER (ORDER BY a.id) AS attendu,
               encode(digest(audit_canonique(a), 'sha256'), 'hex') AS recalcule
        FROM audit a
    ) c WHERE c.hash_prec <> c.attendu OR c.hash <> c.recalcule
$$;
ALTER FUNCTION audit_verifier() OWNER TO jarvis2_audit;

CREATE FUNCTION audit_interdire() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Journal d''audit en ajout seul : % interdit', TG_OP;
END $$;
CREATE TRIGGER audit_sans_modification BEFORE UPDATE OR DELETE ON audit
    FOR EACH ROW EXECUTE FUNCTION audit_interdire();
CREATE TRIGGER audit_sans_vidage BEFORE TRUNCATE ON audit
    FOR EACH STATEMENT EXECUTE FUNCTION audit_interdire();

REVOKE ALL ON audit FROM PUBLIC;
REVOKE ALL ON FUNCTION audit_ajouter(text, text, text, text, jsonb, text) FROM PUBLIC;
GRANT SELECT ON audit TO jarvis2_app;
GRANT EXECUTE ON FUNCTION audit_ajouter(text, text, text, text, jsonb, text) TO jarvis2_app;
GRANT EXECUTE ON FUNCTION audit_verifier() TO jarvis2_app;
REVOKE CREATE ON SCHEMA public FROM jarvis2_audit;

-- --- Appareils et jumelage ----------------------------------------------------------------------------------
-- Jetons jamais stockés en clair : seule leur empreinte SHA-256 est gardée.
CREATE TABLE appareils (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    nom           text NOT NULL CHECK (char_length(nom) BETWEEN 1 AND 80),
    type          text NOT NULL DEFAULT 'navigateur' CHECK (type IN ('navigateur', 'telephone', 'pc', 'cli')),
    jeton_hash    text NOT NULL UNIQUE,
    cree_par      uuid REFERENCES appareils (id) ON DELETE SET NULL,
    cree_le       timestamptz NOT NULL DEFAULT now(),
    dernier_acces timestamptz,
    revoque_le    timestamptz
);

CREATE TABLE jumelages (
    code_hash  text PRIMARY KEY,
    cree_par   uuid REFERENCES appareils (id) ON DELETE CASCADE,  -- NULL : créé en ligne de commande
    type       text NOT NULL DEFAULT 'telephone' CHECK (type IN ('navigateur', 'telephone', 'pc')),
    expire_le  timestamptz NOT NULL,
    utilise_le timestamptz,
    appareil   uuid REFERENCES appareils (id) ON DELETE SET NULL
);

-- Clés d'accès (WebAuthn) : servent à approuver les actions 🔴
CREATE TABLE cles_acces (
    id           text PRIMARY KEY,                   -- identifiant de la clé (base64url)
    appareil_id  uuid NOT NULL REFERENCES appareils (id) ON DELETE CASCADE,
    nom          text NOT NULL,
    cle_publique bytea NOT NULL,
    compteur     bigint NOT NULL DEFAULT 0,
    cree_le      timestamptz NOT NULL DEFAULT now(),
    dernier_usage timestamptz
);

CREATE TABLE defis_webauthn (
    defi        text PRIMARY KEY,                    -- base64url
    type        text NOT NULL CHECK (type IN ('enregistrement', 'approbation')),
    appareil_id uuid NOT NULL REFERENCES appareils (id) ON DELETE CASCADE,
    demande_id  uuid,
    expire_le   timestamptz NOT NULL
);

-- --- Demandes d'approbation ----------------------------------------------------------------------------------
CREATE TABLE demandes (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    action     text NOT NULL,
    niveau     text NOT NULL CHECK (niveau IN ('jaune', 'rouge')),
    resume     text NOT NULL,
    parametres jsonb NOT NULL DEFAULT '{}',
    statut     text NOT NULL DEFAULT 'en_attente'
        CHECK (statut IN ('en_attente', 'approuvee', 'refusee', 'expiree', 'executee', 'echec')),
    demandeur  text NOT NULL,
    cree_le    timestamptz NOT NULL DEFAULT now(),
    expire_le  timestamptz NOT NULL,
    decide_le  timestamptz,
    decide_par uuid REFERENCES appareils (id) ON DELETE SET NULL,
    methode    text CHECK (methode IN ('clic', 'cle_acces')),
    resultat   jsonb
);
CREATE INDEX demandes_attente_idx ON demandes (statut, cree_le DESC);

-- --- État du système (arrêt d'urgence) -----------------------------------------------------------------------
CREATE TABLE etat_systeme (
    cle    text PRIMARY KEY,
    valeur jsonb NOT NULL,
    maj_le timestamptz NOT NULL DEFAULT now()
);
INSERT INTO etat_systeme (cle, valeur) VALUES ('arret_urgence', '{"actif": false}');

GRANT SELECT, INSERT, UPDATE ON appareils, jumelages, cles_acces, demandes TO jarvis2_app;
GRANT SELECT, INSERT, DELETE ON defis_webauthn TO jarvis2_app;
GRANT SELECT, UPDATE ON etat_systeme TO jarvis2_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO jarvis2_app;
