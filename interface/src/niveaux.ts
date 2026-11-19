// Niveaux de confidentialité de la mémoire (lot 14 · C 14) : libellés, déduction pour un ancien Core, mise à jour
// optimiste et lecture tolérante de la section « Mémoire » de « Où partent mes données ». Sans React, testé dans
// niveaux.test.ts.

import type { BlocMemoire, CompteursNiveaux, MemoireFlux, Niveau, RegleNiveau, Souvenir, VersionSouvenir } from "./types";

export const NIVEAUX: readonly Niveau[] = ["public", "semi_prive", "prive"];

/** Libellé court (pastille, sélecteur) et explication (infobulle, texte d'aide). */
export const LIBELLES_NIVEAU: Record<Niveau, { nom: string; aide: string }> = {
  public: { nom: "public", aide: "Peut être donné à une IA externe, toujours expurgé de vos sujets exclus" },
  semi_prive: { nom: "semi-privé", aide: "Part vers une IA externe seulement s'il est utile au message, jamais d'office" },
  prive: { nom: "privé", aide: "Ne part jamais vers une IA externe : IA locales seulement" },
};

export function estNiveau(v: unknown): v is Niveau {
  return v === "public" || v === "semi_prive" || v === "prive";
}

/** Niveau d'un souvenir ; un Core antérieur ne l'envoie pas : `local_uniquement` vaut `prive`, le reste `semi_prive`. */
export function niveauSouvenir(s: Pick<Souvenir, "niveau" | "confidentialite">): Niveau {
  if (estNiveau(s.niveau)) return s.niveau;
  return s.confidentialite === "local_uniquement" ? "prive" : "semi_prive";
}

/** Niveau d'un bloc ; sans le champ (ancien Core) : `local_uniquement` vaut `prive`, le reste `public`. */
export function niveauBloc(b: Pick<BlocMemoire, "niveau" | "confidentialite">): Niveau {
  if (estNiveau(b.niveau)) return b.niveau;
  return b.confidentialite === "local_uniquement" ? "prive" : "public";
}

/** Confidentialité synchronisée avec le niveau (invariant du Core : `prive` ⇔ `local_uniquement`). */
export function confidentialiteDe(niveau: Niveau): "normal" | "local_uniquement" {
  return niveau === "prive" ? "local_uniquement" : "normal";
}

/** Applique un niveau à un souvenir de la liste (mise à jour optimiste, ou retour arrière avec l'ancien niveau). */
export function avecNiveau(liste: readonly Souvenir[], id: string, niveau: Niveau): Souvenir[] {
  return liste.map((s) => (s.id === id ? { ...s, niveau, confidentialite: confidentialiteDe(niveau) } : s));
}

/** Remplace l'ancien souvenir par le nouveau à la même place (le nouveau porte `remplace`). */
export function avecRemplacement(liste: readonly Souvenir[], ancienId: string, nouveau: Souvenir): Souvenir[] {
  return liste.map((s) => (s.id === ancienId ? { ...nouveau, remplace: true } : s));
}

/** Versions de la plus ancienne à l'actuelle : l'actuelle est celle sans fin de validité. */
export function versionsOrdonnees(versions: readonly VersionSouvenir[]): VersionSouvenir[] {
  return [...versions].sort((a, b) => {
    if (a.valid_to === null) return b.valid_to === null ? 0 : 1;
    if (b.valid_to === null) return -1;
    return a.valid_to.localeCompare(b.valid_to);
  });
}

/** Compteurs lisibles : « 12 publics · 340 semi-privés · 8 privés » (niveaux à zéro gardés : on voit qu'il n'y en a pas). */
export function phraseCompteurs(c: CompteursNiveaux): string {
  return NIVEAUX.map((n) => {
    const v = c[n];
    const nom = LIBELLES_NIVEAU[n].nom;
    return `${v.toLocaleString("fr-FR")} ${v > 1 ? `${nom}s` : nom}`;
  }).join(" · ");
}

/** Compteurs par niveau (état mémoire, carte des flux), ou null : ancien Core, réponse incomplète. */
export function lireCompteurs(v: unknown): CompteursNiveaux | null {
  if (!v || typeof v !== "object") return null;
  const o = v as Record<string, unknown>;
  const sortie = { public: 0, semi_prive: 0, prive: 0 };
  for (const n of NIVEAUX) {
    const x = o[n];
    if (typeof x !== "number" || !Number.isFinite(x) || x < 0) return null;
    sortie[n] = x;
  }
  return sortie;
}

/** Section « Mémoire » de la carte des flux, validée ; null si le Core ne la donne pas (ancien Core) ou si elle est
 * illisible. Les règles sont remises dans l'ordre public → privé ; une règle inconnue est ignorée. */
export function lireMemoireFlux(v: unknown): MemoireFlux | null {
  if (!v || typeof v !== "object") return null;
  const o = v as Record<string, unknown>;
  const niveaux = lireCompteurs(o.niveaux);
  if (!niveaux || !Array.isArray(o.regles)) return null;
  const regles: RegleNiveau[] = [];
  for (const r of o.regles as unknown[]) {
    if (!r || typeof r !== "object") continue;
    const x = r as Record<string, unknown>;
    if (!estNiveau(x.niveau) || typeof x.vers_cloud !== "string") continue;
    regles.push({ niveau: x.niveau, libelle: typeof x.libelle === "string" && x.libelle ? x.libelle : LIBELLES_NIVEAU[x.niveau].nom, vers_cloud: x.vers_cloud });
  }
  regles.sort((a, b) => NIVEAUX.indexOf(a.niveau) - NIVEAUX.indexOf(b.niveau));
  return { niveaux, regles, porte_rappel: typeof o.porte_rappel === "string" ? o.porte_rappel : "" };
}
