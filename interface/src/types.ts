// Types partagés avec l'API du Core (core/jarvis2/api.py).

import type { EtatPlafond } from "./couts";

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
  /** Sait lire les images jointes (selon le modèle pour Ollama et les compatibles OpenAI). */
  vision?: boolean;
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

export interface PalierModele {
  taille: string;
  modele: string;
  besoin_go: number;
  exemples?: string[];
}

export interface ConseilModele {
  usage: "conversation" | "vision" | "embeddings" | "transcription";
  titre: string;
  ou: string;
  budget_go: number;
  note: string;
  raison: string;
  conseille: PalierModele | null;
  maximum: PalierModele | null;
}

export interface Materiel {
  ram_go: number | null;
  vram_go: number | null;
  carte: string | null;
  type_carte: "nvidia" | "amd" | "apple" | "intel" | "autre" | "aucune";
  acceleration: "cuda" | "rocm" | "vulkan" | "metal" | "processeur";
  memoire_unifiee: boolean;
  resume: string;
  conseils: ConseilModele[];
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
  /** Serveur sans écran : capture, clics et contrôle de l'écran refusés par le Core. */
  sans_ecran?: boolean;
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
  // Transparence (lot N) : durée vue par le Core, estimation signalée, équivalent API de l'abonnement, plafond
  duree_ms?: number;
  cout_estime?: boolean;
  cout_inconnu?: boolean;
  cout_equivalent_api_usd?: number;
  plafond?: EtatPlafond;
  /** Images jointes à un message de l'utilisateur : seulement leur type et leur poids (le Core ne les garde pas). */
  images?: { type: string; octets: number }[];
  domaines?: { id: string; nom: string; niveau: number }[]; // domaines de connaissance évoqués
  /** Exécution inventée : phrases qui affirment une action qu'aucune action réelle du tour n'appuie. */
  invente?: AffirmationInventee[];
}

export interface AffirmationInventee {
  categorie: string;
  verbe: string;
  extrait: string;
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
  /** Images jointes, en data URL (5 au plus). */
  images?: string[];
}

export type EvenementDialogue =
  | { type: "debut"; donnees: { conversation_id: string; titre: string; moteur: string; modele: string | null; avertissement?: string } }
  | { type: "delta"; donnees: { texte: string } }
  | { type: "fin"; donnees: MetaMessage & { message_id: number; texte: string } }
  | { type: "erreur"; donnees: { message: string; conversation_id?: string } }
  | { type: "avis"; donnees: AvisExpert }
  | { type: "titre"; donnees: { conversation_id: string; titre: string } }
  | { type: "invente"; donnees: { message_id: number; affirmations: AffirmationInventee[] } };

// --- Premier lancement ---
export interface Verification {
  id: string;
  titre: string;
  statut: "ok" | "info" | "attention" | "erreur";
  detail: string;
  reparation: string | null;
  aide: string | null;
}

/** Gros téléchargement (modèle d'embeddings, Whisper) : lu sur ses marqueurs `.downloading` / `.ready` / `.failed`. */
export interface Telechargement {
  id: string;
  titre: string;
  nom: string;
  statut: "absent" | "en_cours" | "interrompu" | "pret" | "echoue";
  octets: number;
  total: number | null;
  raison: string | null;
  essai: number | null;
  maj: string | null;
  taille_estimee: number | null;
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
  prereglages?: Prereglage[];
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
  parametres?: { scientifique?: boolean; domaine_id?: string };
  statut: "en_file" | "en_cours" | "terminee" | "echec" | "annulee";
  progression: number;
  etapes: { nom: string; le: string }[];
  resultat: {
    rapport: string;
    sources: { titre: string; url: string }[];
    souvenir_id: string | null;
    moteur: string;
    // Révision d'un domaine de connaissance
    score?: number;
    lacunes?: string[];
    suggestions?: string[];
    domaine_id?: string;
  } | null;
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

// --- Ateliers Claude Code (phase 9) ---
export interface Atelier {
  id: string;
  projet: string;
  nom: string;
  branche: string;
  chemin: string;
  statut: "pret" | "en_cours" | "arrete" | "fusionne" | "abandonne" | "erreur";
  session: string | null;
  cree_le: string;
  actif: boolean;
}

export interface AttenteOutil {
  id: string;
  atelier: string;
  outil: string;
  entree: Record<string, unknown>;
  raison: string;
}

export interface EvenementAtelier {
  id: number;
  horodatage: string;
  type: string;
  contenu: Record<string, unknown>;
}

// --- Mémoire : souvenirs ---
export interface Souvenir {
  id: string;
  contenu: string;
  type: string;
  tags: string[];
  source: string | null;
  confidentialite: "normal" | "local_uniquement";
  origine: string;
  cree_le: string;
  maj_le: string;
  importance: number;
  acces: number;
}
export interface OrigineMemoire {
  id: string;
  nom: string;
  nombre: number;
}

// --- Chantiers et activité (phase 13, lot C) ---
export type StatutChantier = "propose" | "a_faire" | "en_cours" | "en_attente_utilisateur" | "bloque" | "termine" | "abandonne";

export interface EtapeChantier {
  titre: string;
  fait: boolean;
}

export interface Chantier {
  id: string;
  titre: string;
  description: string | null;
  categorie: string;
  statut: StatutChantier;
  progression: number;
  etape_courante: string | null;
  etapes: EtapeChantier[];
  responsable: string;
  action_utilisateur: string | null;
  priorite: number;
  origine: string;
  motif: string | null;
  cree_le: string;
  maj_le: string;
  termine_le: string | null;
}

export interface Activite {
  chantiers: Chantier[];
  missions: Pick<Mission, "id" | "type" | "objectif" | "statut" | "progression" | "cree_le" | "termine_le">[];
  ateliers: Pick<Atelier, "id" | "projet" | "nom" | "statut" | "actif">[];
  attentes_ateliers: number;
  creations: { id: string; titre: string; version_courante: number; maj_le: string }[];
  en_cours: number;
}
// --- Accueil du matin (lot L) ---
export type ModeMatin = "parle" | "texte" | "desactive";
export interface MeteoMatin {
  temperature: number | null;
  ciel: string | null;
  min: number | null;
  max: number | null;
  pluie: number | null;
  texte: string;
}
export interface RecetteMatin {
  id: string;
  nom: string;
  statut: "ok" | "erreur" | "en_cours" | "ignoree";
}
export type CarteMatin =
  | { afficher: false; raison: "urgence" | "desactive" | "deja_vu"; mode: ModeMatin }
  | {
      afficher: true;
      mode: ModeMatin;
      jour: string;
      lieu_connu: boolean;
      salutation: string;
      date: string;
      heure: string;
      meteo: MeteoMatin | null;
      recettes: RecetteMatin[];
      attention: string[];
      texte_parle: string;
    };
export interface LocalisationMatin {
  nom: string | null;
  source: "configuration" | "geocodage" | "appareil";
  latitude?: number;
  longitude?: number;
}
export interface ReglagesMatin {
  mode: ModeMatin;
  localisation: LocalisationMatin | null;
}
export interface LieuTrouve {
  nom: string;
  region: string | null;
  pays: string | null;
  latitude: number;
  longitude: number;
}
export type Prereglage = "conversation" | "code" | "recherche" | "point_du_matin";
