// « Où partent mes données » : libellés et filtres de la page (sans React, testés dans donnees.test.ts).

import type { CarteFlux, DestinationFlux, FluxDonnee } from "./types";

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
