import { describe, expect, it } from "vitest";

import { arbreCarte, lireMotsCles } from "./connaissances";

describe("Connaissances", () => {
  it("lit les mots-clés sans doublon", () => {
    expect(lireMotsCles("tomate, semis ;  Tomate\npotager  bio,,")).toEqual(["tomate", "semis", "potager bio"]);
  });

  it("rend la carte conceptuelle en arbre selon le retrait", () => {
    const { arbre, reste } = arbreCarte("Introduction\n- Tomate\n  - Semis\n    - Mars\n  - Paillage\n- Compost\n");
    expect(reste).toBe("Introduction");
    expect(arbre.map((n) => n.texte)).toEqual(["Tomate", "Compost"]);
    expect(arbre[0]?.enfants.map((n) => n.texte)).toEqual(["Semis", "Paillage"]);
    expect(arbre[0]?.enfants[0]?.enfants[0]?.texte).toBe("Mars");
  });
});
