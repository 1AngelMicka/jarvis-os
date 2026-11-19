import { describe, expect, it } from "vitest";

import {
  AVANCE,
  casqueParNom,
  commandeArret,
  DetecteurCoupure,
  FileSynthese,
  mesurerDelai,
  type MoteurSynthese,
  REGLAGES_DEFAUT,
  type Sortie,
  textePourLecture,
} from "./synthese";

// Fausses valeurs, assemblées pour ne ressembler à rien de réel dans le dépôt
const CLE_FACTICE = ["sk", "proj", "abcdefghijklmnopqrstuvwxyz0123"].join("-");
const JETON_FACTICE = ["ghp", "abcdefghijklmnopqrstuvwxyz0123456789"].join("_");

const attendre = (ms: number) =>
  new Promise<void>((r) => {
    setTimeout(r, ms);
  });

/** Sortie simulée : la synthèse de chaque phrase prend un temps choisi ; on note l'ordre de lecture. */
function fausseSortie(options: { delais?: Record<string, number>; echecs?: string[]; systeme?: boolean } = {}) {
  const lues: string[] = [];
  const parSysteme: string[] = [];
  let enCours = 0;
  let maxEnCours = 0;
  const abandons: string[] = [];
  const sortie: Sortie = {
    async synthetiser(texte, _moteur, signal) {
      enCours += 1;
      maxEnCours = Math.max(maxEnCours, enCours);
      await attendre(options.delais?.[texte] ?? 5);
      enCours -= 1;
      if (signal.aborted) {
        abandons.push(texte);
        throw new Error("abandon");
      }
      if (options.echecs?.includes(texte)) throw new Error("409");
      return new TextEncoder().encode(texte).buffer;
    },
    async jouer(audio) {
      lues.push(new TextDecoder().decode(audio));
      await attendre(2);
    },
    async direSysteme(texte) {
      parSysteme.push(texte);
      lues.push(`[système] ${texte}`);
      await attendre(2);
    },
    systemeDisponible: () => options.systeme ?? true,
    arreter: () => undefined,
    niveau: () => 0.2,
  };
  return { sortie, lues, parSysteme, abandons, max: () => maxEnCours };
}

const reglages = (moteur: MoteurSynthese) => () => ({ ...REGLAGES_DEFAUT, moteur });
const evenements = () => {
  const e = { debuts: 0, fins: 0 };
  return {
    e,
    rappels: {
      debut: () => {
        e.debuts += 1;
      },
      fin: () => {
        e.fins += 1;
      },
    },
  };
};

async function jusqua(condition: () => boolean, max = 500): Promise<void> {
  for (let t = 0; t < max && !condition(); t += 5) await attendre(5);
}

describe("secrets masqués avant la lecture à voix haute", () => {
  it("masque clés, mots de passe et codes, garde la phrase lisible", () => {
    const dit = textePourLecture(`Votre **clé** ${CLE_FACTICE}, mot de passe : Hunter2024! et le code est 482913.`);
    expect(dit).not.toMatch(/sk-proj|Hunter2024|482913|\*/);
    expect(dit).toContain("mot de passe : (secret masqué)");
  });

  it("dit les étiquettes posées par le Core sans les épeler", () => {
    expect(textePourLecture("La clé est [SECRET : clé OpenAI].")).toBe("La clé est (secret masqué).");
  });

  it("laisse le texte ordinaire intact", () => {
    expect(textePourLecture("Il est 14 h 30, la réunion commence.")).toBe("Il est 14 h 30, la réunion commence.");
  });
});

describe("« stop » pendant la lecture", () => {
  it("reconnaît l'arrêt et le silence, rien d'autre", () => {
    expect(commandeArret("Stop.")).toBe("stop");
    expect(commandeArret("Jarvis, arrête")).toBe("stop");
    expect(commandeArret("tais-toi !")).toBe("silence");
    expect(commandeArret("Silence")).toBe("silence");
    expect(commandeArret("stop le minuteur de la cuisine")).toBeNull();
    expect(commandeArret("Quelle heure est-il ?")).toBeNull();
  });
});

describe("file de synthèse", () => {
  it("synthétise en parallèle et lit dans l'ordre, même si une phrase arrive avant la précédente", async () => {
    const f = fausseSortie({ delais: { "Une.": 40, "Deux.": 5, "Trois.": 10 } });
    const { e, rappels } = evenements();
    const file = new FileSynthese(f.sortie, rappels, reglages("piper"));
    file.dire("Une.");
    file.dire("Deux.");
    file.dire("Trois.");
    await jusqua(() => f.lues.length === 3);
    expect(f.lues).toEqual(["Une.", "Deux.", "Trois."]);
    expect(f.max()).toBe(3); // les trois en même temps
    await jusqua(() => !file.parle);
    expect(e).toEqual({ debuts: 1, fins: 1 });
  });

  it("garde au plus quelques phrases d'avance", async () => {
    const f = fausseSortie();
    const file = new FileSynthese(f.sortie, evenements().rappels, reglages("elevenlabs"));
    for (let i = 0; i < 8; i++) file.dire(`Phrase ${String(i)}.`);
    await jusqua(() => f.lues.length === 8, 2000);
    expect(f.lues).toHaveLength(8);
    expect(f.max()).toBeLessThanOrEqual(AVANCE);
  });

  it("dit la phrase avec la voix du système si le moteur échoue : jamais muet", async () => {
    const f = fausseSortie({ echecs: ["Deux."] });
    const file = new FileSynthese(f.sortie, evenements().rappels, reglages("elevenlabs"));
    file.dire("Une.");
    file.dire("Deux.");
    file.dire("Trois.");
    await jusqua(() => f.lues.length === 3);
    expect(f.lues).toEqual(["Une.", "[système] Deux.", "Trois."]);
  });

  it("voix de l'appareil choisie mais absente : Piper prend le relais", async () => {
    const f = fausseSortie({ systeme: false });
    const file = new FileSynthese(f.sortie, evenements().rappels, reglages("navigateur"));
    file.dire("Bonjour.");
    await jusqua(() => f.lues.length === 1);
    expect(f.lues).toEqual(["Bonjour."]);
  });

  it("voix de l'appareil : rien ne passe par le Core", async () => {
    const f = fausseSortie();
    const file = new FileSynthese(f.sortie, evenements().rappels, reglages("navigateur"));
    file.dire("Bonjour.");
    await jusqua(() => f.lues.length === 1);
    expect(f.parSysteme).toEqual(["Bonjour."]);
    expect(f.max()).toBe(0);
  });

  it("arrêter coupe la file et abandonne les synthèses en route", async () => {
    const f = fausseSortie({ delais: { "Une.": 5, "Deux.": 60, "Trois.": 60 } });
    const file = new FileSynthese(f.sortie, evenements().rappels, reglages("piper"));
    file.dire("Une.");
    file.dire("Deux.");
    file.dire("Trois.");
    await jusqua(() => f.lues.length === 1);
    file.arreter();
    await attendre(90);
    expect(f.lues).toEqual(["Une."]);
    expect(f.abandons.sort()).toEqual(["Deux.", "Trois."]);
    expect(file.parle).toBe(false);
  });

  it("masque les secrets avant d'envoyer la phrase au moteur", async () => {
    const f = fausseSortie();
    const file = new FileSynthese(f.sortie, evenements().rappels, reglages("piper"));
    file.dire(`Le jeton est ${JETON_FACTICE}.`);
    await jusqua(() => f.lues.length === 1);
    expect(f.lues[0]).toBe("Le jeton est (secret masqué).");
  });
});

describe("coupure quand on parle par-dessus", () => {
  it("mesure le délai haut-parleur → micro", () => {
    const enveloppe = Array.from({ length: 120 }, (_, i) => (Math.floor(i / 7) % 2 ? 0.1 : 0));
    const micro = [...Array<number>(8).fill(0), ...enveloppe.slice(0, -8).map((x) => x * 0.3)];
    expect(mesurerDelai(enveloppe, micro)).toBe(80);
    expect(mesurerDelai(Array<number>(50).fill(0), micro.slice(0, 50))).toBeNull();
  });

  it("reconnaît un casque à son nom", () => {
    expect(casqueParNom(["Casque (WH-1000XM4)"])).toBe(true);
    expect(casqueParNom(["Haut-parleurs (Realtek)"])).toBe(false);
  });

  it("ne se coupe pas sur son propre écho, se coupe quand on parle fort par-dessus", () => {
    const d = new DetecteurCoupure(false, false);
    for (let i = 0; i < 300; i++) expect(d.trame(0.3 * 0.2, 0.2)).toBe(false);
    expect(d.mode).toBe("rms");
    let coupe = false;
    for (let i = 0; i < 20; i++) coupe = d.trame(0.3, 0.2) || coupe;
    expect(coupe).toBe(true);
  });

  it("une toux (50 ms) ne coupe pas ; il faut 120 ms de parole de suite", () => {
    const d = new DetecteurCoupure(true, false);
    const r = [...Array.from({ length: 5 }, () => d.trame(0.5, 0)), ...Array.from({ length: 10 }, () => d.trame(0, 0))];
    expect(r.some(Boolean)).toBe(false);
    expect(Array.from({ length: 12 }, () => d.trame(0.5, 0)).some(Boolean)).toBe(true);
  });

  it("devine un casque quand le micro n'entend pas JARVIS", () => {
    const d = new DetecteurCoupure(false, false);
    for (let i = 0; i < 150; i++) d.trame(0.001, 0.3);
    expect(d.casque).toBe(true);
  });
});
