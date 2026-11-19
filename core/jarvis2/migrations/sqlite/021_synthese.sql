-- 021 — Synthèse vocale : moteur choisi (navigateur, Piper, ElevenLabs), voix, coupure quand on parle par-dessus.
INSERT INTO etat_systeme (cle, valeur) VALUES ('synthese', '{"moteur": "navigateur", "voix_piper": "fr_FR-siwis-medium", "voix_elevenlabs": "21m00Tcm4TlvDq8ikWAM", "coupure": true}') ON CONFLICT (cle) DO NOTHING;
