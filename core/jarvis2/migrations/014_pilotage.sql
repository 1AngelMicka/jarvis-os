-- 014 — JARVIS pilote l'interface : règles de protection, commandes rapides sans IA, « toujours autoriser » (🟡),
-- mode de pilotage (oui / demander / non).

-- Registre de règles de protection : « ne touche jamais à X » (interdire) / « demande-moi avant Y » (demander).
-- Le motif (jokers « * ») est cherché dans le nom, le résumé et les paramètres de chaque action demandée.
CREATE TABLE regles_protection (
    id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    genre    text NOT NULL CHECK (genre IN ('interdire', 'demander')),
    motif    text NOT NULL CHECK (char_length(motif) BETWEEN 2 AND 200),
    libelle  text NOT NULL CHECK (char_length(libelle) BETWEEN 1 AND 200),
    origine  text NOT NULL DEFAULT 'utilisateur' CHECK (origine IN ('utilisateur', 'jarvis')),
    cree_par text NOT NULL,
    cree_le  timestamptz NOT NULL DEFAULT now()
);

-- Commandes rapides : une phrase reconnue par un motif → une action déclarée (🟢🟡🔴), sans IA, jamais de shell.
CREATE TABLE commandes_rapides (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    motif                text NOT NULL CHECK (char_length(motif) BETWEEN 2 AND 200),
    cible                text NOT NULL CHECK (cible IN ('interface', 'core')),
    action               text NOT NULL CHECK (char_length(action) BETWEEN 1 AND 80),
    parametres           jsonb NOT NULL DEFAULT '{}',
    priorite             integer NOT NULL DEFAULT 0 CHECK (priorite BETWEEN -100 AND 100),
    phrase_test          text NOT NULL CHECK (char_length(phrase_test) BETWEEN 1 AND 200),
    actif                boolean NOT NULL DEFAULT true,
    utilisations         integer NOT NULL DEFAULT 0,
    derniere_utilisation timestamptz,
    cree_le              timestamptz NOT NULL DEFAULT now(),
    maj_le               timestamptz NOT NULL DEFAULT now()
);

-- « Toujours autoriser » : une action 🟡 approuvée une fois s'exécute ensuite sans demande (jamais 🔴, jamais un clic
-- à l'écran ou dans un navigateur). Retirer une autorisation est libre (🟢 : cela protège).
CREATE TABLE autorisations_permanentes (
    action               text PRIMARY KEY,
    cree_par             uuid REFERENCES appareils (id) ON DELETE SET NULL,
    cree_le              timestamptz NOT NULL DEFAULT now(),
    utilisations         integer NOT NULL DEFAULT 0,
    derniere_utilisation timestamptz
);

INSERT INTO etat_systeme (cle, valeur) VALUES ('pilotage', '{"mode": "demander"}') ON CONFLICT (cle) DO NOTHING;

GRANT SELECT, INSERT, UPDATE, DELETE ON regles_protection, commandes_rapides, autorisations_permanentes TO jarvis2_app;
