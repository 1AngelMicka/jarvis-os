-- 016 — Connecteurs maison facultatifs (Philips Hue, OBS) : désactivés par défaut, activés par l'utilisateur.
-- L'adresse du pont ou d'OBS vit ici (base locale) ; la clé Hue et le mot de passe OBS n'y sont JAMAIS :
-- ils vivent dans le coffre local (securite/coffre.py).

CREATE TABLE connecteurs_maison (
    id      text PRIMARY KEY CHECK (id IN ('hue', 'obs')),
    actif   boolean NOT NULL DEFAULT false,
    adresse text CHECK (adresse IS NULL OR length(adresse) <= 120),
    maj_le  timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE ON connecteurs_maison TO jarvis2_app;
