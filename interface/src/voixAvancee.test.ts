import { describe, expect, it } from "vitest";

import { Dictee, type EtatDicteeEnCours, ecrireCorrections, lireCorrections, messageDictee, type ResultatDictee } from "./voixAvancee";

describe("dictionnaire de corrections", () => {
  it("lit une correction par ligne, sans doublon (casse et accents ignorés)", () => {
    expect(lireCorrections("jarvice → JARVIS\n\nsans flèche\nÉloïse = Éloïse B.\neloise -> doublon\n  git  status   =>  git status")).toEqual([
      { de: "jarvice", vers: "JARVIS" },
      { de: "Éloïse", vers: "Éloïse B." },
      { de: "git status", vers: "git status" },
    ]);
    const c = [{ de: "jarvice", vers: "JARVIS" }];
    expect(lireCorrections(ecrireCorrections(c))).toEqual(c);
  });
});

class FauxMicro {
  ouvert = false;
  constructor(
    private readonly audio: Blob,
    private readonly refus = false,
  ) {}
  demarrer(): Promise<void> {
    if (this.refus) return Promise.reject(new Error("refus"));
    this.ouvert = true;
    return Promise.resolve();
  }
  arreter(): Promise<Blob> {
    this.ouvert = false;
    return Promise.resolve(this.audio);
  }
}

function dictee(audio: Blob, refus = false) {
  let temps = 0;
  const etats: EtatDicteeEnCours[] = [];
  const envois: Blob[] = [];
  const resultat: ResultatDictee = { texte: "Bonjour.", style: "phrase", programme: "winword.exe", colle: true };
  const d = new Dictee(
    () => new FauxMicro(audio, refus),
    (a) => {
      envois.push(a);
      return Promise.resolve(resultat);
    },
    (e) => etats.push(e),
    () => temps,
  );
  return {
    d,
    etats,
    envois,
    avancer: (ms: number) => {
      temps += ms;
    },
  };
}

describe("dictée maintenue", () => {
  it("raccourci tenu puis relâché : envoi, puis « Collé dans … »", async () => {
    const t = dictee(new Blob(["audio"]));
    t.d.commencer();
    t.d.commencer(); // répétition de la touche tenue : un seul micro
    expect(t.d.enCours).toBe(true);
    t.avancer(1200);
    await t.d.finir();
    expect(t.envois).toHaveLength(1);
    expect(t.etats.map((e) => e.etape)).toEqual(["ecoute", "transcription", "fini"]);
    expect(messageDictee(t.etats[2] as EtatDicteeEnCours)).toBe("Collé dans winword.exe");
  });

  it("appui trop bref : rien n'est envoyé", async () => {
    const t = dictee(new Blob(["audio"]));
    t.d.commencer();
    t.avancer(100);
    await t.d.finir();
    expect(t.envois).toHaveLength(0);
    expect(t.etats.at(-1)?.etape).toBe("repos");
  });

  it("micro refusé : message clair, relâcher ne fait rien", async () => {
    const t = dictee(new Blob(["audio"]), true);
    t.d.commencer();
    t.avancer(1000);
    await t.d.finir();
    expect(t.envois).toHaveLength(0);
    expect(t.etats.at(-1)).toEqual({ etape: "erreur", message: "Micro refusé ou indisponible." });
  });

  it("messages", () => {
    expect(messageDictee({ etape: "repos" })).toBeNull();
    expect(messageDictee({ etape: "fini", resultat: { texte: "", style: "phrase", programme: null, colle: false } })).toBe("Rien entendu");
    expect(messageDictee({ etape: "fini", resultat: { texte: "a", style: "code", programme: null, colle: false } })).toBe("Texte prêt");
  });
});
