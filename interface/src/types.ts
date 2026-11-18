// Types partagés avec l'API du Core (core/jarvis2/api.py).

export interface InfoModele {
  id: string;
  nom: string;
  defaut: boolean;
}

export interface InfoMoteur {
  id: string;
  nom: string;
  externe: boolean;
  disponible: boolean;
  detail: string;
  modeles: InfoModele[];
  efforts: string[];
  effort_defaut: string | null;
  famille?: "cli" | "api" | "local";
  risque?: boolean;
}

/** Carte de la page Connecteurs. */
export interface Connecteur extends InfoMoteur {
  famille: "cli" | "api" | "local";
  statut: "disponible" | "non_connecte" | "non_installe" | "desactive";
  actif: boolean;
  risque: boolean;
  installe: boolean;
  connecte: boolean | null;
  dans_conseil: boolean;
  installation_url: string | null;
  conditions_url: string | null;
  cle: { requise: boolean; enregistree: boolean; apercu: string | null; url: string | null } | null;
  conditions: { version: string; texte: string; url: string } | null;
  conditions_acceptees: boolean;
}

export interface AvisExpert {
  connecteur: string;
  nom: string;
  modele: string | null;
  texte: string;
  erreur: string | null;
  duree_ms: number;
}

export interface Materiel {
  ram_go: number | null;
  vram_go: number | null;
  carte: string | null;
  recommandations: { taille: string; ou: string; exemples: string[]; raison: string }[];
}

export interface ResumeConversation {
  id: string;
  titre: string;
  titre_source: string;
  epinglee: boolean;
  archivee: boolean;
  cree_le: string;
  maj_le: string;
  nb_messages: number;
  connecteur?: string | null;
  modele?: string | null;
}

export interface Appareil {
  id: string;
  nom: string;
  type: string;
  cree_le: string;
  dernier_acces: string | null;
  revoque: boolean;
}

export interface Demande {
  id: string;
  action: string;
  niveau: "jaune" | "rouge";
  resume: string;
  parametres: Record<string, unknown>;
  statut: string;
  demandeur: string;
  cree_le: string;
  expire_le: string;
  resultat: Record<string, unknown> | null;
}

export interface EtatUrgence {
  actif: boolean;
  par: string | null;
  depuis: string | null;
}

export interface EntreeAudit {
  id: number;
  horodatage: string;
  acteur: string;
  action: string;
  niveau: "vert" | "jaune" | "rouge";
  cible: string | null;
  resultat: string;
}

export interface DemandeAction {
  action: string;
  parametres: Record<string, unknown>;
}

export type ReponseAction =
  | { statut: "executee"; resultat: Record<string, unknown> }
  | { statut: "en_attente"; demande: Demande }
  | { statut: "refusee" };

export interface Etat {
  version: string;
  moteur_defaut: string;
  moteurs: InfoMoteur[];
  conversations: ResumeConversation[];
  memoire: { total: number; noyau: number; local_uniquement: number };
  appareil: Appareil;
  urgence: EtatUrgence;
  demandes: Demande[];
  cles_acces: number;
}

export interface MetaMessage {
  moteur?: string;
  modele?: string | null;
  effort?: string;
  cout_usd?: number;
  jetons_entree?: number | null;
  jetons_sortie?: number | null;
  source_auth?: string;
  interrompu?: boolean;
  erreur?: string;
  souvenirs?: string[];
  memoire_consultee?: boolean;
  masques?: Record<string, number>;
  prive?: boolean;
  conseil?: AvisExpert[];
}

export interface MessageStocke {
  id: number;
  role: "utilisateur" | "jarvis";
  contenu: string;
  horodatage: string;
  meta: MetaMessage;
}

export interface DetailConversation {
  conversation: ResumeConversation;
  messages: MessageStocke[];
}

export interface DemandeDialogue {
  message: string;
  conversation_id?: string;
  moteur?: string;
  modele?: string;
  effort?: string;
}

export type EvenementDialogue =
  | { type: "debut"; donnees: { conversation_id: string; titre: string; moteur: string; modele: string | null } }
  | { type: "delta"; donnees: { texte: string } }
  | { type: "fin"; donnees: MetaMessage & { message_id: number; texte: string } }
  | { type: "erreur"; donnees: { message: string; conversation_id?: string } }
  | { type: "avis"; donnees: AvisExpert };

// --- Premier lancement ---
export interface Verification {
  id: string;
  titre: string;
  statut: "ok" | "info" | "attention" | "erreur";
  detail: string;
  reparation: string | null;
  aide: string | null;
}

export interface EtatTailscale {
  installe: boolean;
  connecte: boolean;
  nom: string | null;
  serve_actif: boolean;
  adresse: string | null;
  commande: string;
  aide: string;
}

export interface EtatAccueil {
  termine: boolean;
  stockage: "sqlite" | "postgres";
  tailscale: EtatTailscale | null;
}

export interface Jumelage {
  url: string;
  qr: string;
  expire_le: string;
  local: boolean;
  tailscale: boolean;
}

// --- Agents (phase 7) ---
export interface ExecutionRecette {
  id: number;
  declencheur: "planification" | "manuel";
  debut: string;
  fin: string | null;
  statut: "en_cours" | "ok" | "erreur" | "ignoree";
  conversation_id: string | null;
  resultat: string | null;
  erreur: string | null;
}

export interface Recette {
  id: string;
  nom: string;
  planification: string;
  consigne: string;
  connecteur: string | null;
  livraison: "conversation" | "memoire";
  active: boolean;
  prochaine: string | null;
  en_cours: boolean;
  derniere: ExecutionRecette | null;
}

export interface Mission {
  id: string;
  type: "recherche" | "brainstorm" | "revue";
  objectif: string;
  statut: "en_file" | "en_cours" | "terminee" | "echec" | "annulee";
  progression: number;
  etapes: { nom: string; le: string }[];
  resultat: { rapport: string; sources: { titre: string; url: string }[]; souvenir_id: string | null; moteur: string } | null;
  erreur: string | null;
  cree_le: string;
  termine_le: string | null;
}

export interface OutilMcp {
  nom: string;
  description: string;
  schema: Record<string, unknown>;
  actif: boolean;
}

export interface ServeurMcp {
  serveur: string;
  disponible: boolean;
  erreur?: string;
  outils: OutilMcp[];
}

// --- Mémoire v2 (phase 8) ---
export interface BlocMemoire {
  label: string;
  content: string;
  version: number;
  char_limit: number;
  confidentialite: "normal" | "local_uniquement";
  maj_le: string;
}

export interface EtatMemoire {
  souvenirs: { total: number; noyau: number; local_uniquement: number };
  modele_actif: string | null;
  bascule: { cible: string | null; faits: number; restants: number; erreur: string | null } | null;
  sans_vecteur: number;
  taches: { id: string; nom: string; planification: string; derniere: { debut: string; statut: string; resultat: string | null; erreur: string | null } | null }[];
}
