-- 006 — Assistant de premier lancement : terminé ou non (une installation existante le voit une fois).
INSERT INTO etat_systeme (cle, valeur) VALUES ('accueil', '{"termine": false}') ON CONFLICT (cle) DO NOTHING;
