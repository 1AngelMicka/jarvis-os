import { describe, expect, it } from "vitest";

import { COTE_MAX, dimensionsCible, ErreurImage, imagesDe, type Outils, places, planifier, POIDS_CIBLE, POIDS_MAX, poidsLisible, preparerImage, QUALITE } from "./images";

const Mo = 1024 * 1024;

describe("dimensionsCible", () => {
  it("réduit le plus grand côté à 1 600 px en gardant les proportions", () => {
    expect(dimensionsCible(4000, 3000)).toEqual({ largeur: 1600, hauteur: 1200 });
    expect(dimensionsCible(1080, 2400)).toEqual({ largeur: 720, hauteur: 1600 });
  });

  it("n'agrandit jamais", () => {
    expect(dimensionsCible(800, 600)).toEqual({ largeur: 800, hauteur: 600 });
    expect(dimensionsCible(COTE_MAX, 10)).toEqual({ largeur: COTE_MAX, hauteur: 10 });
  });
});

describe("planifier", () => {
  it("garde une petite image telle quelle", () => {
    expect(planifier("image/png", 200_000, 1200, 800)).toEqual({ action: "garder" });
  });

  it("compresse au-delà de 1 600 px ou de 1 Mo : JPEG reste JPEG, PNG et WebP en WebP", () => {
    expect(planifier("image/jpeg", 500_000, 4032, 3024)).toEqual({ action: "compresser", largeur: 1600, hauteur: 1200, type: "image/jpeg" });
    expect(planifier("image/png", POIDS_CIBLE + 1, 1000, 1000)).toEqual({ action: "compresser", largeur: 1000, hauteur: 1000, type: "image/webp" });
    expect(planifier("image/webp", 2 * Mo, 2000, 1000)).toMatchObject({ action: "compresser", type: "image/webp" });
  });

  it("ne redimensionne jamais un GIF, refusé au-delà de 3 Mo", () => {
    expect(planifier("image/gif", 2 * Mo, 4000, 4000)).toEqual({ action: "garder" });
    expect(planifier("image/gif", POIDS_MAX + 1, 100, 100)).toMatchObject({ action: "refuser" });
  });

  it("refuse les autres formats", () => {
    expect(planifier("image/svg+xml", 100, 10, 10)).toMatchObject({ action: "refuser" });
    expect(planifier("image/heic", 100, 10, 10)).toMatchObject({ action: "refuser" });
  });
});

describe("divers", () => {
  it("compte les places restantes (5 par message)", () => {
    expect(places(0)).toBe(5);
    expect(places(4)).toBe(1);
    expect(places(7)).toBe(0);
  });

  it("écrit les poids en français", () => {
    expect(poidsLisible(512)).toBe("512 o");
    expect(poidsLisible(2048)).toBe("2 Ko");
    expect(poidsLisible(1.5 * Mo)).toBe("1,5 Mo");
  });

  it("trie les fichiers collés ou déposés", () => {
    const r = imagesDe([new File(["a"], "a.png", { type: "image/png" }), new File(["b"], "b.txt", { type: "text/plain" })]);
    expect(r.images.map((f) => f.name)).toEqual(["a.png"]);
    expect(r.ignores).toBe(1);
  });
});

/** Outils factices : dimensions annoncées, encodeur qui rend un blob du poids voulu. */
function outils(largeur: number, hauteur: number, rendu: { type: string; poids: number }[]): Outils & { appels: unknown[][] } {
  const appels: unknown[][] = [];
  return {
    appels,
    dimensions: () => Promise.resolve({ largeur, hauteur }),
    encoder: (_f, l, h, type, q) => {
      appels.push([l, h, type, q]);
      const r = rendu.shift() ?? { type, poids: 10 };
      return Promise.resolve(new Blob([new Uint8Array(r.poids)], { type: r.type }));
    },
    dataUrl: (b) => Promise.resolve(`data:${b.type};base64,xx`),
  };
}

const fichier = (poids: number, type: string, nom = "photo") => new File([new Uint8Array(poids)], nom, { type });

describe("preparerImage", () => {
  it("garde une petite image sans la réencoder", async () => {
    const o = outils(800, 600, []);
    const img = await preparerImage(fichier(1000, "image/png"), o);
    expect(img).toMatchObject({ type: "image/png", poids: 1000, nom: "photo", dataUrl: "data:image/png;base64,xx" });
    expect(o.appels).toEqual([]);
  });

  it("réduit une grande photo en JPEG à 85 %", async () => {
    const o = outils(4032, 3024, [{ type: "image/jpeg", poids: 400_000 }]);
    const img = await preparerImage(fichier(5 * Mo, "image/jpeg"), o);
    expect(o.appels).toEqual([[1600, 1200, "image/jpeg", QUALITE]]);
    expect(img).toMatchObject({ type: "image/jpeg", poids: 400_000 });
  });

  it("passe en JPEG si le navigateur ne sait pas écrire le WebP", async () => {
    const o = outils(3000, 2000, [{ type: "image/png", poids: 900_000 }, { type: "image/jpeg", poids: 300_000 }]);
    const img = await preparerImage(fichier(2 * Mo, "image/png"), o);
    expect(o.appels.map((a) => a[2])).toEqual(["image/webp", "image/jpeg"]);
    expect(img.type).toBe("image/jpeg");
  });

  it("ne touche pas aux GIF et refuse ceux de plus de 3 Mo", async () => {
    const o = outils(0, 0, []);
    expect((await preparerImage(fichier(2 * Mo, "image/gif"), o)).type).toBe("image/gif");
    expect(o.appels).toEqual([]);
    await expect(preparerImage(fichier(POIDS_MAX + 1, "image/gif"), o)).rejects.toBeInstanceOf(ErreurImage);
  });

  it("refuse un format inconnu, une image illisible ou trop lourde même compressée", async () => {
    await expect(preparerImage(fichier(10, "application/pdf"), outils(1, 1, []))).rejects.toThrow(/format non pris en charge/);
    const illisible: Outils = { ...outils(1, 1, []), dimensions: () => Promise.reject(new Error("x")) };
    await expect(preparerImage(fichier(10, "image/png"), illisible)).rejects.toThrow(/illisible/);
    await expect(preparerImage(fichier(8 * Mo, "image/jpeg"), outils(8000, 6000, [{ type: "image/jpeg", poids: POIDS_MAX + 1 }]))).rejects.toThrow(/trop lourde/);
  });
});
