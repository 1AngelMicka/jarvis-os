-- 024 — Niveaux de confidentialité (jumelle SQLite de la migration PostgreSQL 024).

ALTER TABLE memoires ADD COLUMN niveau TEXT NOT NULL DEFAULT 'semi_prive'
    CHECK (niveau IN ('public', 'semi_prive', 'prive'));

UPDATE memoires SET niveau = CASE
    WHEN confidentialite = 'local_uniquement' THEN 'prive'
    WHEN EXISTS (SELECT 1 FROM json_each(memoires.tags) WHERE value = 'noyau') THEN 'public'
    ELSE 'semi_prive'
END;

ALTER TABLE memory_blocks ADD COLUMN niveau TEXT NOT NULL DEFAULT 'public'
    CHECK (niveau IN ('public', 'semi_prive', 'prive'));

UPDATE memory_blocks SET niveau = CASE WHEN confidentialite = 'local_uniquement' THEN 'prive' ELSE 'public' END;
