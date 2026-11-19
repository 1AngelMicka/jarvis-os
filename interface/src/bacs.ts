// Bacs à sable des ateliers (point 14 · B 9) : libellés du choix, de l'état et des événements du fil.
// Logique pure (sans React) : la vue Ateliers l'affiche, les tests la vérifient. Un Core antérieur n'envoie ni
// `bacs` ni `bac` : tout ce qui suit renvoie alors null et la vue n'affiche rien de nouveau.

import type { Atelier, BacASable } from "./types";

/** Noms de repli quand le Core ne liste pas (ou plus) le bac. */
const NOMS: Record<string, string> = {
  docker: "Docker",
  podman: "Podman",
  windows_sandbox: "Windows Sandbox",
  bubblewrap: "bubblewrap",
  sandbox_exec: "sandbox-exec",
};

/** Bacs dont le Core coupe le réseau à coup sûr (conteneurs lancés sans réseau). */
const SANS_RESEAU = new Set(["docker", "podman", "windows_sandbox", "bubblewrap", "sandbox_exec"]);

export const SANS_BAC = "Sans bac à sable 🟡";

export function nomBac(id: string, bacs: readonly BacASable[] = []): string {
  return bacs.find((b) => b.id === id)?.nom ?? NOMS[id] ?? id;
}

/** « Docker (sans réseau) », « Windows Sandbox »… */
export function descriptionBac(id: string, bacs: readonly BacASable[] = []): string {
  return SANS_RESEAU.has(id) ? `${nomBac(id, bacs)} (sans réseau)` : nomBac(id, bacs);
}

/** Libellé court d'un choix (« Automatique », « Docker », « Sans bac à sable 🟡 »). */
export function libelleChoix(choix: string, bacs: readonly BacASable[] = []): string {
  if (choix === "auto") return "Automatique";
  if (choix === "aucun") return SANS_BAC;
  return nomBac(choix, bacs);
}

export interface OptionBac {
  valeur: string;
  libelle: string;
}

/**
 * Options du sélecteur : Automatique, chaque bac détecté avec son état, puis « Sans bac à sable ».
 * Un bac indisponible reste proposé (on peut démarrer Docker ensuite) : le lancement dira pourquoi il est refusé.
 */
export function optionsBac(bacs: readonly BacASable[], actuel?: string): OptionBac[] {
  const options: OptionBac[] = [{ valeur: "auto", libelle: "Automatique (le premier disponible)" }];
  for (const b of bacs) options.push({ valeur: b.id, libelle: `${b.nom} — ${b.disponible ? "disponible" : "indisponible"}` });
  if (actuel && actuel !== "auto" && actuel !== "aucun" && !bacs.some((b) => b.id === actuel)) {
    options.push({ valeur: actuel, libelle: `${nomBac(actuel)} — non détecté` });
  }
  options.push({ valeur: "aucun", libelle: "Sans bac à sable (🟡 directement sur le PC)" });
  return options;
}

export type TonBac = "ok" | "attention" | "risque" | undefined;

export interface EtatBac {
  texte: string;
  ton: TonBac;
  /** Le prochain lancement sera refusé */
  refuse: boolean;
}

/** État lisible du bac à sable d'un atelier ; null avec un Core qui ne connaît pas les bacs à sable. */
export function etatBac(a: Pick<Atelier, "bac_a_sable" | "bac">, bacs: readonly BacASable[] = []): EtatBac | null {
  if (a.bac_a_sable === undefined && a.bac === undefined) return null;
  const refus = a.bac?.refus;
  if (refus) return { texte: `Refusé : ${refus}`, ton: "risque", refuse: true };
  if (a.bac_a_sable === "aucun") return { texte: SANS_BAC, ton: "attention", refuse: false };
  const effectif = a.bac?.effectif;
  if (effectif) {
    const auto = a.bac_a_sable === "auto" ? " · choix automatique" : "";
    return { texte: `Bac à sable : ${descriptionBac(effectif, bacs)}${auto}`, ton: "ok", refuse: false };
  }
  return { texte: `Bac à sable : ${libelleChoix(a.bac_a_sable ?? "auto", bacs)}`, ton: undefined, refuse: false };
}

function chaine(v: unknown): string {
  return typeof v === "string" ? v : "";
}

/** Libellé des événements propres aux bacs à sable ; null pour les autres types. */
export function ligneEvenementBac(type: string, c: Record<string, unknown>, bacs: readonly BacASable[] = []): string | null {
  switch (type) {
    case "bac_a_sable": {
      const avant = chaine(c.avant);
      return `Bac à sable : ${libelleChoix(chaine(c.choix) || "auto", bacs)}${avant ? ` (avant : ${libelleChoix(avant, bacs)})` : ""}`;
    }
    case "bac_a_sable_refuse":
      return `Lancement refusé, aucun bac à sable : ${chaine(c.raison) || "raison non précisée"}`;
    case "sans_bac_a_sable":
      return "Lancé sans bac à sable 🟡 : les commandes s'exécutent directement sur le PC (choix journalisé)";
    default:
      return null;
  }
}

/** Suffixe d'une consigne ou d'une autorisation qui porte `bac` (rien si le Core ne l'envoie pas). */
export function suffixeBac(c: Record<string, unknown>, bacs: readonly BacASable[] = []): string {
  if (!("bac" in c)) return "";
  const bac = chaine(c.bac);
  return bac ? ` [${descriptionBac(bac, bacs)}]` : " [sans bac à sable 🟡]";
}
