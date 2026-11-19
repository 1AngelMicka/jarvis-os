import { describe, expect, it } from "vitest";

import { sontReduites } from "./animations";
import { adresse, CATEGORIES, chercherSections, lireAdresse, resoudre, SECTIONS, sectionsDe } from "./reglages";

describe("registre des réglages", () => {
  it("chaque catégorie a au moins une section, chaque section une catégorie connue", () => {
    for (const c of CATEGORIES) expect(sectionsDe(c.id).length).toBeGreaterThan(0);
    for (const s of SECTIONS) expect(CATEGORIES.some((c) => c.id === s.categorie)).toBe(true);
  });

  it("identifiants et alias uniques : une adresse mène à un seul endroit", () => {
    const noms = [...CATEGORIES.map((c) => c.id), ...SECTIONS.flatMap((s) => [s.id, ...(s.alias ?? [])])];
    const doublons = noms.filter((n, i) => noms.indexOf(n) !== i);
    // « appareils » est à la fois une catégorie et sa section principale : la catégorie l'emporte
    expect(doublons).toEqual(["appareils"]);
  });
});

describe("recherche", () => {
  it("trouve sans tenir compte des accents ni de la casse", () => {
    expect(chercherSections("METEO")[0]?.id).toBe("accueil-matin");
    expect(chercherSections("thème")[0]?.id).toBe("themes");
  });

  it("cherche dans les mots-clés et met le titre en premier", () => {
    expect(chercherSections("plafond")[0]?.id).toBe("couts");
    expect(chercherSections("ollama").map((s) => s.id)).toContain("connecteurs");
    expect(chercherSections("cles")[0]?.id).toBe("cles-acces");
  });

  it("tous les mots doivent correspondre ; rien pour une requête vide", () => {
    expect(chercherSections("voix zebre")).toEqual([]);
    expect(chercherSections("   ")).toEqual([]);
  });
});

describe("adresses directes", () => {
  it("catégorie, section ou alias", () => {
    expect(resoudre("voix")).toEqual({ categorie: "voix" });
    expect(resoudre("themes")).toEqual({ categorie: "apparence", section: "themes" });
    expect(resoudre("localisation")).toEqual({ categorie: "matin", section: "accueil-matin" });
    expect(resoudre("inconnu")).toBeNull();
  });

  it("lit #reglages et #reglages/<nom>, ignore les autres adresses", () => {
    expect(lireAdresse("#reglages/plafonds")).toEqual({ categorie: "cerveau", section: "couts" });
    expect(lireAdresse("#reglages")).toEqual({});
    expect(lireAdresse("#reglages/nimporte")).toEqual({});
    expect(lireAdresse("#jumeler=abc")).toBeNull();
    expect(lireAdresse("#reglagesX")).toBeNull();
  });

  it("aller-retour : l'adresse écrite se relit à l'identique", () => {
    for (const s of SECTIONS) {
      const c = { categorie: s.categorie, section: s.id };
      // « appareils » : la section porte le nom de sa catégorie, l'adresse ouvre la catégorie (même page)
      expect(lireAdresse(adresse(c))).toEqual(s.id === s.categorie ? { categorie: s.categorie } : c);
    }
  });
});

describe("animations", () => {
  it("« selon le système » suit la préférence, les autres choix l'emportent", () => {
    expect(sontReduites("systeme", true)).toBe(true);
    expect(sontReduites("systeme", false)).toBe(false);
    expect(sontReduites("reduites", false)).toBe(true);
    expect(sontReduites("normales", true)).toBe(false);
  });
});
