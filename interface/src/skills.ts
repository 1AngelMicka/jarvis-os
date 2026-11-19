// Skills SKILL.md et réglages du client MCP (phase 14, point 12) : types, accès à l'API du Core, libellés.

import { ErreurApi, appeler, envoyer, unSeul } from "./api";
import { lireJeton } from "./auth";
import type { ReponseAction } from "./types";

export type CapaciteDangereuse = "shell" | "reseau" | "ecriture";
export type StatutSkill = "a_revoir" | "approuve" | "bloque";
export type ConfianceSkill = "non_fiable" | "instructions" | "capacites";

export interface DetectionSkill {
  capacite: CapaciteDangereuse;
  fichier: string;
  raison: string;
}

export interface FichierSkill {
  chemin: string;
  taille: number;
  script: boolean;
}

export interface Skill {
  id: string;
  nom: string;
  description: string;
  origine: "dossier" | "archive";
  source: string;
  confiance: ConfianceSkill;
  statut: StatutSkill;
  capacites: DetectionSkill[];
  capacites_acceptees: CapaciteDangereuse[];
  dangereuses: CapaciteDangereuse[];
  fichiers: FichierSkill[];
  empreinte: string;
  empreinte_approuvee: string | null;
  empreinte_actuelle?: string | null;
  raison_blocage: string | null;
  importe_par: string;
  approuve_par: string | null;
  cree_le: string;
  approuve_le: string | null;
  bloque_le: string | null;
}

export interface ReglagesMcp {
  max_outils: number;
  par_le_sens: boolean;
  relance_auto: boolean;
}

export interface SessionMcp {
  serveur: string;
  session: "ouverte" | "fermee" | "en_panne";
  demarrages: number;
  plantages: number;
  relances_auto: number;
  outils_connus: number | null;
  derniere_erreur: string | null;
  depuis_s: number | null;
}

export interface OutilChoisi {
  cle: string;
  genre: "mcp" | "skill" | "recherche";
  ligne: string;
}

export interface ChoixOutils {
  outils: OutilChoisi[];
  total: number;
  methode: "sens" | "mots" | null;
  max_outils: number;
}

export const STATUTS_SKILL: Record<StatutSkill, { texte: string; ton?: "ok" | "attention" | "risque" }> = {
  a_revoir: { texte: "À revoir", ton: "attention" },
  approuve: { texte: "Approuvé", ton: "ok" },
  bloque: { texte: "Bloqué", ton: "risque" },
};

export const CONFIANCES: Record<ConfianceSkill, string> = {
  non_fiable: "Non fiable : jamais revu, inutilisable",
  instructions: "Instructions seulement : aucune capacité dangereuse",
  capacites: "Capacités revues : cochées une à une",
};

export const SESSIONS: Record<SessionMcp["session"], { texte: string; ton?: "ok" | "attention" | "risque" }> = {
  ouverte: { texte: "Session ouverte", ton: "ok" },
  fermee: { texte: "Session fermée" },
  en_panne: { texte: "En panne", ton: "risque" },
};

/** Empreinte abrégée pour l'affichage (la complète reste en infobulle). */
export function empreinteCourte(empreinte: string | null | undefined): string {
  return empreinte ? `${empreinte.slice(0, 12)}…` : "—";
}

/** Le dossier copié a-t-il changé depuis l'approbation ? (vrai aussi si le dossier a disparu) */
export function empreinteChangee(s: Skill): boolean {
  if (s.statut === "bloque") return true;
  if (!s.empreinte_approuvee || s.empreinte_actuelle === undefined) return false;
  return s.empreinte_actuelle !== s.empreinte_approuvee;
}

/** Détections regroupées par capacité, dans un ordre stable. */
export function parCapacite(detections: DetectionSkill[]): [CapaciteDangereuse, DetectionSkill[]][] {
  const ordre: CapaciteDangereuse[] = ["shell", "reseau", "ecriture"];
  return ordre
    .map((c): [CapaciteDangereuse, DetectionSkill[]] => [c, detections.filter((d) => d.capacite === c)])
    .filter(([, liste]) => liste.length > 0);
}

export const listerSkills = () =>
  unSeul("skills", () => appeler<{ skills: Skill[]; capacites: Record<CapaciteDangereuse, string> }>("/v1/skills"));
export const lireSkill = (id: string) => appeler<Skill>(`/v1/skills/${encodeURIComponent(id)}`);
export const lireFichierSkill = (id: string, chemin: string) =>
  appeler<{ chemin: string; texte: string; tronque: boolean }>(
    `/v1/skills/${encodeURIComponent(id)}/fichier?chemin=${encodeURIComponent(chemin)}`,
  );
export const importerDossierSkill = (chemin: string) => envoyer<Skill>("/v1/skills/importer/dossier", { chemin });
export const approuverSkill = (id: string, capacites: CapaciteDangereuse[]) =>
  envoyer<ReponseAction>(`/v1/skills/${encodeURIComponent(id)}/approuver`, { capacites });
export const retirerSkill = (id: string) => envoyer<ReponseAction>(`/v1/skills/${encodeURIComponent(id)}/retirer`);
export const executerSkill = (id: string, script: string, args: string[]) =>
  envoyer<ReponseAction>(`/v1/skills/${encodeURIComponent(id)}/executer`, { script, arguments: args });

/** Archive .zip choisie par l'utilisateur : envoyée telle quelle (le Core vérifie chaque entrée). */
export async function importerArchiveSkill(fichier: File): Promise<Skill> {
  const jeton = lireJeton();
  let rep: Response;
  try {
    rep = await fetch(`/v1/skills/importer/archive?nom=${encodeURIComponent(fichier.name)}`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/zip",
        ...(jeton ? { Authorization: `Bearer ${jeton}` } : {}),
      },
      body: fichier,
    });
  } catch {
    throw new ErreurApi("Core injoignable.", 0);
  }
  if (!rep.ok) {
    let detail = "Archive refusée.";
    try {
      const corps = (await rep.json()) as { detail?: unknown };
      if (typeof corps.detail === "string") detail = corps.detail;
    } catch {
      /* corps non JSON */
    }
    throw new ErreurApi(detail, rep.status);
  }
  return (await rep.json()) as Skill;
}

export const lireReglagesMcp = () => appeler<{ reglages: ReglagesMcp; max_par_tour: number }>("/v1/mcp/reglages");
export const ecrireReglagesMcp = (changement: Partial<ReglagesMcp>) =>
  appeler<{ reglages: ReglagesMcp; max_par_tour: number }>("/v1/mcp/reglages", { methode: "PUT", corps: changement });
export const lireSessionsMcp = () => appeler<{ sessions: SessionMcp[] }>("/v1/mcp/sessions");
export const relancerServeurMcp = (serveur: string) =>
  envoyer<SessionMcp>(`/v1/mcp/serveurs/${encodeURIComponent(serveur)}/relancer`);
export const essayerChoixOutils = (q: string) =>
  appeler<ChoixOutils>(`/v1/mcp/outils/choix?q=${encodeURIComponent(q)}`);
