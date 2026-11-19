-- 010 — Coûts et transparence : plafond de dépenses mensuel par connecteur payant (réglé par l'utilisateur).
-- NULL : aucun plafond. Au-delà, le connecteur refuse de répondre et le routeur passe à une autre IA.

ALTER TABLE connecteurs ADD COLUMN plafond_mensuel_usd double precision
    CHECK (plafond_mensuel_usd IS NULL OR plafond_mensuel_usd >= 0);
