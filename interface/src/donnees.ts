// « Où partent mes données » : libellés et filtres de la page (sans React, testés dans donnees.test.ts).

import { LIBELLES_NIVEAU } from "./niveaux";
import type { CarteFlux, CompteursNiveaux, DestinationFlux, FluxDonnee, MemoireFlux, Niveau } from "./types";

export type Filtre = "tout" | "sort" | "reste";

export const FILTRES: readonly { id: Filtre; nom: string }[] = [
  { id: "tout", nom: "Tout" },
  { id: "sort", nom: "Sort du PC" },
  { id: "reste", nom: "Reste sur le PC" },
];

export const DESTINATIONS: Record<DestinationFlux, { nom: string; ton: "ok" | "attention" | undefined }> = {
  pc: { nom: "Reste sur le PC", ton: "ok" },
  reseau: { nom: "Réseau privé", ton: undefined },
  internet: { nom: "Internet", ton: "attention" },
  variable: { nom: "Selon le programme", ton: "attention" },
};

export const ETATS: Record<FluxDonnee["etat"], string> = {
  actif: "Actif",
  sur_accord: "Sur votre accord",
  inactif: "Inactif",
};

/** Flux qui correspondent au filtre (un flux « variable » ne reste pas forcément sur le PC : il compte comme sortant). */
export function filtrerFlux(flux: readonly FluxDonnee[], filtre: Filtre): FluxDonnee[] {
  if (filtre === "sort") return flux.filter((f) => !f.local);
  if (filtre === "reste") return flux.filter((f) => f.local);
  return [...flux];
}

/** Phrase de synthèse, sans jargon : combien de fonctions font sortir des données en ce moment. */
export function phraseResume(r: CarteFlux["resume"]): string {
  if (r.sortants_actifs === 0) return "En ce moment, rien ne sort du PC sans votre accord.";
  const s = r.sortants_actifs > 1 ? "s" : "";
  const internet = r.internet_actifs ? `, dont ${String(r.internet_actifs)} vers Internet` : "";
  return `${String(r.sortants_actifs)} fonction${s} active${s} envoie${r.sortants_actifs > 1 ? "nt" : ""} des données hors du PC${internet}.`;
}

// --- Section « Mémoire » (lot 14 · C 14) : ce que chaque niveau laisse partir vers le cloud ---

/** Une ligne par règle du Core, avec le nombre de souvenirs du niveau (règles déjà validées par `lireMemoireFlux`). */
export function lignesMemoire(m: MemoireFlux): { niveau: Niveau; nom: string; nombre: number; libelle: string; vers_cloud: string }[] {
  return m.regles.map((r) => ({ niveau: r.niveau, nom: LIBELLES_NIVEAU[r.niveau].nom, nombre: m.niveaux[r.niveau], libelle: r.libelle, vers_cloud: r.vers_cloud }));
}

/** Synthèse sans jargon des niveaux, du plus ouvert au plus fermé. */
export function phraseMemoire(n: CompteursNiveaux): string {
  const total = n.public + n.semi_prive + n.prive;
  if (total === 0) return "Aucun souvenir pour l'instant.";
  const nb = (v: number) => v.toLocaleString("fr-FR");
  const peut = n.public > 1 ? "peuvent" : "peut";
  return `Sur ${nb(total)} souvenir${total > 1 ? "s" : ""}, ${nb(n.public)} ${peut} partir vers une IA externe, ${nb(n.semi_prive)} seulement s'il${n.semi_prive > 1 ? "s sont utiles" : " est utile"} au message, ${nb(n.prive)} jamais.`;
}
