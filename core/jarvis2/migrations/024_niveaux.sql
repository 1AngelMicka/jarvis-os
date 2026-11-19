-- 024 — Niveaux de confidentialité des souvenirs et des blocs : public, semi_prive, prive.
-- Vers un moteur externe : « public » part partout (noyau, blocs, souvenirs trouvés, nouveautés) ; « semi_prive »
-- part seulement s'il est trouvé pertinent pour le message ; « prive » ne part jamais.
-- Invariant tenu par le code : niveau = 'prive' ⇔ confidentialite = 'local_uniquement' (les deux colonnes restent).

ALTER TABLE memoires
    ADD COLUMN niveau text NOT NULL DEFAULT 'semi_prive' CHECK (niveau IN ('public', 'semi_prive', 'prive'));

-- Reprise : privé si local uniquement, noyau public (il partait déjà partout), le reste semi-privé
UPDATE memoires SET niveau = CASE
    WHEN confidentialite = 'local_uniquement' THEN 'prive'
    WHEN tags @> ARRAY['noyau']::text[] THEN 'public'
    ELSE 'semi_prive'
END;

ALTER TABLE memory_blocks
    ADD COLUMN niveau text NOT NULL DEFAULT 'public' CHECK (niveau IN ('public', 'semi_prive', 'prive'));

UPDATE memory_blocks SET niveau = CASE WHEN confidentialite = 'local_uniquement' THEN 'prive' ELSE 'public' END;
