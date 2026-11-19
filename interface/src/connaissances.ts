// Connaissances par domaine (lot H) : types et accès à l'API du Core.

import { appeler, envoyer, unSeul } from "./api";

export interface SourceCitee {
  titre: string;
  url: string;
}

export interface ResumeDomaine {
  id: string;
  nom: string;
  description: string;
  mots_cles: string[];
  prive: boolean;
  niveau: number;
  lacunes: string[];
  extrait_le: string | null;
  revu_le: string | null;
  cree_le: string;
  maj_le: string;
  nb_fiches: number;
  nb_questions: number;
  en_attente: number;
  en_cours: boolean;
}

export interface Fiche {
  id: string;
  concept: string;
  contenu: string;
  sources: SourceCitee[];
  maj_le: string;
}

export interface QuestionControle {
  id: string;
  question: string;
  reponse: string;
  sources: SourceCitee[];
  cree_le: string;
}

export interface EntreeJournalDomaine {
  id: number;
  horodatage: string;
  type: "creation" | "modification" | "extraction" | "report" | "revue" | "erreur";
  resume: string;
  contenu: {
    score?: number;
    lacunes?: string[];
    missions?: string[];
    questions?: { question: string; maitrise: boolean; commentaire: string }[];
    mission_id?: string;
  };
}

export interface ExtractionDomaine {
  mission_id: string;
  statut: "en_attente" | "faite" | "echec";
  erreur: string | null;
  objectif: string;
  cree_le: string;
  faite_le: string | null;
}

export interface DetailDomaine extends Omit<ResumeDomaine, "nb_fiches" | "nb_questions" | "en_attente"> {
  carte: string;
  fiches: Fiche[];
  questions: QuestionControle[];
  journal: EntreeJournalDomaine[];
  extractions: ExtractionDomaine[];
}

export interface NouveauDomaine {
  nom: string;
  description: string;
  mots_cles: string[];
  prive: boolean;
}

const chemin = (id: string) => `/v1/connaissances/${encodeURIComponent(id)}`;

export const listerDomaines = () =>
  unSeul("connaissances", () => appeler<{ domaines: ResumeDomaine[]; scientifique: boolean }>("/v1/connaissances"));
export const lireDomaine = (id: string) => unSeul(`domaine:${id}`, () => appeler<DetailDomaine>(chemin(id)));
export const creerDomaine = (d: NouveauDomaine) => envoyer<{ id: string }>("/v1/connaissances", d);
export const modifierDomaine = (id: string, d: Partial<NouveauDomaine>) => appeler<DetailDomaine>(chemin(id), { methode: "PATCH", corps: d });
export const extraireDomaine = (id: string) => envoyer<{ lancee: boolean; rattachees: number }>(`${chemin(id)}/extraire`);
export const reviserDomaine = (id: string) => envoyer<{ id: string }>(`${chemin(id)}/reviser`);

/** « tomate, semis ; potager » → ["tomate", "semis", "potager"] */
export function lireMotsCles(texte: string): string[] {
  const vus: string[] = [];
  for (const mot of texte.split(/[,;\n]/)) {
    const propre = mot.trim().replace(/\s+/g, " ");
    if (propre && !vus.some((v) => v.toLowerCase() === propre.toLowerCase())) vus.push(propre);
  }
  return vus.slice(0, 20);
}

export interface Noeud {
  texte: string;
  enfants: Noeud[];
}

/** Carte conceptuelle : listes imbriquées du Markdown rendues en arbre (le reste en texte riche). */
export function arbreCarte(source: string): { arbre: Noeud[]; reste: string } {
  const racine: Noeud = { texte: "", enfants: [] };
  const pile: { retrait: number; noeud: Noeud }[] = [{ retrait: -1, noeud: racine }];
  const reste: string[] = [];
  for (const ligne of source.replace(/\r\n/g, "\n").split("\n")) {
    const m = /^(\s*)(?:[-*•]|\d+[.)])\s+(.*)$/.exec(ligne);
    if (!m) {
      if (ligne.trim()) reste.push(ligne);
      continue;
    }
    const retrait = (m[1] ?? "").replace(/\t/g, "  ").length;
    while (pile.length > 1 && (pile.at(-1)?.retrait ?? -1) >= retrait) pile.pop();
    const noeud: Noeud = { texte: m[2] ?? "", enfants: [] };
    pile.at(-1)?.noeud.enfants.push(noeud);
    pile.push({ retrait, noeud });
  }
  return { arbre: racine.enfants, reste: reste.join("\n") };
}
