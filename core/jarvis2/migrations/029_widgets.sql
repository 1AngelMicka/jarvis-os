-- 029 — Widgets épinglés dans le HUD (phase 14, D 16). Le fragment est celui que le Core a validé et réécrit
-- (`widgets.py`, listes fermées) ; il est validé de nouveau à chaque lecture. L'empreinte évite les doublons.

CREATE TABLE widgets_epingles (
    id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    empreinte text NOT NULL UNIQUE CHECK (char_length(empreinte) BETWEEN 8 AND 64),
    titre     text NOT NULL CHECK (char_length(titre) BETWEEN 1 AND 60),
    html      text NOT NULL CHECK (char_length(html) BETWEEN 1 AND 8000),
    cree_le   timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, DELETE ON widgets_epingles TO jarvis2_app;
