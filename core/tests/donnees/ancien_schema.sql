-- Schéma des tables héritées de l'ancien JARVIS (extrait de sa sauvegarde du 18 nov. 2026, structure seule).
-- Sert de base d'attente factice dans les tests d'import.

CREATE TABLE public.conversations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    titre text NOT NULL,
    cree_le timestamp with time zone DEFAULT now() NOT NULL,
    maj_le timestamp with time zone DEFAULT now() NOT NULL,
    titre_source text DEFAULT 'extrait'::text NOT NULL,
    epinglee boolean DEFAULT false NOT NULL,
    archivee boolean DEFAULT false NOT NULL,
    resume text,
    resume_le timestamp with time zone,
    resume_nb_messages integer DEFAULT 0 NOT NULL,
    interne boolean DEFAULT false NOT NULL,
    CONSTRAINT conversations_titre_source_check CHECK ((titre_source = ANY (ARRAY['extrait'::text, 'auto'::text, 'utilisateur'::text])))
);

CREATE TABLE public.creation_donnees (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    creation_id uuid NOT NULL,
    collection text NOT NULL,
    donnees jsonb NOT NULL,
    cree_le timestamp with time zone DEFAULT now() NOT NULL,
    maj_le timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT creation_donnees_collection_check CHECK ((collection ~ '^[A-Za-z0-9_-]{1,64}$'::text))
);

CREATE TABLE public.creation_versions (
    creation_id uuid NOT NULL,
    version integer NOT NULL,
    html text NOT NULL,
    demande text NOT NULL,
    modele text,
    avertissements jsonb DEFAULT '[]'::jsonb NOT NULL,
    duree_ms integer,
    cree_le timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT creation_versions_version_check CHECK ((version >= 1))
);

CREATE TABLE public.creations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    titre text NOT NULL,
    description text,
    version_courante integer DEFAULT 0 NOT NULL,
    archive boolean DEFAULT false NOT NULL,
    cree_par text NOT NULL,
    cree_le timestamp with time zone DEFAULT now() NOT NULL,
    maj_le timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT creations_titre_check CHECK (((char_length(titre) >= 1) AND (char_length(titre) <= 200))),
    CONSTRAINT creations_version_courante_check CHECK ((version_courante >= 0))
);

CREATE TABLE public.memoires (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    contenu text NOT NULL,
    type text NOT NULL,
    tags text[] DEFAULT '{}'::text[] NOT NULL,
    source text,
    confidentialite text DEFAULT 'normal'::text NOT NULL,
    embedding public.vector(384),
    tsv tsvector NOT NULL,
    cree_le timestamp with time zone DEFAULT now() NOT NULL,
    maj_le timestamp with time zone DEFAULT now() NOT NULL,
    origine text DEFAULT 'autre'::text NOT NULL,
    canal_detail text,
    CONSTRAINT memoires_confidentialite_check CHECK ((confidentialite = ANY (ARRAY['normal'::text, 'local_uniquement'::text]))),
    CONSTRAINT memoires_origine_check CHECK ((origine = ANY (ARRAY['conversation'::text, 'mission'::text, 'import_ia'::text, 'import_google'::text, 'profil'::text, 'ecoute'::text, 'creation'::text, 'projet'::text, 'systeme'::text, 'utilisateur'::text, 'connaissances'::text, 'autre'::text]))),
    CONSTRAINT memoires_type_check CHECK ((type = ANY (ARRAY['note'::text, 'idee'::text, 'decision'::text, 'fait'::text, 'projet'::text])))
);

CREATE TABLE public.messages (
    id bigint NOT NULL,
    conversation_id uuid NOT NULL,
    role text NOT NULL,
    contenu text NOT NULL,
    horodatage timestamp with time zone DEFAULT now() NOT NULL,
    meta jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT messages_role_check CHECK ((role = ANY (ARRAY['utilisateur'::text, 'jarvis'::text])))
);

CREATE SEQUENCE public.messages_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.messages_id_seq OWNED BY public.messages.id;

CREATE TABLE public.missions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    type text NOT NULL,
    objectif text NOT NULL,
    parametres jsonb DEFAULT '{}'::jsonb NOT NULL,
    statut text DEFAULT 'en_file'::text NOT NULL,
    progression smallint DEFAULT 0 NOT NULL,
    etapes jsonb DEFAULT '[]'::jsonb NOT NULL,
    resultat jsonb,
    erreur text,
    cout_usd numeric(12,6),
    acteur text NOT NULL,
    cree_le timestamp with time zone DEFAULT now() NOT NULL,
    demarre_le timestamp with time zone,
    termine_le timestamp with time zone,
    CONSTRAINT missions_progression_check CHECK (((progression >= 0) AND (progression <= 100))),
    CONSTRAINT missions_statut_check CHECK ((statut = ANY (ARRAY['en_file'::text, 'en_cours'::text, 'terminee'::text, 'echec'::text, 'annulee'::text])))
);

CREATE TABLE public.profil_reponses (
    question_id text NOT NULL,
    reponse jsonb NOT NULL,
    commentaire text,
    souvenir_id uuid,
    cree_le timestamp with time zone DEFAULT now() NOT NULL,
    maj_le timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.taches (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    titre text NOT NULL,
    description text,
    categorie text DEFAULT 'general'::text NOT NULL,
    statut text DEFAULT 'a_faire'::text NOT NULL,
    progression smallint DEFAULT 0 NOT NULL,
    etape_courante text,
    etapes jsonb DEFAULT '[]'::jsonb NOT NULL,
    responsable text DEFAULT 'Claude'::text NOT NULL,
    action_utilisateur text,
    priorite smallint DEFAULT 2 NOT NULL,
    cree_par text NOT NULL,
    cree_le timestamp with time zone DEFAULT now() NOT NULL,
    maj_le timestamp with time zone DEFAULT now() NOT NULL,
    termine_le timestamp with time zone,
    origine text DEFAULT 'claude'::text NOT NULL,
    type text,
    proposition jsonb,
    apercu jsonb,
    session_id uuid,
    valide_par text,
    motif text,
    amelioration jsonb,
    CONSTRAINT taches_origine_check CHECK ((origine = ANY (ARRAY['utilisateur'::text, 'jarvis'::text, 'claude'::text]))),
    CONSTRAINT taches_priorite_check CHECK (((priorite >= 1) AND (priorite <= 3))),
    CONSTRAINT taches_progression_check CHECK (((progression >= 0) AND (progression <= 100))),
    CONSTRAINT taches_statut_check CHECK ((statut = ANY (ARRAY['propose'::text, 'a_faire'::text, 'en_cours'::text, 'en_attente_utilisateur'::text, 'termine'::text, 'bloque'::text, 'abandonne'::text]))),
    CONSTRAINT taches_titre_check CHECK (((char_length(titre) >= 1) AND (char_length(titre) <= 300))),
    CONSTRAINT taches_type_check CHECK (((type IS NULL) OR (type ~ '^[a-z0-9][a-z0-9_-]{0,39}$'::text)))
);

ALTER TABLE ONLY public.messages ALTER COLUMN id SET DEFAULT nextval('public.messages_id_seq'::regclass);

ALTER TABLE ONLY public.conversations
    ADD CONSTRAINT conversations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.creation_donnees
    ADD CONSTRAINT creation_donnees_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.creation_versions
    ADD CONSTRAINT creation_versions_pkey PRIMARY KEY (creation_id, version);

ALTER TABLE ONLY public.creations
    ADD CONSTRAINT creations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.memoires
    ADD CONSTRAINT memoires_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.missions
    ADD CONSTRAINT missions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.profil_reponses
    ADD CONSTRAINT profil_reponses_pkey PRIMARY KEY (question_id);

ALTER TABLE ONLY public.taches
    ADD CONSTRAINT taches_pkey PRIMARY KEY (id);

CREATE INDEX conversations_liste_idx ON public.conversations USING btree (archivee, epinglee DESC, maj_le DESC);

CREATE INDEX conversations_maj_le_idx ON public.conversations USING btree (maj_le DESC);

CREATE INDEX conversations_visibles_idx ON public.conversations USING btree (archivee, epinglee DESC, maj_le DESC) WHERE (NOT interne);

CREATE INDEX creation_donnees_idx ON public.creation_donnees USING btree (creation_id, collection, cree_le);

CREATE INDEX creations_liste_idx ON public.creations USING btree (archive, maj_le DESC);

CREATE INDEX memoires_connaissances_idx ON public.memoires USING btree (canal_detail, cree_le DESC) WHERE (origine = 'connaissances'::text);

CREATE INDEX memoires_cree_le_idx ON public.memoires USING btree (cree_le DESC);

CREATE INDEX memoires_embedding_idx ON public.memoires USING hnsw (embedding public.vector_cosine_ops);

CREATE INDEX memoires_origine_idx ON public.memoires USING btree (origine, cree_le DESC);

CREATE INDEX memoires_source_idx ON public.memoires USING btree (source);

CREATE INDEX memoires_tags_idx ON public.memoires USING gin (tags);

CREATE INDEX memoires_tsv_idx ON public.memoires USING gin (tsv);

CREATE INDEX messages_conversation_idx ON public.messages USING btree (conversation_id, id);

CREATE INDEX missions_cree_le_idx ON public.missions USING btree (cree_le DESC);

CREATE INDEX missions_statut_idx ON public.missions USING btree (statut, cree_le);

CREATE INDEX taches_session_idx ON public.taches USING btree (session_id) WHERE (session_id IS NOT NULL);

CREATE INDEX taches_statut_idx ON public.taches USING btree (statut, priorite, maj_le DESC);

CREATE INDEX taches_termine_le_idx ON public.taches USING btree (termine_le DESC) WHERE (termine_le IS NOT NULL);

CREATE INDEX taches_type_idx ON public.taches USING btree (type, statut) WHERE (type IS NOT NULL);

ALTER TABLE ONLY public.creation_donnees
    ADD CONSTRAINT creation_donnees_creation_id_fkey FOREIGN KEY (creation_id) REFERENCES public.creations(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.creation_versions
    ADD CONSTRAINT creation_versions_creation_id_fkey FOREIGN KEY (creation_id) REFERENCES public.creations(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.profil_reponses
    ADD CONSTRAINT profil_reponses_souvenir_id_fkey FOREIGN KEY (souvenir_id) REFERENCES public.memoires(id) ON DELETE SET NULL;
