// Accès à l'API du Core. Chaque appel porte le jeton de l'appareil ; un 401 renvoie à l'écran de jumelage.
// Une seule requête par ressource à la fois (dédoublonnage) : le démarrage fait UN appel (/v1/etat), même
// quand React rejoue les effets en mode strict.

import { EVENEMENT_NON_AUTORISE, ecrireJeton, lireJeton } from "./auth";
import type { ResumeCouts } from "./couts";
import { LecteurSSE } from "./sse";
import type {
  Activite,
  Chantier,
  EtapeChantier,
  StatutChantier,
  Appareil,
  Connecteur,
  Demande,
  Materiel,
  DemandeAction,
  DemandeDialogue,
  DetailConversation,
  EntreeAudit,
  EtatAccueil,
  EtatTailscale,
  Jumelage,
  Telechargement,
  Verification,
  Atelier,
  AttenteOutil,
  EvenementAtelier,
  EtatVeille,
  ModeleAtelier,
  ReglagesVeille,
  BlocMemoire,
  EtatMemoire,
  Mission,
  Recette,
  ServeurMcp,
  Etat,
  EvenementDialogue,
  ReponseAction,
  ResumeConversation,
  OrigineMemoire,
  Souvenir,
  CarteMatin,
  LieuTrouve,
  LocalisationMatin,
  ModeMatin,
  Prereglage,
  ReglagesMatin,
} from "./types";

export class ErreurApi extends Error {
  constructor(
    message: string,
    readonly statut: number,
  ) {
    super(message);
  }
}

const enCours = new Map<string, Promise<unknown>>();

/** Partage la même promesse entre appels simultanés pour une même clé. */
export function unSeul<T>(cle: string, appel: () => Promise<T>): Promise<T> {
  const existant = enCours.get(cle);
  if (existant) return existant as Promise<T>;
  const promesse = appel().finally(() => enCours.delete(cle));
  enCours.set(cle, promesse);
  return promesse;
}

const MESSAGES_STATUT: Record<number, string> = {
  401: "Cet appareil n'est pas (ou plus) autorisé.",
  403: "Refusé.",
  404: "Introuvable.",
  409: "Impossible pour l'instant.",
  422: "Demande invalide.",
  423: "Arrêt d'urgence actif : aucune action n'est acceptée.",
  429: "Trop de demandes : réessayez dans un instant.",
};
const INJOIGNABLE = "Core injoignable : vérifiez qu'il tourne (commande jarvis2 sur le PC).";

async function lireErreur(rep: Response): Promise<ErreurApi> {
  let detail = "";
  try {
    const corps = (await rep.json()) as { detail?: unknown };
    if (typeof corps.detail === "string") detail = corps.detail;
  } catch {
    /* corps non JSON */
  }
  if (rep.status === 401 && lireJeton()) {
    ecrireJeton(null);
    window.dispatchEvent(new Event(EVENEMENT_NON_AUTORISE));
  }
  const base = MESSAGES_STATUT[rep.status] ?? (rep.status >= 500 ? "Le Core a rencontré une erreur." : "Erreur.");
  return new ErreurApi(detail || base, rep.status);
}

function entetes(extra: Record<string, string> = {}): Record<string, string> {
  const jeton = lireJeton();
  return { Accept: "application/json", ...(jeton ? { Authorization: `Bearer ${jeton}` } : {}), ...extra };
}

export async function appeler<T>(chemin: string, init: { methode?: string; corps?: unknown } = {}): Promise<T> {
  let rep: Response;
  try {
    rep = await fetch(chemin, {
      method: init.methode ?? "GET",
      headers: entetes(init.corps !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(init.corps !== undefined ? { body: JSON.stringify(init.corps) } : {}),
    });
  } catch {
    throw new ErreurApi(INJOIGNABLE, 0);
  }
  if (!rep.ok) throw await lireErreur(rep);
  return (await rep.json()) as T;
}

export const envoyer = <T>(chemin: string, corps: unknown = {}) => appeler<T>(chemin, { methode: "POST", corps });

export const lireEtat = () => unSeul("etat", () => appeler<Etat>("/v1/etat"));
/** Le Core répond-il ? (route publique, légère : surveillance de la connexion) */
export const sonderCore = () => appeler<{ statut: string }>("/v1/sante");
/** Demandes en attente seules (léger : rafraîchit la file sans relire tout l'état) */
export const chercherConversations = (q: string, archivees = false) =>
  appeler<{ conversations: ResumeConversation[] }>(
    `/v1/conversations?${new URLSearchParams({ ...(q ? { q } : {}), ...(archivees ? { archivees: "true" } : {}) }).toString()}`,
  );
export const modifierConversation = (id: string, changement: { titre?: string; epinglee?: boolean; archivee?: false }) =>
  appeler<{ conversation: ResumeConversation }>(`/v1/conversations/${encodeURIComponent(id)}`, { methode: "PATCH", corps: changement });
export const resumerConversation = (id: string) =>
  envoyer<{ statut: string; prive?: boolean; raison?: string }>(`/v1/conversations/${encodeURIComponent(id)}/resumer`);
export const listerDemandes = () => appeler<{ demandes: Demande[] }>("/v1/demandes");
export const lireConversation = (id: string) =>
  unSeul(`conversation:${id}`, () => appeler<DetailConversation>(`/v1/conversations/${encodeURIComponent(id)}`));

// --- Jumelage et appareils ---
export const etatAuth = () => appeler<{ premier_possible: boolean }>("/v1/auth/etat");
export const premierAppareil = (nom: string) => envoyer<{ jeton: string; appareil: Appareil }>("/v1/appareils/premier", { nom });
export const echangerCode = (code: string, nom: string) =>
  envoyer<{ jeton: string; appareil: Appareil }>("/v1/jumelage/echanger", { code, nom });
export const creerJumelage = (type: string) =>
  envoyer<Jumelage>("/v1/jumelage", { type });
export const listerAppareils = () => appeler<{ appareils: (Appareil & { courant: boolean; cles: number })[] }>("/v1/appareils");
export const revoquerAppareil = (id: string) => envoyer<{ revoque: boolean; soi_meme: boolean }>(`/v1/appareils/${id}/revoquer`);

// --- Clés d'accès, actions, demandes ---
export const optionsCle = () => envoyer<Record<string, unknown>>("/v1/cles/enregistrement/options");
export const enregistrerCle = (credential: Record<string, unknown>, nom: string) =>
  envoyer<{ id: string }>("/v1/cles/enregistrement", { credential, nom });
export const demanderAction = (d: DemandeAction) => envoyer<ReponseAction>("/v1/actions", d);
export const optionsApprobation = (id: string) => envoyer<Record<string, unknown>>(`/v1/demandes/${id}/options`);
export const approuver = (id: string, credential?: Record<string, unknown>) =>
  envoyer<ReponseAction>(`/v1/demandes/${id}/approuver`, credential ? { credential } : {});
export const refuser = (id: string) => envoyer<{ statut: string }>(`/v1/demandes/${id}/refuser`);

// --- Arrêt d'urgence, audit ---
export const arreterUrgence = () => envoyer<{ reponses_interrompues: number }>("/v1/urgence/arreter");
export const leverUrgence = () => envoyer<ReponseAction>("/v1/urgence/lever");
export const lireAudit = (limite = 12) =>
  appeler<{ entrees: EntreeAudit[]; rompue_a: number | null }>(`/v1/audit?limite=${String(limite)}`);

// --- Connecteurs d'IA ---
export const listerConnecteurs = () => appeler<{ connecteurs: Connecteur[] }>("/v1/connecteurs");
export const testerConnecteur = (id: string) =>
  envoyer<{ disponible: boolean; detail: string; modeles: number }>(`/v1/connecteurs/${id}/tester`);
export const activerConnecteur = (id: string, accepte = false, version?: string) =>
  envoyer<{ ok: boolean }>(`/v1/connecteurs/${id}/activer`, { accepte, ...(version ? { version } : {}) });
export const desactiverConnecteur = (id: string) => envoyer<{ ok: boolean }>(`/v1/connecteurs/${id}/desactiver`);
export const inclureAuConseil = (id: string, inclus: boolean) =>
  envoyer<{ ok: boolean }>(`/v1/connecteurs/${id}/conseil`, { inclus });
export const enregistrerCleApi = (id: string, cle: string) =>
  appeler<{ ok: boolean }>(`/v1/connecteurs/${id}/cle`, { methode: "PUT", corps: { cle } });
export const supprimerCleApi = (id: string) => appeler<{ ok: boolean }>(`/v1/connecteurs/${id}/cle`, { methode: "DELETE" });
export const lireCouts = () => unSeul("couts", () => appeler<ResumeCouts>("/v1/couts"));
export const definirPlafond = (id: string, plafond_usd: number | null) =>
  appeler<{ ok: boolean }>(`/v1/connecteurs/${id}/plafond`, { methode: "PUT", corps: { plafond_usd } });
export const lireMateriel = () => unSeul("materiel", () => appeler<Materiel>("/v1/materiel"));

// --- Premier lancement : assistant, diagnostic, téléphone ---
export const lireAccueil = () => unSeul("accueil", () => appeler<EtatAccueil>("/v1/accueil"));
export const terminerAccueil = () => envoyer<{ termine: boolean }>("/v1/accueil/terminer");
export const lireDiagnostic = () => unSeul("diagnostic", () => appeler<{ verifications: Verification[] }>("/v1/diagnostic"));
export const reparer = (id: string) => envoyer<{ verifications: Verification[] }>(`/v1/diagnostic/reparer/${encodeURIComponent(id)}`);
export const lireTelechargements = () =>
  unSeul("telechargements", () => appeler<{ telechargements: Telechargement[] }>("/v1/telechargements"));
/** Le clic de l'utilisateur vaut accord : rien n'est jamais téléchargé sans lui. */
export const lancerTelechargement = (id: string) =>
  envoyer<{ telechargements: Telechargement[] }>(`/v1/telechargements/${encodeURIComponent(id)}`);
export const lireTailscale = () => appeler<EtatTailscale>("/v1/tailscale");
export const choisirPrereglages = (choix: Prereglage[]) =>
  envoyer<{ prereglages: Prereglage[]; recette: "creee" | "existante" | null }>("/v1/accueil/prereglages", { choix });

// --- Accueil du matin ---
export const lireMatin = (rejouer = false) => appeler<CarteMatin>(`/v1/matin${rejouer ? "?rejouer=true" : ""}`);
export const marquerMatinVu = () => envoyer<{ vu: string }>("/v1/matin/vu");
export const lireReglagesMatin = () => appeler<ReglagesMatin>("/v1/matin/reglages");
export const changerReglagesMatin = (r: { mode?: ModeMatin; localisation?: LocalisationMatin; effacer_localisation?: boolean }) =>
  appeler<ReglagesMatin>("/v1/matin/reglages", { methode: "PUT", corps: r });
export const chercherLieux = (q: string) => appeler<{ lieux: LieuTrouve[] }>(`/v1/matin/lieux?q=${encodeURIComponent(q)}`);

// --- Agents : recettes, missions, outils MCP ---
export const listerRecettes = () =>
  unSeul("recettes", () => appeler<{ dossier: string | null; recettes: Recette[]; erreurs: string[] }>("/v1/recettes"));
export const lancerRecette = (id: string) => envoyer<{ lancee: string }>(`/v1/recettes/${encodeURIComponent(id)}/lancer`);
export const listerMissions = () =>
  unSeul("missions", () => appeler<{ missions: Mission[]; recherche_web: boolean; scientifique: string[] }>("/v1/missions"));
/** `scientifique` : bases scientifiques en plus du web ; `domaine_id` : domaine de connaissance (revue = révision). */
export const lancerMission = (type: Mission["type"], objectif: string, options: { scientifique?: boolean; domaine_id?: string } = {}) =>
  envoyer<{ id: string }>("/v1/missions", { type, objectif, ...options });
export const listerOutilsMcp = () => unSeul("mcp", () => appeler<{ serveurs: ServeurMcp[] }>("/v1/mcp/outils"));
export const activerOutilMcp = (serveur: string, outil: string, actif: boolean) =>
  envoyer<{ actif: boolean }>(`/v1/mcp/outils/${encodeURIComponent(serveur)}/${encodeURIComponent(outil)}/actif`, { actif });

/** Conseil multi-IA : mêmes événements que le dialogue, plus un `avis` par expert. */
export function conseiller(
  demande: { question: string; conversation_id?: string },
  surEvenement: (ev: EvenementDialogue) => void,
  signal: AbortSignal,
): Promise<void> {
  return diffuser("/v1/conseil", demande, surEvenement, signal);
}

/** Envoie un message et transmet chaque événement du flux à `surEvenement`. */
export function dialoguer(
  demande: DemandeDialogue,
  surEvenement: (ev: EvenementDialogue) => void,
  signal: AbortSignal,
): Promise<void> {
  return diffuser("/v1/dialogue", demande, surEvenement, signal);
}

async function diffuser(
  chemin: string,
  demande: unknown,
  surEvenement: (ev: EvenementDialogue) => void,
  signal: AbortSignal,
): Promise<void> {
  let rep: Response;
  try {
    rep = await fetch(chemin, {
      method: "POST",
      headers: entetes({ "Content-Type": "application/json", Accept: "text/event-stream" }),
      body: JSON.stringify(demande),
      signal,
    });
  } catch (e) {
    if (signal.aborted) return;
    throw e instanceof Error && e.name === "AbortError" ? e : new ErreurApi(INJOIGNABLE, 0);
  }
  if (!rep.ok || !rep.body) throw await lireErreur(rep);
  const lecteur = rep.body.pipeThrough(new TextDecoderStream()).getReader();
  const sse = new LecteurSSE();
  try {
    for (;;) {
      const { value, done } = await lecteur.read();
      if (done) break;
      for (const ev of sse.pousser(value)) {
        surEvenement({ type: ev.evenement, donnees: JSON.parse(ev.donnees) as unknown } as EvenementDialogue);
      }
    }
  } catch (e) {
    if (signal.aborted) return;
    throw e;
  } finally {
    lecteur.releaseLock();
  }
}

// --- Mémoire v2 : blocs, bascule de modèle, tâches de nuit ---
export const lireEtatMemoire = () => unSeul("memoire", () => appeler<EtatMemoire>("/v1/memoire/etat"));
export const listerSouvenirs = (filtre: { origine?: string; avant?: string; q?: string }) =>
  appeler<{ souvenirs: Souvenir[]; suite: boolean }>(
    `/v1/memoire/souvenirs?${new URLSearchParams(Object.entries(filtre).filter((e): e is [string, string] => Boolean(e[1]))).toString()}`,
  );
export const listerOrigines = () => appeler<{ origines: OrigineMemoire[] }>("/v1/memoire/origines");
export const lireNouveautes = (depuis: string) =>
  appeler<{ nombre: number; souvenirs: Souvenir[] }>(`/v1/memoire/nouveautes?${new URLSearchParams({ depuis }).toString()}`);
export const listerBlocs = () => appeler<{ blocs: BlocMemoire[] }>("/v1/memoire/blocs");
export const ecrireBloc = (label: string, contenu: string, confidentialite?: BlocMemoire["confidentialite"]) =>
  appeler<BlocMemoire>(`/v1/memoire/blocs/${encodeURIComponent(label)}`, {
    methode: "PUT",
    corps: { contenu, ...(confidentialite ? { confidentialite } : {}) },
  });
export const noyauEnBlocs = () => envoyer<{ convertis: Record<string, number> }>("/v1/memoire/noyau-en-blocs");
export const lancerTacheMemoire = (id: string) => envoyer<{ lancee: string }>(`/v1/memoire/taches/${encodeURIComponent(id)}/lancer`);
// --- Ateliers Claude Code ---
export const listerAteliers = () =>
  unSeul("ateliers", () =>
    appeler<{ projets: { id: string; nom: string }[]; modeles: ModeleAtelier[]; ateliers: Atelier[]; attentes: AttenteOutil[] }>(
      "/v1/ateliers",
    ),
  );
export const creerAtelier = (projet: string, nom: string, modele: string | null = null) =>
  envoyer<Atelier>("/v1/ateliers", { projet, nom, modele });
export const pauseAtelier = (id: string) => envoyer<{ fait: boolean }>(`/v1/ateliers/${id}/pause`);
export const reprendreAtelier = (id: string) => envoyer<{ fait: boolean }>(`/v1/ateliers/${id}/reprendre`);
export const relancerAtelier = (id: string) => envoyer<{ fait: boolean }>(`/v1/ateliers/${id}/relancer`);
export const cloturerAtelier = (id: string, notes: string) => envoyer<Atelier>(`/v1/ateliers/${id}/cloturer`, { notes });
export const modeleAtelier = (id: string, modele: string | null) =>
  appeler<Atelier>(`/v1/ateliers/${id}/modele`, { methode: "PUT", corps: { modele } });
export const lireVeille = (apres = 0) => appeler<EtatVeille>(`/v1/veille-claude?apres=${String(apres)}`);
export const reglerVeille = (r: Partial<ReglagesVeille>) =>
  appeler<{ reglages: ReglagesVeille }>("/v1/veille-claude", { methode: "PUT", corps: r });
export const evenementsAtelier = (id: string, apres = 0) =>
  appeler<{ evenements: EvenementAtelier[]; attentes: AttenteOutil[] }>(`/v1/ateliers/${id}/evenements?apres=${String(apres)}`);
export const consigneAtelier = (id: string, consigne: string, reprendre = false) =>
  envoyer<{ lance: boolean }>(`/v1/ateliers/${id}/consigne`, { consigne, reprendre });
export const arreterAtelier = (id: string) => envoyer<{ arrete: boolean }>(`/v1/ateliers/${id}/arreter`);
export const abandonnerAtelier = (id: string) => envoyer<{ abandonne: boolean }>(`/v1/ateliers/${id}/abandonner`);
export const repondreAttente = (id: string, accorde: boolean) => envoyer<{ accorde: boolean }>(`/v1/ateliers/attentes/${id}`, { accorde });
// --- Voix et vision (phase 10) ---
/** Enregistrement → texte (transcription sur le PC) ; `eveil` : la phrase commence par « Jarvis ». */
export async function transcrireAudio(audio: Blob): Promise<{ texte: string; eveil: boolean; commande: string }> {
  let rep: Response;
  try {
    rep = await fetch("/v1/voix/transcrire", {
      method: "POST",
      headers: entetes({ "Content-Type": audio.type || "audio/webm" }),
      body: audio,
    });
  } catch {
    throw new ErreurApi(INJOIGNABLE, 0);
  }
  if (!rep.ok) throw await lireErreur(rep);
  return (await rep.json()) as { texte: string; eveil: boolean; commande: string };
}
export const decrireImage = (image: string, question?: string) =>
  envoyer<{ description: string; modele: string }>("/v1/vision/decrire", { image, ...(question ? { question } : {}) });
export const listerCreations = () =>
  appeler<{ creations: { id: string; titre: string; description: string; version_courante: number; maj_le: string }[] }>("/v1/creations");
export const creerCreation = (titre: string, demande: string) => envoyer<{ id: string; version: number }>("/v1/creations", { titre, demande });
export const modifierCreation = (id: string, demande: string) => envoyer<{ id: string; version: number }>(`/v1/creations/${id}/modifier`, { demande });
export const lienCreation = (id: string) => appeler<{ url: string; version: number }>(`/v1/creations/${id}/lien`);
// --- Chantiers et activité (phase 13, lot C) ---
export const lireActivite = () => unSeul("activite", () => appeler<Activite>("/v1/activite"));
export const listerChantiers = (statut: "ouverts" | "termines" | "abandonnes" | "tous" = "ouverts") =>
  appeler<{ chantiers: Chantier[] }>(`/v1/chantiers?statut=${statut}`);
export const creerChantier = (titre: string, etapes: EtapeChantier[] = []) =>
  envoyer<{ chantier: Chantier; cree: boolean }>("/v1/chantiers", { titre, etapes });
export const modifierChantier = (id: string, modif: { etapes?: EtapeChantier[]; progression?: number; statut?: StatutChantier; titre?: string }) =>
  appeler<Chantier>(`/v1/chantiers/${id}`, { methode: "PATCH", corps: modif });
export const terminerChantier = (id: string) => envoyer<{ chantier: Chantier; doublons_abandonnes: number }>(`/v1/chantiers/${id}/terminer`);
export const rouvrirChantier = (id: string) => envoyer<Chantier>(`/v1/chantiers/${id}/rouvrir`);
// --- Profil guidé (phase 13, lot D) ---
export interface ReponseProfil {
  question_id: string;
  texte: string;
  prive: boolean;
  commentaire: string | null;
  maj_le: string | null;
}
export interface SectionProfil {
  id: string;
  titre: string;
  description: string;
  prive: boolean;
  total: number;
  repondues: number;
}
export interface QuestionProfil {
  id: string;
  section: string;
  texte: string;
  aide: string;
  reponse: ReponseProfil | null;
}
export interface EtatProfil {
  sections: SectionProfil[];
  total: number;
  repondues: number;
  pourcentage: number;
  reprise: { section: string; question: string } | null;
  heritees: number;
}
export const lireProfil = () => appeler<EtatProfil>("/v1/profil");
export const lireSectionProfil = (id: string) =>
  appeler<Omit<SectionProfil, "total" | "repondues"> & { questions: QuestionProfil[] }>(`/v1/profil/sections/${encodeURIComponent(id)}`);
export const repondreProfil = (questionId: string, texte: string, prive: boolean) =>
  appeler<{ reponse: ReponseProfil; modifiee: boolean }>(`/v1/profil/reponses/${encodeURIComponent(questionId)}`, {
    methode: "PUT",
    corps: { texte, prive },
  });
export const retirerReponseProfil = (questionId: string) =>
  appeler<{ retiree: string }>(`/v1/profil/reponses/${encodeURIComponent(questionId)}`, { methode: "DELETE" });
