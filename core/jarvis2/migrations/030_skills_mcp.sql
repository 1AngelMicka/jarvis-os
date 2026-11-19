-- 030 — Skills SKILL.md importés et réglages du client MCP (phase 14, point 12).
-- Un skill est une copie, dans le dossier des données, d'un dossier ou d'une archive choisi par l'utilisateur (la
-- source n'est jamais modifiée). Il reste inutilisable tant qu'il n'est pas revu et approuvé par la file
-- d'approbations ; l'empreinte SHA-256 du dossier est enregistrée à l'approbation : un fichier modifié le bloque
-- jusqu'à une nouvelle revue. Les capacités dangereuses (shell, réseau, écriture) ne sont permises que cochées une à
-- une pendant la revue.

CREATE TABLE skills (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    nom                  text NOT NULL UNIQUE CHECK (char_length(nom) BETWEEN 1 AND 64),
    description          text NOT NULL CHECK (char_length(description) BETWEEN 1 AND 1024),
    origine              text NOT NULL CHECK (origine IN ('dossier', 'archive')),
    source               text NOT NULL CHECK (char_length(source) <= 500),  -- nom du dossier ou de l'archive
    dossier              text NOT NULL,                                    -- copie dans le dossier des données
    -- non_fiable : jamais revu (inutilisable) ; instructions : approuvé, texte seulement ;
    -- capacites : approuvé avec des capacités dangereuses cochées pendant la revue
    confiance            text NOT NULL DEFAULT 'non_fiable'
        CHECK (confiance IN ('non_fiable', 'instructions', 'capacites')),
    statut               text NOT NULL DEFAULT 'a_revoir' CHECK (statut IN ('a_revoir', 'approuve', 'bloque')),
    capacites            jsonb NOT NULL DEFAULT '[]',  -- détectées : [{capacite, fichier, raison}]
    capacites_acceptees  jsonb NOT NULL DEFAULT '[]',  -- cochées à la revue : ["shell", …]
    fichiers             jsonb NOT NULL DEFAULT '[]',  -- [{chemin, taille, script}]
    empreinte            text NOT NULL,                -- empreinte du dossier à l'import
    empreinte_approuvee  text,                         -- empreinte au moment de l'approbation
    raison_blocage       text,
    importe_par          text NOT NULL,
    approuve_par         text,
    cree_le              timestamptz NOT NULL DEFAULT now(),
    maj_le               timestamptz NOT NULL DEFAULT now(),
    approuve_le          timestamptz,
    bloque_le            timestamptz
);
CREATE INDEX skills_statut_idx ON skills (statut, nom);

GRANT SELECT, INSERT, UPDATE, DELETE ON skills TO jarvis2_app;

-- Client MCP : outils proposés au modèle par tour (11 au plus, outil de recherche compris), choix par le sens,
-- relance automatique (une seule) d'un serveur planté. Écrite par UPDATE seulement.
INSERT INTO etat_systeme (cle, valeur)
VALUES ('mcp', '{"max_outils": 8, "par_le_sens": true, "relance_auto": true}')
ON CONFLICT (cle) DO NOTHING;
