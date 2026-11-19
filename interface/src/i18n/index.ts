// Traduction de l'interface, sans dépendance : deux dictionnaires typés (français de référence, anglais complet),
// `t(cle, params)` avec interpolation `{nom}`, `tn(base, n)` pour les pluriels. La langue est choisie par appareil
// (stockage local, comme le thème) ; au premier lancement, celle du navigateur. Appliquée avant le premier rendu
// (main.tsx) : `<html lang>` suit. Les composants suivent les changements par `useLangue()` (./react.ts).

import { en } from "./en";
import { type Cle, fr } from "./fr";

export type { Cle } from "./fr";

export const LANGUES = [
  { id: "fr", nom: "Français", locale: "fr-FR" },
  { id: "en", nom: "English", locale: "en-US" },
] as const;

export type Langue = (typeof LANGUES)[number]["id"];

export const DICTIONNAIRES: Record<Langue, Record<Cle, string>> = { fr, en };

export type Parametres = Record<string, string | number>;

/** Bases de pluriel : `x` quand `x.un` et `x.autre` existent toutes deux. */
export type BasePluriel = {
  [K in Cle]: K extends `${infer B}.un` ? (`${B}.autre` extends Cle ? B : never) : never;
}[Cle];

const CLE = "jarvis2.langue";

export function estLangue(valeur: unknown): valeur is Langue {
  return LANGUES.some((l) => l.id === valeur);
}

/** Langue préférée du navigateur (la première de la liste) : anglais si elle commence par « en », sinon français. */
export function detecterLangue(preferees: readonly string[] | undefined): Langue {
  const premiere = preferees?.find((l) => l.trim() !== "");
  return premiere?.trim().toLowerCase().startsWith("en") ? "en" : "fr";
}

function languesNavigateur(): readonly string[] {
  if (typeof navigator === "undefined") return [];
  return navigator.languages.length ? navigator.languages : [navigator.language];
}

/** Choix gardé sur cet appareil, sinon la langue du navigateur. */
export function lireLangue(): Langue {
  try {
    const l = localStorage.getItem(CLE);
    if (estLangue(l)) return l;
  } catch {
    /* stockage indisponible : langue du navigateur */
  }
  return detecterLangue(languesNavigateur());
}

let courante: Langue = "fr";

export function langueCourante(): Langue {
  return courante;
}

/** Locale de la langue courante, pour `toLocaleString` et `Intl` (« fr-FR », « en-US »). */
export function locale(langue: Langue = courante): string {
  return LANGUES.find((l) => l.id === langue)?.locale ?? "fr-FR";
}

/** Remplace chaque `{nom}` par le paramètre du même nom ; un `{x}` sans paramètre reste tel quel. */
export function interpoler(modele: string, params?: Parametres): string {
  if (!params) return modele;
  return modele.replace(/\{(\w+)\}/g, (tout, nom: string) => {
    const v = params[nom];
    return v === undefined ? tout : typeof v === "number" ? v.toLocaleString(locale()) : v;
  });
}

/** Noms des paramètres `{x}` d'un texte, triés (pour comparer deux langues). */
export function parametresDe(modele: string): string[] {
  return [...new Set(Array.from(modele.matchAll(/\{(\w+)\}/g), (m) => m[1] ?? ""))].sort();
}

export function traduire(langue: Langue, cle: Cle, params?: Parametres): string {
  return interpoler(DICTIONNAIRES[langue][cle], params);
}

/** Texte de la clé dans la langue courante. */
export function t(cle: Cle, params?: Parametres): string {
  return traduire(courante, cle, params);
}

/** Pluriel : `<base>.un` ou `<base>.autre` selon les règles de la langue ; `{n}` reçoit le nombre. */
export function tn(base: BasePluriel, n: number, params?: Parametres): string {
  const regle = new Intl.PluralRules(locale()).select(n);
  const cle: Cle = regle === "one" ? `${base}.un` : `${base}.autre`;
  return t(cle, { n, ...params });
}

/** Applique la langue au document et, sur choix de l'utilisateur, la garde sur cet appareil. */
export function appliquerLangue(langue: Langue, memoriser = false): void {
  courante = langue;
  if (typeof document !== "undefined") document.documentElement.lang = langue;
  if (!memoriser) return;
  try {
    localStorage.setItem(CLE, langue);
  } catch {
    /* stockage indisponible : langue gardée pour cette page seulement */
  }
}

/** Événement de fenêtre : la langue a changé (les composants qui utilisent `useLangue()` se redessinent). */
export const EVENEMENT_LANGUE = "jarvis2:langue";

/** Choix de l'utilisateur (Réglages › Interface & apparence) : appliqué, mémorisé et annoncé. */
export function choisirLangue(langue: Langue): void {
  appliquerLangue(langue, true);
  window.dispatchEvent(new CustomEvent(EVENEMENT_LANGUE, { detail: langue }));
}
