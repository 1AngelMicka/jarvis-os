import { describe, expect, it } from "vitest";

import { dollars, duree, texteJauge, tonPlafond } from "./couts";

describe("mise en forme des coûts", () => {
  it("montants et durées", () => {
    expect(dollars(0)).toBe("0 $");
    expect(dollars(0.0012).replace(/\s/g, " ")).toBe("0,0012 $");
    expect(dollars(12.5).replace(/\s/g, " ")).toBe("12,50 $");
    expect(duree(450)).toBe("450 ms");
    expect(duree(2400)).toBe("2,4 s");
    expect(duree(125_000)).toBe("2 min 05 s");
  });

  it("une jauge non mesurée est « inconnu », jamais 0 %", () => {
    expect(texteJauge({ type: "five_hour", nom: "5 heures", etat: "inconnu" })).toBe("inconnu");
    expect(texteJauge({ type: "five_hour", nom: "5 heures", etat: "mesure", utilisation: 0.42 }).replace(/\s/g, " ")).toBe("42 %");
    expect(texteJauge({ type: "seven_day", nom: "7 jours", etat: "perime", utilisation: null })).toBe("mesure sans pourcentage (périmé)");
  });

  it("ton du plafond", () => {
    expect(tonPlafond(null)).toBe("ok");
    expect(tonPlafond({ plafond_usd: 10, depense_usd: 8, part: 0.8, alerte: true, atteint: false })).toBe("attention");
    expect(tonPlafond({ plafond_usd: 10, depense_usd: 10, part: 1, alerte: true, atteint: true })).toBe("danger");
  });
});
