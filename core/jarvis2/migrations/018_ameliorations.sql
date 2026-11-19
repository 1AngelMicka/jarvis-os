-- 018 — Amélioration continue (phase 13, lot O) : suggestions (de JARVIS ou de l'utilisateur, avec origine et
-- raison), réalisées dans un atelier (branche dédiée), aperçu et tests, mise en service 🟡 (fusion locale) et retour
-- arrière 🟡 (revenir au commit d'avant). Jamais de push.

CREATE TABLE ameliorations (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    titre          text NOT NULL CHECK (char_length(titre) BETWEEN 1 AND 200),
    raison         text NOT NULL CHECK (char_length(raison) BETWEEN 1 AND 2000),
    description    text NOT NULL DEFAULT '' CHECK (char_length(description) <= 10000),
    origine        text NOT NULL CHECK (origine IN ('jarvis', 'utilisateur')),
    projet         text NOT NULL,
    statut         text NOT NULL DEFAULT 'proposee'
        CHECK (statut IN ('proposee', 'en_atelier', 'en_service', 'retiree', 'rejetee')),
    atelier_id     uuid REFERENCES ateliers (id) ON DELETE SET NULL,
    tests          jsonb,          -- dernier essai des tests : code, réussite, sortie (tronquée), empreinte testée
    commit_avant   text,           -- tête du projet juste avant la mise en service
    commit_service text,           -- tête du projet après la fusion
    commit_retour  text,           -- commit du retour arrière
    cree_par       text NOT NULL,
    cree_le        timestamptz NOT NULL DEFAULT now(),
    maj_le         timestamptz NOT NULL DEFAULT now(),
    en_service_le  timestamptz,
    retiree_le     timestamptz
);
CREATE INDEX ameliorations_statut_idx ON ameliorations (statut, cree_le DESC);

GRANT SELECT, INSERT, UPDATE ON ameliorations TO jarvis2_app;
