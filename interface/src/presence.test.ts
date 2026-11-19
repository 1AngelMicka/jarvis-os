import { describe, expect, it } from "vitest";

import { densitePixels, etatPresence, MOUVEMENTS, rapprocher, sphereFibonacci, voisinsParGrille } from "./presence";

const calme = { enCours: false, premierMorceau: false, parle: false, microOuvert: false, compactage: false };

describe("état de l'orbe", () => {
  it("veille par défaut, écoute quand le micro est ouvert", () => {
    expect(etatPresence(calme)).toBe("veille");
    expect(etatPresence({ ...calme, microOuvert: true })).toBe("ecoute");
  });

  it("réflexion avant le premier morceau, parole ensuite ou pendant la lecture à voix haute", () => {
    expect(etatPresence({ ...calme, enCours: true, microOuvert: true })).toBe("reflexion");
    expect(etatPresence({ ...calme, enCours: true, premierMorceau: true })).toBe("parole");
    expect(etatPresence({ ...calme, parle: true, microOuvert: true })).toBe("parole");
  });

  it("le compactage (résumé en mémoire) passe avant tout", () => {
    expect(etatPresence({ enCours: true, premierMorceau: true, parle: true, microOuvert: true, compactage: true })).toBe("compactage");
  });

  it("a un mouvement pour chacun des cinq états", () => {
    expect(Object.keys(MOUVEMENTS).sort()).toEqual(["compactage", "ecoute", "parole", "reflexion", "veille"]);
  });
});

describe("rendu", () => {
  it("borne la densité de pixels à 2", () => {
    expect(densitePixels(3)).toBe(2);
    expect(densitePixels(1.5)).toBe(1.5);
    expect(densitePixels(Number.NaN)).toBe(1);
  });

  it("glisse vers la cible de moitié à chaque demi-vie", () => {
    expect(rapprocher(0, 1, 0.5, 0.5)).toBeCloseTo(0.5);
    expect(rapprocher(0, 1, 1, 0.5)).toBeCloseTo(0.75);
  });

  it("répartit les points sur la sphère unité", () => {
    const p = sphereFibonacci(200);
    for (let i = 0; i < 200; i++) {
      expect(Math.hypot(p[i * 3] ?? 0, p[i * 3 + 1] ?? 0, p[i * 3 + 2] ?? 0)).toBeCloseTo(1, 5);
    }
  });
});

describe("voisins par grille spatiale", () => {
  it("trouve les mêmes paires qu'une comparaison exhaustive (sans plafond)", () => {
    const p = sphereFibonacci(300);
    const d = 0.25;
    const attendu = new Set<string>();
    for (let i = 0; i < 300; i++) {
      for (let j = i + 1; j < 300; j++) {
        const dx = (p[i * 3] ?? 0) - (p[j * 3] ?? 0);
        const dy = (p[i * 3 + 1] ?? 0) - (p[j * 3 + 1] ?? 0);
        const dz = (p[i * 3 + 2] ?? 0) - (p[j * 3 + 2] ?? 0);
        if (dx * dx + dy * dy + dz * dz <= d * d) attendu.add(`${String(i)}-${String(j)}`);
      }
    }
    const paires = voisinsParGrille(p, d, 1000);
    const trouve = new Set<string>();
    for (let k = 0; k < paires.length; k += 2) trouve.add(`${String(paires[k])}-${String(paires[k + 1])}`);
    expect(trouve).toEqual(attendu);
  });

  it("respecte le plafond de liens par point", () => {
    const p = sphereFibonacci(400);
    const paires = voisinsParGrille(p, 0.4, 2);
    const parPoint = new Map<number, number>();
    for (let k = 0; k < paires.length; k += 2) parPoint.set(paires[k] ?? 0, (parPoint.get(paires[k] ?? 0) ?? 0) + 1);
    expect(Math.max(...parPoint.values())).toBeLessThanOrEqual(2);
  });
});
