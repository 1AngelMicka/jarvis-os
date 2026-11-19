import { describe, expect, it } from "vitest";

import { analyserCommande, commandeDuRaccourci, COMMANDES, filtrerCommandes, normaliser, suggererSlash, texteAEnvoyer, themeDepuis, themeSuivant } from "./commandes";

describe("analyserCommande", () => {
  it("reconnaît une commande, ses alias et son argument", () => {
    expect(analyserCommande("/nouvelle")).toMatchObject({ type: "commande", commande: { id: "nouvelle" }, argument: "" });
    expect(analyserCommande("  /Thème   atelier clair ")).toMatchObject({ type: "commande", commande: { id: "theme" }, argument: "atelier clair" });
    expect(analyserCommande("/hist")).toMatchObject({ type: "commande", commande: { id: "historique" } });
    expect(analyserCommande("/MÉMOIRE")).toMatchObject({ type: "commande", commande: { id: "memoire" } });
    expect(analyserCommande("/chercher potager du jardin")).toMatchObject({ commande: { id: "chercher" }, argument: "potager du jardin" });
  });

  it("laisse passer le texte ordinaire et « // »", () => {
    expect(analyserCommande("Bonjour /nouvelle")).toEqual({ type: "texte" });
    expect(analyserCommande("//nouvelle n'est pas une commande")).toEqual({ type: "texte" });
    expect(texteAEnvoyer("//nouvelle n'est pas une commande")).toBe("/nouvelle n'est pas une commande");
    expect(texteAEnvoyer("  bonjour ")).toBe("bonjour");
  });

  it("signale une commande inconnue", () => {
    expect(analyserCommande("/xyz abc")).toEqual({ type: "inconnue", nom: "xyz" });
    expect(analyserCommande("/")).toEqual({ type: "inconnue", nom: "" });
  });

  it("chaque commande « / » a un nom unique, alias compris", () => {
    const noms = COMMANDES.flatMap((c) => (c.slash ? [c.slash, ...(c.alias ?? [])] : []));
    expect(new Set(noms).size).toBe(noms.length);
  });
});

describe("suggererSlash", () => {
  it("propose toutes les commandes après « / » seul", () => {
    expect(suggererSlash("/").length).toBe(COMMANDES.filter((c) => c.slash).length);
  });

  it("filtre par préfixe, puis par alias", () => {
    expect(suggererSlash("/th").map((c) => c.id)).toEqual(["theme"]);
    expect(suggererSlash("/me").map((c) => c.id)).toEqual(["memoire"]);
    expect(suggererSlash("/s").map((c) => c.id)).toEqual(["securite", "silence", "memoire", "urgence"]); // alias « souvenirs », « stop »
    expect(suggererSlash("/chut").map((c) => c.id)).toEqual(["silence"]);
  });

  it("se tait une fois l'argument commencé, ou hors commande", () => {
    expect(suggererSlash("/theme ")).toEqual([]);
    expect(suggererSlash("bonjour")).toEqual([]);
    expect(suggererSlash("//")).toEqual([]);
  });
});

describe("palette", () => {
  it("cherche sans accents dans le nom, puis dans la description et les mots-clés", () => {
    expect(filtrerCommandes("theme")[0]?.id).toBe("theme");
    expect(filtrerCommandes("conv")[0]?.id).toBe("nouvelle");
    expect(filtrerCommandes("arret")[0]?.id).toBe("urgence");
    expect(filtrerCommandes("souvenirs").map((c) => c.id)).toContain("memoire");
    expect(filtrerCommandes("introuvable zzz")).toEqual([]);
    expect(filtrerCommandes("").length).toBe(COMMANDES.length);
  });

  it("normalise", () => {
    expect(normaliser("  Thème   Épuré ")).toBe("theme epure");
  });
});

describe("thèmes", () => {
  it("reconnaît un thème par son nom ou un synonyme", () => {
    expect(themeDepuis("clair")).toBe("atelier");
    expect(themeDepuis("Studio nocturne")).toBe("studio");
    expect(themeDepuis("console")).toBe("console");
    expect(themeDepuis("JARVIS")).toBe("jarvis");
    expect(themeDepuis("")).toBeNull();
    expect(themeDepuis("arc-en-ciel")).toBeNull();
  });

  it("passe au thème suivant, en boucle", () => {
    expect(themeSuivant("jarvis")).toBe("studio");
    expect(themeSuivant("console")).toBe("jarvis");
  });
});

describe("raccourcis", () => {
  const touche = (key: string, mod: Partial<{ ctrlKey: boolean; metaKey: boolean; altKey: boolean; shiftKey: boolean }> = {}) => ({
    key,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    shiftKey: false,
    ...mod,
  });

  it("Ctrl ou Cmd + K, H, M", () => {
    expect(commandeDuRaccourci(touche("k", { ctrlKey: true }))).toBe("palette");
    expect(commandeDuRaccourci(touche("K", { metaKey: true }))).toBe("palette");
    expect(commandeDuRaccourci(touche("h", { ctrlKey: true }))).toBe("historique");
    expect(commandeDuRaccourci(touche("m", { ctrlKey: true }))).toBe("silence");
  });

  it("ignore les autres combinaisons", () => {
    expect(commandeDuRaccourci(touche("k"))).toBeNull();
    expect(commandeDuRaccourci(touche("k", { ctrlKey: true, shiftKey: true }))).toBeNull();
    expect(commandeDuRaccourci(touche("v", { ctrlKey: true }))).toBeNull();
  });
});
