-- 013 — Où partent mes données : accord séparé avant d'envoyer une image jointe à un connecteur cloud.
-- NULL : jamais accordé (ou révoqué) ; JARVIS demande avant la première image envoyée à ce connecteur.

ALTER TABLE connecteurs ADD COLUMN images_accordees_le timestamptz;
