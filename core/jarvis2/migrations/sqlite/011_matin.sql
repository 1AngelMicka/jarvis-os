-- 011 — Accueil du matin : mode (parlé, texte, désactivé), lieu choisi dans les réglages, dernier accueil par appareil.
INSERT INTO etat_systeme (cle, valeur) VALUES ('matin', '{"mode": "parle", "vus": {}}') ON CONFLICT (cle) DO NOTHING;
