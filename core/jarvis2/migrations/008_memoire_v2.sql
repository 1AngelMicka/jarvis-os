-- 008 — Mémoire v2 : vecteurs de plusieurs modèles par souvenir (bascule de modèle sans interruption),
-- blocs de mémoire privés, état de la bascule.

-- Vecteurs d'un modèle autre que celui de `memoires.embedding` (ex. BAAI/bge-m3, 1024 dimensions). La recherche
-- compare le vecteur du modèle ACTIF : `memoires.embedding` s'il en vient, sinon celui-ci.
CREATE TABLE memoire_vecteurs (
    memoire_id uuid NOT NULL REFERENCES memoires (id) ON DELETE CASCADE,
    modele     text NOT NULL,
    vecteur    vector NOT NULL,
    cree_le    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (memoire_id, modele)
);

ALTER TABLE memory_blocks
    ADD COLUMN confidentialite text NOT NULL DEFAULT 'normal' CHECK (confidentialite IN ('normal', 'local_uniquement'));

-- Modèle d'embeddings actif de la recherche (vide : celui de la configuration)
INSERT INTO etat_systeme (cle, valeur) VALUES ('memoire_modele', '{}') ON CONFLICT (cle) DO NOTHING;

GRANT SELECT, INSERT, UPDATE ON memoire_vecteurs TO jarvis2_app;
