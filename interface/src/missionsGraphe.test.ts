import { describe, expect, it } from "vitest";

import { MAX_ETAPES, grouperParNiveau, lirePlan } from "./missionsGraphe";

describe("lecture du plan à cases", () => {
  it("lit les cases, le détail indenté, les dépendances et les cases cochées", () => {
    const plan = lirePlan(
      [
        "# Plan",
        "- [ ] E1 : Rassembler les sources",
        "  Chercher trois articles récents.",
        "  Les résumer.",
        "- [x] E2 : Écrire le brouillon (après E1)",
        "- [ ] E3 : Relire (Après E1, e2)",
        "Texte libre qui n'est pas une étape.",
      ].join("\n"),
    );
    expect(plan.erreurs).toEqual([]);
    expect(plan.total).toBe(3);
    expect(plan.faites).toBe(1);
    expect(plan.etapes.map((e) => [e.id, e.titre, e.apres, e.niveau, e.faite])).toEqual([
      ["E1", "Rassembler les sources", [], 0, false],
      ["E2", "Écrire le brouillon", ["E1"], 1, true],
      ["E3", "Relire", ["E1", "E2"], 2, false],
    ]);
    expect(plan.etapes[0]?.detail).toBe("Chercher trois articles récents.\nLes résumer.");
    expect(plan.etapes[1]?.detail).toBe("");
  });

  it("accepte « apres » sans accent et les fins de ligne Windows", () => {
    const plan = lirePlan("- [ ] E1 : A\r\n- [X] E2 : B (apres E1)\r\n");
    expect(plan.etapes[1]?.apres).toEqual(["E1"]);
    expect(plan.faites).toBe(1);
  });

  it("un texte sans case ne donne aucune étape (repli sur la conversation)", () => {
    const plan = lirePlan("Faire un site.\n- une puce sans case\n- [ ] sans identifiant");
    expect(plan.total).toBe(0);
    expect(plan.erreurs).toEqual([]);
  });

  it("signale un identifiant en double", () => {
    expect(lirePlan("- [ ] E1 : A\n- [ ] E1 : B").erreurs).toEqual(["Identifiant en double : E1."]);
  });

  it("signale une dépendance inconnue", () => {
    expect(lirePlan("- [ ] E1 : A (après E9)").erreurs).toEqual(["E1 dépend de E9, qui n'existe pas."]);
  });

  it("signale un cycle une seule fois", () => {
    const plan = lirePlan("- [ ] E1 : A (après E2)\n- [ ] E2 : B (après E1)\n- [ ] E3 : C (après E3)");
    expect(plan.erreurs).toEqual(["Cycle de dépendances : E1 → E2 → E1.", "Cycle de dépendances : E3 → E3."]);
  });

  it(`refuse plus de ${String(MAX_ETAPES)} étapes`, () => {
    const texte = Array.from({ length: MAX_ETAPES + 1 }, (_, i) => `- [ ] E${String(i + 1)} : Étape`).join("\n");
    expect(lirePlan(texte).erreurs).toEqual([`Trop d'étapes : ${String(MAX_ETAPES + 1)} (${String(MAX_ETAPES)} au plus).`]);
  });
});

describe("regroupement par niveau", () => {
  it("une colonne par niveau, dans l'ordre, l'ordre du plan gardé", () => {
    const { etapes } = lirePlan("- [ ] E1 : A\n- [ ] E3 : C (après E2)\n- [ ] E2 : B (après E1)\n- [ ] E4 : D");
    expect(grouperParNiveau(etapes).map((col) => col.map((e) => e.id))).toEqual([["E1", "E4"], ["E2"], ["E3"]]);
  });

  it("une liste vide ne donne aucune colonne", () => {
    expect(grouperParNiveau([])).toEqual([]);
  });
});
