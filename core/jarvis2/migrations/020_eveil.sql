-- 020 — Éveil « Dis Jarvis » (phase 13, lot K1) : réglages de l'éveil et de la conversation vocale.
-- Mémoire d'ambiance et étage acoustique openWakeWord désactivés par défaut ; fenêtre de relance de 6 s.
-- Les phrases d'ambiance ne sont jamais écrites en base : seuls les souvenirs qu'en retient une IA locale le sont.

INSERT INTO etat_systeme (cle, valeur)
VALUES ('eveil', '{"ambiance": false, "openwakeword": false, "relance_s": 6}')
ON CONFLICT (cle) DO NOTHING;
