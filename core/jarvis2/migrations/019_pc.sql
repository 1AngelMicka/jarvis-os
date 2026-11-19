-- 019 — Ressources et contrôle du PC (phase 13, lot J) : réglage du mode jeu (veille stricte), mode Windows
-- appliqué par JARVIS et réglages d'avant ce mode (remis par « Normal »). Aucune donnée personnelle.

INSERT INTO etat_systeme (cle, valeur)
VALUES ('pc', '{"jeu": "automatique", "mode": "normal", "avant": null, "modifies": []}')
ON CONFLICT (cle) DO NOTHING;
