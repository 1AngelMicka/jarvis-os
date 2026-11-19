-- 031 — Ateliers dans un vrai bac à sable (point 14 · B 9) : choix du bac de chaque atelier.
-- « auto » (défaut) = premier bac disponible ; un type précis = celui-là ou refus (jamais de repli) ;
-- « aucun » = sans bac à sable, choix explicite et confirmé de l'utilisateur.

ALTER TABLE ateliers ADD COLUMN bac_a_sable text NOT NULL DEFAULT 'auto'
    CHECK (bac_a_sable IN ('auto', 'docker', 'podman', 'windows_sandbox', 'bubblewrap', 'sandbox_exec', 'aucun'));
