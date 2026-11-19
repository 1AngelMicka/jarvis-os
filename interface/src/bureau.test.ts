import { describe, expect, it } from "vitest";

import { cleServeur, estGadget, lireDecision, lireLien, lirePartage, taille } from "./bureau";

describe("liens de l'application de bureau", () => {
  it("lit le lien jarvis:// mis dans le fragment par l'application", () => {
    expect(lireLien("#jarvis=jarvis%3A%2F%2Fouvrir%2Fmemoire")).toBe("jarvis://ouvrir/memoire");
    expect(lireLien("#jarvis=jarvis%3A%2F%2Fdire%3Ftexte%3Da%20b")).toBe("jarvis://dire?texte=a b");
  });
  it("ignore tout le reste", () => {
    expect(lireLien("")).toBeNull();
    expect(lireLien("#reglages/securite")).toBeNull();
    expect(lireLien("#jarvis=https%3A%2F%2Fexemple.org")).toBeNull();
    expect(lireLien("#jarvis=%E0%A4%A")).toBeNull(); // encodage cassé
    expect(lireLien(`#jarvis=${encodeURIComponent(`jarvis://dire?texte=${"a".repeat(3000)}`)}`)).toBeNull();
  });
});

describe("appel de décision", () => {
  it("n'accepte qu'un identifiant de demande", () => {
    expect(lireDecision("#decision=0F8FAD5B-D9CB-469F-A165-70867728950E")).toBe("0f8fad5b-d9cb-469f-a165-70867728950e");
    expect(lireDecision("#decision=../../v1/urgence")).toBeNull();
    expect(lireDecision("#decision=")).toBeNull();
  });
});

describe("partager vers JARVIS", () => {
  it("lit les champs du Web Share Target", () => {
    expect(lirePartage("?partage_titre=Article&partage_texte=Bonjour&partage_url=https%3A%2F%2Fa.b")).toEqual({
      titre: "Article",
      texte: "Bonjour",
      url: "https://a.b",
    });
    expect(lirePartage("?partage_texte=seul")).toEqual({ titre: "", texte: "seul", url: "" });
    expect(lirePartage("?mode=gadget")).toBeNull();
  });
});

describe("divers", () => {
  it("reconnaît le gadget", () => {
    expect(estGadget("?mode=gadget")).toBe(true);
    expect(estGadget("")).toBe(false);
  });
  it("décode la clé publique VAPID", () => {
    expect(Array.from(cleServeur("BAEC_w"))).toEqual([4, 1, 2, 255]);
  });
  it("écrit une taille lisible", () => {
    expect(taille(512)).toBe("512 o");
    expect(taille(2048)).toBe("2 Ko");
    expect(taille(3 * 1024 * 1024 + 200000)).toBe("3,2 Mo");
  });
});
