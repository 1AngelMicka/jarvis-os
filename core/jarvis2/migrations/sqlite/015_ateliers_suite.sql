-- 015 — Ateliers, suite (jumelle SQLite de la migration PostgreSQL 015).

ALTER TABLE ateliers ADD COLUMN modele TEXT CHECK (modele IS NULL OR length(modele) BETWEEN 1 AND 80);
ALTER TABLE ateliers ADD COLUMN notes TEXT CHECK (notes IS NULL OR length(notes) <= 10000);
ALTER TABLE ateliers ADD COLUMN clos_le TIMESTAMPTZ;

CREATE TABLE fichiers_atelier (
    atelier_id UUID NOT NULL REFERENCES ateliers (id) ON DELETE CASCADE,
    chemin     TEXT NOT NULL CHECK (length(chemin) BETWEEN 1 AND 1000),
    premier_le TIMESTAMPTZ NOT NULL DEFAULT (now()),
    PRIMARY KEY (atelier_id, chemin)
);
CREATE INDEX fichiers_atelier_chemin_idx ON fichiers_atelier (chemin);

INSERT INTO etat_systeme (cle, valeur)
VALUES ('veille_claude_code', '{"actif": false, "voix": false, "notification": true}')
ON CONFLICT (cle) DO NOTHING;
