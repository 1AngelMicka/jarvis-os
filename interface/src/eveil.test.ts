import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { appliquerDecision, type DecisionEveil, type Effets, lireEcouteFond, reglerEcouteFond, suivreFinDeReponse } from "./eveil";

// Environnement « node » : une fenêtre et un stockage minimaux (minuteurs factices de vitest compris)
beforeEach(() => {
  const cible = new EventTarget();
  vi.stubGlobal(
    "window",
    Object.assign(cible, {
      setInterval: (f: () => void, t: number) => setInterval(f, t),
      clearInterval: (i: number) => {
        clearInterval(i);
      },
    }),
  );
  const valeurs = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (c: string) => valeurs.get(c) ?? null,
    setItem: (c: string, v: string) => valeurs.set(c, v),
    removeItem: (c: string) => valeurs.delete(c),
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function decision(action: DecisionEveil["action"], commande = ""): DecisionEveil {
  return { action, commande, raison: "", texte: commande, etage: 1, score: 1, juge: null, etat: "actif", phase: "reponse", jusqu_a: null };
}

function effets(): Effets & { appels: string[] } {
  const appels: string[] = [];
  return {
    appels,
    envoyer: (t) => appels.push(`envoyer:${t}`),
    arreter: () => appels.push("arreter"),
    couperVoix: () => appels.push("couper"),
    notifier: (m) => appels.push(`notifier:${m}`),
  };
}

describe("décisions de l'éveil", () => {
  it("envoie la commande et annonce une réponse à suivre", () => {
    const e = effets();
    expect(appliquerDecision(decision("envoyer", "quelle heure est-il ?"), e)).toBe(true);
    expect(e.appels).toEqual(["envoyer:quelle heure est-il ?"]);
    expect(appliquerDecision(decision("envoyer", ""), effets())).toBe(false);
  });

  it("stop arrête, silence arrête et coupe la voix, ignorer ne fait rien", () => {
    const stop = effets();
    appliquerDecision(decision("stop"), stop);
    expect(stop.appels).toEqual(["arreter"]);
    const silence = effets();
    appliquerDecision(decision("silence"), silence);
    expect(silence.appels.slice(0, 2)).toEqual(["arreter", "couper"]);
    const rien = effets();
    expect(appliquerDecision(decision("ignorer"), rien)).toBe(false);
    expect(rien.appels).toEqual([]);
    const arme = effets();
    appliquerDecision(decision("armer"), arme);
    expect(arme.appels).toEqual(["notifier:Je vous écoute."]);
  });
});

describe("fin de la réponse", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("attend la fin de la réponse et de la voix avant de le dire au Core", () => {
    vi.useFakeTimers();
    let occupe = false;
    const fins: number[] = [];
    suivreFinDeReponse(
      () => occupe,
      (t) => fins.push(t),
      100,
    );
    vi.advanceTimersByTime(300); // la réponse n'a pas encore commencé
    expect(fins).toEqual([]);
    occupe = true;
    vi.advanceTimersByTime(1000);
    expect(fins).toEqual([]);
    occupe = false;
    vi.advanceTimersByTime(100);
    expect(fins).toHaveLength(1);
    vi.advanceTimersByTime(1000);
    expect(fins).toHaveLength(1);
  });

  it("une réponse qui ne commence jamais se referme au bout de 3 s", () => {
    vi.useFakeTimers();
    const fins: number[] = [];
    suivreFinDeReponse(
      () => false,
      (t) => fins.push(t),
      100,
    );
    vi.advanceTimersByTime(3200);
    expect(fins).toHaveLength(1);
  });
});

describe("écoute en fond", () => {
  it("préférence de l'appareil, désactivée par défaut, annoncée à la console", () => {
    localStorage.removeItem("jarvis2.eveil.fond");
    expect(lireEcouteFond()).toBe(false);
    const vus: unknown[] = [];
    const suivre = (e: Event) => vus.push((e as CustomEvent<unknown>).detail);
    window.addEventListener("jarvis2:eveil-fond", suivre);
    reglerEcouteFond(true);
    expect(lireEcouteFond()).toBe(true);
    reglerEcouteFond(false);
    window.removeEventListener("jarvis2:eveil-fond", suivre);
    expect(vus).toEqual([true, false]);
  });
});
