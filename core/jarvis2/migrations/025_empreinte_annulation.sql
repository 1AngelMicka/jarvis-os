-- 025 — Approbation liée à l'empreinte du plan exact et pile d'annulation (phase 14, point B 7).
-- `demandes.empreinte` : SHA-256 du texte canonique (action, niveau, résumé, paramètres) calculé par le Core à la
-- création ; l'interface renvoie l'empreinte affichée avec l'approbation, le Core la revérifie juste avant d'exécuter.
-- Une demande d'avant cette migration n'a pas d'empreinte : elle ne s'approuve plus (relancer l'action).
-- `annulations` : actions réversibles exécutées (« Annuler » dans l'interface ou par commande rapide), avec l'état
-- d'avant nécessaire pour revenir en arrière ; chaque annulation est inscrite au journal d'audit.

ALTER TABLE demandes ADD COLUMN empreinte text CHECK (empreinte IS NULL OR empreinte ~ '^[0-9a-f]{64}$');

CREATE TABLE annulations (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    action     text NOT NULL,
    resume     text NOT NULL,
    comment    text NOT NULL,      -- comment l'action est annulée (affiché sur le bouton « Annuler »)
    parametres jsonb NOT NULL DEFAULT '{}',
    resultat   jsonb NOT NULL DEFAULT '{}',   -- contient l'état d'avant (« avant ») quand l'annulation en a besoin
    demande_id uuid REFERENCES demandes (id) ON DELETE SET NULL,
    acteur     text NOT NULL,
    statut     text NOT NULL DEFAULT 'disponible' CHECK (statut IN ('disponible', 'annulee', 'echec', 'perimee')),
    cree_le    timestamptz NOT NULL DEFAULT now(),
    expire_le  timestamptz NOT NULL,
    annule_le  timestamptz,
    annule_par text,
    detail     text
);
CREATE INDEX annulations_pile_idx ON annulations (statut, cree_le DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON annulations TO jarvis2_app;
