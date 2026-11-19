-- 015 — Ateliers, suite (phase 13, lot I) : choix du modèle, clôture avec notes, fichiers touchés par chaque atelier
-- (conflits entre ateliers d'un même projet), réglage de la veille des sessions Claude Code de l'utilisateur.

ALTER TABLE ateliers ADD COLUMN modele text CHECK (modele IS NULL OR char_length(modele) BETWEEN 1 AND 80);
ALTER TABLE ateliers ADD COLUMN notes text CHECK (notes IS NULL OR char_length(notes) <= 10000);
ALTER TABLE ateliers ADD COLUMN clos_le timestamptz;

-- Fichiers modifiés par un atelier (chemin relatif au worktree) : deux ateliers ouverts du même projet qui touchent
-- le même fichier sont signalés, jamais bloqués.
CREATE TABLE fichiers_atelier (
    atelier_id uuid NOT NULL REFERENCES ateliers (id) ON DELETE CASCADE,
    chemin     text NOT NULL CHECK (char_length(chemin) BETWEEN 1 AND 1000),
    premier_le timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (atelier_id, chemin)
);
CREATE INDEX fichiers_atelier_chemin_idx ON fichiers_atelier (chemin);

-- Veille des sessions Claude Code de l'utilisateur : lecture seule, désactivée par défaut
INSERT INTO etat_systeme (cle, valeur)
VALUES ('veille_claude_code', '{"actif": false, "voix": false, "notification": true}')
ON CONFLICT (cle) DO NOTHING;

GRANT SELECT, INSERT ON fichiers_atelier TO jarvis2_app;
