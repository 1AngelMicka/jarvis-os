// Types partagés avec l'API du Core (core/jarvis2/api.py).

import type { EtatPlafond } from "./couts";
import type { Avis, RouteMessage } from "./routage";
import type { Widget, WidgetEpingle } from "./widgets";

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
  /** Connecteur cloud qui lit les images : une image jointe n'y part qu'après un accord (mémorisé, révocable). */
  images_accord_requis?: boolean;
  images_accordees_le?: string | null;
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
  /** La case « Toujours autoriser » peut être proposée (action 🟡 autorisable). */
  toujours_possible?: boolean;
  /** « Plus tard » : heure du rappel poussé au téléphone, et nombre de reports (3 au plus). */
  rappel_le?: string | null;
  reports?: number;
  /** Empreinte SHA-256 du plan exact (renvoyée à l'approbation) et sa forme courte affichée (« 3fa2 9c01 »). */
  empreinte?: string | null;
  empreinte_courte?: string | null;
  /** L'action se défait une fois exécutée (« Annuler »). */
  reversible?: boolean;
}

/** Action réversible exécutée, encore annulable (pile d'annulation, 24 h). */
export interface EntreeAnnulation {
  id: string;
  action: string;
  resume: string;
  /** Comment elle s'annule (texte affiché). */
  comment: string;
  demande_id: string | null;
  acteur: string;
  statut: string;
  cree_le: string;
  expire_le: string;
}

export interface ResultatAnnulation {
  statut: "annulee";
  annulation: EntreeAnnulation;
  resultat: Record<string, unknown>;
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
  | { statut: "executee"; resultat: Record<string, unknown>; toujours_autorisee?: boolean }
  | { statut: "en_attente"; demande: Demande; regle?: string }
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
  /** Widgets épinglés dans le HUD (phase 14, D 16). */
  widgets?: WidgetEpingle[];
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
  /** Bloc d'actions de JARVIS, validé par le Core (lot F) ; `actions_ecartees` : raisons, jamais le contenu. */
  actions?: ActionPilotage[];
  actions_ecartees?: string[];
  /** Barrière d'injection (14 · B 6) : ce tour a lu du contenu non fiable ; ses actions qui agissent sont retenues. */
  barriere?: BilanBarriere;
  /** Identifiant du message (événement « fin ») : avis 👍 / 👎 sur la réponse. */
  message_id?: number;
  /** Routeur par type de tâche (14 · B 11) : type, raison, IA rétrogradées écartées ; avis de l'utilisateur. */
  route?: RouteMessage;
  retour?: Avis;
  /** Widgets générés (14 · D 16), fragments validés et réécrits par le Core ; `widgets_ecartes` : raisons. */
  widgets?: Widget[];
  widgets_ecartes?: string[];
}

export interface LectureNonFiable {
  source: string;
  libelle: string;
  detail: string;
}

export interface BilanBarriere {
  sources: LectureNonFiable[];
  /** Libellés des actions retenues pendant le tour. */
  bloquees: string[];
  message: string;
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
  | { type: "invente"; donnees: { message_id: number; affirmations: AffirmationInventee[] } }
  /** Image jointe pour un connecteur cloud sans accord : rien n'est parti, l'accord est demandé. */
  | { type: "accord_images"; donnees: { connecteur: string; nom: string; message: string } }
  /** Un outil long démarre (conseil, lecture d'images…) : phrase fixe du Core, affichée et dite si la voix est active. */
  | { type: "attente"; donnees: { outil: string; phrase: string } };

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

/** Missions « projet » : brainstorm → spec → plan à valider → exécution en graphe de dépendances. */
export type PhasePlan = "preparation" | "a_valider" | "execution" | "terminee" | "echec";
export type StatutEtape = "a_faire" | "attente_approbation" | "en_cours" | "faite" | "refusee" | "echec" | "sautee";

export interface EtapeGraphe {
  /** « E1 » */
  id: string;
  titre: string;
  /** "" si aucun */
  detail: string;
  /** Dépendances */
  apres: string[];
  /** Profondeur dans le graphe (0 = sans dépendance) : une colonne par niveau */
  niveau: number;
  statut: StatutEtape;
  /** Nom lisible du moteur choisi */
  moteur: string | null;
  /** Raison du choix de modèle (aussi dans l'audit) */
  raison: string | null;
  /** Demande d'approbation en cours ou passée */
  demande_id: string | null;
  /** Extrait (≤ 600 caractères) du résultat de l'étape */
  resultat: string | null;
  erreur: string | null;
  /** ISO 8601 */
  debut: string | null;
  fin: string | null;
}

export interface PlanMission {
  phase: PhasePlan;
  brainstorm: string;
  /** Markdown */
  spec: string;
  /** Markdown à cases */
  plan: string;
  /** Graphe lu depuis `plan` (+ état d'exécution) */
  etapes: EtapeGraphe[];
  /** Erreurs de lecture du plan (vide = exécutable) */
  erreurs: string[];
  /** Cases cochées */
  faites: number;
  /** Cases */
  total: number;
  /** Borne utilisée / réglée */
  parallele: number;
  /** Exécution repliée sur la conversation simple */
  repli: boolean;
}

export interface ReglagesMissions {
  /** Étapes d'une mission projet exécutées en même temps (1 à 8) */
  parallele: number;
}

export interface Mission {
  id: string;
  type: "recherche" | "brainstorm" | "revue" | "projet";
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
  /** Mission « projet » : spec, plan et graphe ; null pour les autres types */
  plan: PlanMission | null;
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
/** Niveau de confidentialité d'un souvenir ou d'un bloc (lot 14 · C 14). `prive` ⇔ `confidentialite = local_uniquement`. */
export type Niveau = "public" | "semi_prive" | "prive";
export type CompteursNiveaux = Record<Niveau, number>;

export interface BlocMemoire {
  label: string;
  content: string;
  version: number;
  char_limit: number;
  confidentialite: "normal" | "local_uniquement";
  /** Absent avec un Core antérieur au lot 14 · C 14 : déduit de `confidentialite`. */
  niveau?: Niveau;
  maj_le: string;
}

export interface EtatMemoire {
  souvenirs: { total: number; noyau: number; local_uniquement: number };
  modele_actif: string | null;
  bascule: { cible: string | null; faits: number; restants: number; erreur: string | null } | null;
  sans_vecteur: number;
  /** Compteurs par niveau (Core ≥ lot 14 · C 14). */
  niveaux?: CompteursNiveaux;
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
  /** Pause réelle (processus suspendu, autorisations retenues) */
  en_pause: boolean;
  /** Modèle de Claude Code choisi (null : réglage de Claude Code) */
  modele: string | null;
  notes: string | null;
  clos_le: string | null;
  /** Fichiers aussi modifiés par un autre atelier ouvert du même projet */
  conflits: { fichier: string; ateliers: { id: string; nom: string }[] }[];
  /** Bac à sable choisi (absent avec un Core antérieur au point 14 · B 9) */
  bac_a_sable?: ChoixBac;
  /** Bac que le prochain lancement utilisera (null : « aucun » ou refus) et raison du refus éventuel */
  bac?: { effectif: string | null; refus: string | null };
}

/** Choix du bac à sable d'un atelier : automatique, un bac précis, ou sans bac à sable (🟡, journalisé). */
export type ChoixBac = "auto" | "docker" | "podman" | "windows_sandbox" | "bubblewrap" | "sandbox_exec" | "aucun";

/** Un bac à sable détecté par le Core, disponible ou non. */
export interface BacASable {
  id: string;
  nom: string;
  disponible: boolean;
  /** Pourquoi il est (in)disponible */
  raison: string;
}

// --- Amélioration continue (lot O) ---
export type StatutAmelioration = "proposee" | "en_atelier" | "en_service" | "retiree" | "rejetee";

/** Un essai des tests du projet (dans l'atelier, ou sur le projet après un retour arrière). */
export interface EssaiTests {
  reussi: boolean;
  code: number | null;
  sortie: string;
  duree?: number;
  /** Arbre git testé (vide : le contenu a changé pendant les tests) */
  empreinte?: string;
  /** Les tests ont modifié le dossier de l'atelier : l'essai ne vaut pas pour le contenu vu */
  contenu_change?: boolean;
  le: string;
}

export interface Amelioration {
  id: string;
  titre: string;
  raison: string;
  description: string;
  origine: "jarvis" | "utilisateur";
  projet: string;
  statut: StatutAmelioration;
  atelier_id: string | null;
  tests: { atelier?: EssaiTests; retour?: EssaiTests };
  tests_en_cours: boolean;
  commit_avant: string | null;
  commit_service: string | null;
  commit_retour: string | null;
  cree_le: string;
  en_service_le: string | null;
  retiree_le: string | null;
}

export interface ProjetAmelioration {
  id: string;
  nom: string;
  /** Commande des tests (configuration locale) ; vide : aucun test configuré */
  tests: string;
}

export interface FichierApercu {
  chemin: string;
  etat: "ajoute" | "modifie" | "supprime";
  ajouts: number | null;
  retraits: number | null;
}

export interface ApercuAmelioration {
  empreinte: string;
  fichiers: FichierApercu[];
  diff: string;
  diff_tronque: boolean;
  base: string;
  branche: string;
  atelier_statut: Atelier["statut"];
  atelier_actif: boolean;
  commande_tests: string;
  tests: Partial<EssaiTests>;
  tests_a_jour: boolean;
}

export interface ModeleAtelier {
  id: string;
  nom: string;
}

// --- Veille des sessions Claude Code de l'utilisateur (lecture seule) ---
export type EtatSessionClaude = "travaille" | "vous_attend" | "permission" | "bloquee" | "inconnu";

export interface SessionClaude {
  id: string;
  nom: string;
  projet: string;
  dossier: string;
  etat: EtatSessionClaude;
  libelle: string;
  detail: string | null;
  depuis: string | null;
  origine: string | null;
}

export interface ReglagesVeille {
  actif: boolean;
  voix: boolean;
  notification: boolean;
}

export interface AlerteVeille {
  id: number;
  texte: string;
  etat: EtatSessionClaude;
  session: string;
  horodatage: string;
}

export interface EtatVeille {
  reglages: ReglagesVeille;
  disponible: boolean;
  sessions: SessionClaude[];
  alertes: AlerteVeille[];
  /** Dernier numéro d'alerte donné par le Core (repart de 0 à son redémarrage) */
  dernier: number;
  maj_le: string | null;
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
  /** Absent avec un Core antérieur au lot 14 · C 14 : déduit de `confidentialite`. */
  niveau?: Niveau;
  /** A une version antérieure (changement d'avis). */
  remplace?: boolean;
  origine: string;
  cree_le: string;
  maj_le: string;
  importance: number;
  acces: number;
}
/** Une version d'un souvenir : `valid_to` est la fin de validité (null pour la version actuelle). */
export interface VersionSouvenir extends Souvenir {
  valid_to: string | null;
  superseded_by: string | null;
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

// --- Où partent mes données ---
export type DestinationFlux = "pc" | "reseau" | "internet" | "variable";

/** Un flux de données de cette installation, généré par le Core depuis la configuration réelle. */
export interface FluxDonnee {
  id: string;
  categorie: string;
  fonction: string;
  service: string;
  destination: DestinationFlux;
  local: boolean;
  etat: "actif" | "sur_accord" | "inactif";
  envoie: string[];
  jamais: string[];
  detail: string | null;
  desactiver: { texte: string; reglage: string | null; vue: string | null };
  images: { accorde: boolean; accorde_le: string | null } | null;
}

export interface CarteFlux {
  genere_le: string;
  resume: { flux: number; locaux: number; sortants_actifs: number; internet_actifs: number; connecteurs_inactifs: number };
  flux: FluxDonnee[];
  /** Ce que chaque niveau de mémoire laisse partir (Core ≥ lot 14 · C 14 ; absent avant). */
  memoire?: MemoireFlux;
}

export interface RegleNiveau {
  niveau: Niveau;
  libelle: string;
  vers_cloud: string;
}

export interface MemoireFlux {
  niveaux: CompteursNiveaux;
  regles: RegleNiveau[];
  porte_rappel: string;
}

// --- Lot F : pilotage de l'interface, règles de protection, commandes rapides, « toujours autoriser » ---

export type NiveauAction = "vert" | "jaune" | "rouge";
export type TypeImmediat = "naviguer" | "ouvrir" | "rechercher_memoire" | "regler";
export type TypeProposition = "proposer_mission" | "proposer_atelier" | "proposer_amelioration" | "demander_action" | "ajouter_regle";

/** Action validée par le Core : `immediate` (appliquée seule en mode « oui »), `proposition` (toujours un clic). */
export interface ActionPilotage {
  type: TypeImmediat | TypeProposition;
  genre: "immediate" | "proposition";
  niveau: NiveauAction;
  libelle: string;
  parametres: Record<string, unknown>;
  /** Retenue par la barrière d'injection (raison) : jamais appliquée seule, l'utilisateur la lance lui-même. */
  bloquee?: string;
}

export type ModePilotage = "oui" | "demander" | "non";

export interface InfoPilotage {
  mode: ModePilotage;
  vues: Record<string, string>;
  actions_interface: string[];
  actions_declarees: { nom: string; niveau: NiveauAction; description: string; toujours_possible: boolean }[];
}

export interface RegleProtection {
  id: string;
  genre: "interdire" | "demander";
  motif: string;
  libelle: string;
  origine: "utilisateur" | "jarvis";
  cree_par: string;
  cree_le: string;
}

export interface AutorisationPermanente {
  action: string;
  description: string;
  cree_le: string;
  utilisations: number;
  derniere_utilisation: string | null;
}

export interface CommandeRapide {
  id: string;
  motif: string;
  cible: "interface" | "core";
  action: string;
  parametres: Record<string, unknown>;
  priorite: number;
  phrase_test: string;
  actif: boolean;
  utilisations: number;
  derniere_utilisation: string | null;
  niveau: NiveauAction | "inconnu";
}

export type CommandeRapideEdition = Pick<CommandeRapide, "motif" | "cible" | "action" | "parametres" | "priorite" | "phrase_test" | "actif">;

export interface ConflitCommande {
  id: string;
  motif: string;
  priorite: number;
}

export interface ResultatCommande {
  trouvee: boolean;
  commande?: CommandeRapide;
  action?: ActionPilotage | { type: string; niveau: NiveauAction; libelle: string; parametres: Record<string, unknown> };
  resultat?: ReponseAction;
  erreur?: string;
}

// --- Connecteurs maison facultatifs (Hue, OBS) ---
export interface OutilMaison {
  nom: string;
  connecteur: "hue" | "obs" | "home_assistant";
  niveau: "vert" | "jaune" | "rouge";
  description: string;
  parametres: Record<string, string>;
}

export interface ConnecteurMaison {
  id: "hue" | "obs";
  nom: string;
  description: string;
  actif: boolean;
  adresse: string | null;
  secret_enregistre: boolean;
  outils: OutilMaison[];
}

// --- Home Assistant, Wyoming, satellites, pièces, profils (lot 14 · D 18) ---
export interface CarteHomeAssistant {
  id: "home_assistant";
  nom: string;
  description: string;
  actif: boolean;
  adresse: string | null;
  mode: "mcp" | "rest";
  oauth: boolean;
  jeton_rest: boolean;
  code_alarme: boolean;
  pret: boolean;
  outils: OutilMaison[];
}

export interface EtatWyoming {
  actif: boolean;
  hote: string;
  port: number;
  clients: string[];
  en_ecoute: boolean;
  port_reel: number | null;
  satellites_connectes: string[];
}

export interface Satellite {
  id: string;
  nom: string;
  piece: string;
  volume_max: number;
  actif: boolean;
  cree_le: string | null;
  vu_le: string | null;
  personne: string | null;
}

export interface PieceMaison {
  piece: string;
  satellites: number;
  vu_le: string | null;
  personne: string | null;
  occupee: boolean;
}

export interface ProfilVoix {
  id: string;
  nom: string;
  volume_max: number;
  cree_le: string | null;
  empreintes: number;
}

// --- Bureau et téléphone (lot M) ---------------------------------------------------------------------------

export interface LienVerifie {
  action: "ouvrir" | "conversation" | "nouvelle" | "ecouter" | "ecran" | "dire" | "decision" | "gadget";
  parametres: Record<string, string>;
  libelle: string;
  /** Le lien porte un texte venu de l'extérieur : à relire, jamais à suivre comme une consigne. */
  non_fiable: boolean;
}

export interface EtatPush {
  disponible: boolean;
  cle_publique: string | null;
  abonne: boolean;
}

export interface Partage {
  id: string;
  titre: string;
  texte: string;
  url: string;
  recu_le: string;
  traite: boolean;
  appareil: string | null;
  non_fiable: true;
}

export interface FichierEnvoyable {
  nom: string;
  taille: number;
  modifie_le: string;
}

export interface DemandeDetaillee {
  demande: Demande;
  description: string;
  cles_acces: number;
}

// --- Ressources et contrôle du PC (lot J) ---
export interface MesurePC {
  horodatage: number;
  cpu: number | null;
  ram: number | null;
  ram_utilisee_go: number | null;
  ram_totale_go: number | null;
  gpu: number | null;
  vram: number | null;
  vram_utilisee_go: number | null;
  vram_totale_go: number | null;
}

export interface PointCourbePC {
  t: number;
  cpu: number | null;
  ram: number | null;
  gpu: number | null;
  vram: number | null;
}

export interface ModeleCharge {
  nom: string;
  taille_go: number;
  vram_go: number;
  expire_le: string | null;
}

export interface EtatOllama {
  installe: boolean;
  joignable: boolean;
  lance_par_jarvis: boolean;
  modeles_charges: ModeleCharge[];
  inactivite_min: number;
  arret_dans_s: number | null;
}

export type ReglageJeu = "automatique" | "force" | "jamais";

export interface EtatJeu {
  reglage: ReglageJeu;
  en_veille: boolean;
  jeu: string | null;
  detection: boolean;
}

export interface RessourcesPC {
  actuel: MesurePC;
  alertes: string[];
  seuil_alerte: number;
  courbe: PointCourbePC[];
  ollama: EtatOllama;
  jeu: EtatJeu;
  controle: boolean;
}

export interface FenetrePC {
  id: number;
  titre: string;
  programme: string;
  active: boolean;
  reduite: boolean;
}

export interface EtatControlePC {
  volume: { niveau: number; muet: boolean } | null;
  luminosite: number | null;
  media: { application: string | null; titre: string | null; artiste: string | null; statut: string | null } | null;
  fenetres: FenetrePC[] | null;
  plan_alimentation: { actif: string; nom: string | null } | null;
  notifications: boolean | null;
  theme_sombre: boolean | null;
  mode: string;
  modes: { id: string; titre: string; description: string }[];
  extinction_dans_s: number | null;
}

/** Indicateur « nouvelle version » (`GET /v1/mises-a-jour`) : vérifié au plus une fois par jour, si actif. */
export interface EtatMisesAJour {
  active: boolean;
  installee: string;
  derniere: string | null;
  nouvelle: boolean;
  /** Notes de version en texte brut (jamais interprétées) */
  notes: string | null;
  url: string | null;
  publiee_le: string | null;
  verifie_le: string | null;
  erreur: string | null;
  commande: string;
}
