// Routeur par type de tâche (14 · B 11) : types de `/v1/routes`, appels et mise en forme (route, score, état).

import { appeler, envoyer } from "./api";

export type TypeTache = "code" | "raisonnement" | "rapide" | "prive";
export type SourceClassement = "prive" | "regles" | "modele" | "defaut";
export type EtatRoute = "rodage" | "bon" | "retrogradee";
export type Avis = "positif" | "negatif";

/** Route choisie pour une réponse (meta `route` du message). */
export interface RouteMessage {
  type: TypeTache;
  libelle: string;
  raison: string;
  source: SourceClassement;
  connecteur: string | null;
  modele?: string;
  retrogradees?: { connecteur: string; score: number | null }[];
  note?: string;
}

export interface CandidatRoute {
  connecteur: string;
  nom: string;
  disponible: boolean;
  appels: number;
  succes: number;
  erreurs: number;
  latence_moy_ms: number | null;
  positifs: number;
  negatifs: number;
  score: number | null;
  etat: EtatRoute;
}

export interface RouteType {
  type: TypeTache;
  libelle: string;
  description: string;
  connecteur: string | null;
  modele: string | null;
  actuel: string | null;
  candidats: CandidatRoute[];
}

export interface EvenementRoute {
  type: TypeTache;
  connecteur: string;
  evenement: "retrogradee" | "reprise" | "retablie";
  score?: number | null;
  raison: string;
  le: string;
}

export interface TableauRoutes {
  types: RouteType[];
  classifieur: { modele: string | null; ollama_disponible: boolean; modeles: string[] };
  historique: EvenementRoute[];
  seuil: number;
  min_mesures: number;
  fenetre_jours: number;
  connecteurs: { id: string; nom: string; local: boolean }[];
}

export const lireRoutes = () => appeler<TableauRoutes>("/v1/routes");
export const reglerRoute = (type: TypeTache, connecteur: string | null, modele: string | null = null) =>
  appeler<TableauRoutes>(`/v1/routes/${type}`, { methode: "PUT", corps: { connecteur, modele } });
export const reglerClassifieur = (modele: string | null) =>
  appeler<TableauRoutes>("/v1/routes/classifieur", { methode: "PUT", corps: { modele } });
export const retablirRoute = (type: TypeTache, connecteur: string) =>
  envoyer<TableauRoutes>(`/v1/routes/${type}/retablir`, { connecteur });
export const essayerClassement = (texte: string) =>
  envoyer<{ type: TypeTache; libelle: string; raison: string; source: SourceClassement }>("/v1/routes/essai", { texte });
export const noterReponse = (messageId: number, avis: Avis | null) =>
  envoyer<{ message_id: number; retour: Avis | null }>(`/v1/messages/${String(messageId)}/retour`, { avis });

const SOURCES: Record<SourceClassement, string> = {
  prive: "sujet privé",
  regles: "règles",
  modele: "petit modèle local",
  defaut: "choix par défaut",
};

export function texteSource(source: SourceClassement): string {
  return SOURCES[source];
}

/** « Code · Claude Code » ; le nom du connecteur vient de la liste des moteurs (repli : son identifiant). */
export function texteRoute(route: RouteMessage, nom: (id: string) => string): string {
  return route.connecteur ? `${route.libelle} · ${nom(route.connecteur)}` : route.libelle;
}

const ETATS: Record<EtatRoute, string> = { rodage: "en rodage", bon: "bonne", retrogradee: "rétrogradée" };

export function texteEtat(c: Pick<CandidatRoute, "etat" | "succes" | "erreurs">, minMesures: number): string {
  if (c.etat === "rodage") {
    const manque = minMesures - c.succes - c.erreurs;
    return manque > 0 ? `${ETATS.rodage} (encore ${String(manque)} mesure${manque > 1 ? "s" : ""})` : ETATS.rodage;
  }
  return ETATS[c.etat];
}

export function texteScore(score: number | null): string {
  return score == null ? "—" : `${String(score)} / 100`;
}

/** Ton visuel d'un score : danger sous le seuil, attention à moins de 10 points, sinon neutre. */
export function tonScore(score: number | null, seuil: number): "danger" | "attention" | undefined {
  if (score == null) return undefined;
  if (score < seuil) return "danger";
  if (score < seuil + 10) return "attention";
  return undefined;
}

const EVENEMENTS: Record<EvenementRoute["evenement"], string> = {
  retrogradee: "rétrogradée",
  reprise: "reprise",
  retablie: "rétablie",
};

export function texteEvenement(e: EvenementRoute): string {
  return EVENEMENTS[e.evenement];
}
