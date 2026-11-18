// Accès à l'API du Core. Chaque appel porte le jeton de l'appareil ; un 401 renvoie à l'écran de jumelage.
// Une seule requête par ressource à la fois (dédoublonnage) : le démarrage fait UN appel (/v1/etat), même
// quand React rejoue les effets en mode strict.

import { EVENEMENT_NON_AUTORISE, ecrireJeton, lireJeton } from "./auth";
import { LecteurSSE } from "./sse";
import type {
  Appareil,
  Connecteur,
  Materiel,
  DemandeAction,
  DemandeDialogue,
  DetailConversation,
  EntreeAudit,
  EtatAccueil,
  EtatTailscale,
  Jumelage,
  Verification,
  Etat,
  EvenementDialogue,
  ReponseAction,
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

async function appeler<T>(chemin: string, init: { methode?: string; corps?: unknown } = {}): Promise<T> {
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

const envoyer = <T>(chemin: string, corps: unknown = {}) => appeler<T>(chemin, { methode: "POST", corps });

export const lireEtat = () => unSeul("etat", () => appeler<Etat>("/v1/etat"));
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
export const lireMateriel = () => unSeul("materiel", () => appeler<Materiel>("/v1/materiel"));

// --- Premier lancement : assistant, diagnostic, téléphone ---
export const lireAccueil = () => unSeul("accueil", () => appeler<EtatAccueil>("/v1/accueil"));
export const terminerAccueil = () => envoyer<{ termine: boolean }>("/v1/accueil/terminer");
export const lireDiagnostic = () => unSeul("diagnostic", () => appeler<{ verifications: Verification[] }>("/v1/diagnostic"));
export const reparer = (id: string) => envoyer<{ verifications: Verification[] }>(`/v1/diagnostic/reparer/${encodeURIComponent(id)}`);
export const lireTailscale = () => appeler<EtatTailscale>("/v1/tailscale");

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
