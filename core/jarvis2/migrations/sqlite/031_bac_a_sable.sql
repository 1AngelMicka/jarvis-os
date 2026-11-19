-- 031 — Ateliers dans un vrai bac à sable (jumelle SQLite de la migration PostgreSQL 031).

ALTER TABLE ateliers ADD COLUMN bac_a_sable TEXT NOT NULL DEFAULT 'auto'
    CHECK (bac_a_sable IN ('auto', 'docker', 'podman', 'windows_sandbox', 'bubblewrap', 'sandbox_exec', 'aucun'));
