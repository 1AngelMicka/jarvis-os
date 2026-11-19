-- 022 — Voix, lot K3 : réglages de la reconnaissance du propriétaire (désactivée par défaut ; les empreintes restent
-- dans le dossier des données, jamais en base) et de la dictée globale (désactivée, corrections, styles).

INSERT INTO etat_systeme (cle, valeur)
VALUES ('proprietaire', '{"actif": false, "seuil": 0.5}'),
       ('dictee', '{"actif": false, "corrections": [], "styles": {}}')
ON CONFLICT (cle) DO NOTHING;
