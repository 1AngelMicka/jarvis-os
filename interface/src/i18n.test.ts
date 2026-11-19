import { afterEach, describe, expect, it } from "vitest";

import { appliquerLangue, type Cle, detecterLangue, DICTIONNAIRES, interpoler, LANGUES, parametresDe, t, tn, traduire } from "./i18n";
import { en } from "./i18n/en";
import { fr } from "./i18n/fr";
import { CATEGORIES, chercherSections, SECTIONS } from "./reglages";

const clesFr = Object.keys(fr).sort();
const clesEn = Object.keys(en).sort();

afterEach(() => {
  appliquerLangue("fr");
});

describe("dictionnaires", () => {
  it("chaque clé du français existe en anglais", () => {
    expect(clesFr.filter((c) => !(c in en))).toEqual([]);
  });

  it("aucune clé anglaise inconnue du français", () => {
    expect(clesEn.filter((c) => !(c in fr))).toEqual([]);
  });

  it("aucune valeur vide, dans aucune langue", () => {
    for (const l of LANGUES) {
      const vides = Object.entries(DICTIONNAIRES[l.id]).filter(([, v]) => !v.trim());
      expect(vides.map(([c]) => `${l.id}:${c}`)).toEqual([]);
    }
  });

  it("mêmes paramètres {x} dans les deux langues", () => {
    const ecarts = clesFr.filter((c) => {
      const cle = c as Cle;
      return parametresDe(fr[cle]).join(",") !== parametresDe(en[cle]).join(",");
    });
    expect(ecarts).toEqual([]);
  });

  it("chaque pluriel a ses deux formes", () => {
    for (const c of clesFr) {
      if (c.endsWith(".un")) expect(clesFr).toContain(c.replace(/\.un$/, ".autre"));
      if (c.endsWith(".autre")) expect(clesFr).toContain(c.replace(/\.autre$/, ".un"));
    }
  });

  it("chaque catégorie et section des réglages a son titre et sa description", () => {
    const manquantes = [
      ...CATEGORIES.flatMap((c) => [`reglages.cat.${c.id}.nom`, `reglages.cat.${c.id}.description`]),
      ...SECTIONS.flatMap((s) => [`reglages.section.${s.id}.titre`, `reglages.section.${s.id}.description`]),
    ].filter((c) => !(c in fr));
    expect(manquantes).toEqual([]);
  });
});

describe("langue du navigateur", () => {
  it("anglais si la langue préférée commence par en", () => {
    expect(detecterLangue(["en-US", "fr-FR"])).toBe("en");
    expect(detecterLangue(["EN"])).toBe("en");
    expect(detecterLangue(["en-GB"])).toBe("en");
  });

  it("français sinon, et par défaut", () => {
    expect(detecterLangue(["fr-FR", "en-US"])).toBe("fr");
    expect(detecterLangue(["de-DE"])).toBe("fr");
    expect(detecterLangue([])).toBe("fr");
    expect(detecterLangue(undefined)).toBe("fr");
  });
});

describe("interpolation", () => {
  it("remplace les paramètres connus, garde les autres", () => {
    expect(interpoler("{nom} indisponible : {detail}.", { nom: "Ollama", detail: "arrêté" })).toBe("Ollama indisponible : arrêté.");
    expect(interpoler("cherche {sujet}", { nom: "x" })).toBe("cherche {sujet}");
    expect(interpoler("sans paramètre")).toBe("sans paramètre");
  });

  it("met les nombres au format de la langue", () => {
    appliquerLangue("fr");
    expect(t("etat.enAttente", { n: 1234 })).toBe("1 234 en attente");
    appliquerLangue("en");
    expect(t("etat.enAttente", { n: 1234 })).toBe("1,234 pending");
  });

  it("t et traduire suivent la langue", () => {
    expect(traduire("en", "accueil.titre")).toBe("What would you like to do?");
    appliquerLangue("en");
    expect(t("vue.reglages")).toBe("Settings");
    appliquerLangue("fr");
    expect(t("vue.reglages")).toBe("Réglages");
  });

  it("pluriels selon la langue : 0 au singulier en français, au pluriel en anglais", () => {
    appliquerLangue("fr");
    expect(tn("msg.souvenirs", 0)).toBe("0 souvenir");
    expect(tn("msg.souvenirs", 2)).toBe("2 souvenirs");
    appliquerLangue("en");
    expect(tn("msg.souvenirs", 0)).toBe("0 memories");
    expect(tn("msg.souvenirs", 1)).toBe("1 memory");
  });
});

describe("réglages traduits", () => {
  it("titres dans la langue courante, recherche dans les deux langues", () => {
    appliquerLangue("en");
    expect(SECTIONS.find((s) => s.id === "themes")?.titre).toBe("Theme");
    expect(chercherSections("language")[0]?.id).toBe("langue");
    expect(chercherSections("thème")[0]?.id).toBe("themes");
    appliquerLangue("fr");
    expect(chercherSections("langue")[0]?.id).toBe("langue");
  });
});
