import { describe, expect, it } from "vitest";

import { decouperBlocs, enLigne } from "./texte";

describe("decouperBlocs", () => {
  it("reconnaît code, titres, listes et paragraphes", () => {
    const blocs = decouperBlocs("# Titre\n\nUn paragraphe\nsur deux lignes.\n\n- a\n- b\n\n```py\nx = 1\n```\n1. un\n2. deux");
    expect(blocs.map((b) => b.type)).toEqual(["titre", "paragraphe", "liste", "code", "liste"]);
    expect(blocs[3]).toEqual({ type: "code", langue: "py", texte: "x = 1" });
    expect(blocs[4]).toEqual({ type: "liste", ordonnee: true, items: ["un", "deux"] });
  });

  it("garde le HTML comme du texte", () => {
    const blocs = decouperBlocs("<img src=x onerror=alert(1)>");
    expect(blocs).toEqual([{ type: "paragraphe", texte: "<img src=x onerror=alert(1)>" }]);
  });
});

describe("enLigne", () => {
  it("ne crée de lien que vers http(s)", () => {
    expect(enLigne("[x](javascript:alert(1))")).toEqual(["[x](javascript:alert(1))"]);
    const noeuds = enLigne("voir [doc](https://exemple.fr) et `code`");
    expect(noeuds).toHaveLength(4);
  });
});
