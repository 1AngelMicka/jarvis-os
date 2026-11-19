// Éveil « Dis Jarvis » (lot K1) : chaque phrase captée part au Core avec ses horodatages ; le Core décide (mot
// d'éveil en deux étages, relance sans mot d'éveil, « stop », « silence ») et tient l'état actif / veille. L'interface
// applique la décision et dit au Core quand la voix de JARVIS s'est tue (début de la fenêtre de relance).

import { appeler, envoyerAudio } from "./api";

export type ActionEveil = "ignorer" | "envoyer" | "armer" | "stop" | "silence" | "veille";
export type PhaseEveil = "veille" | "commande" | "reponse" | "relance";

export interface EtatConversation {
  etat: "veille" | "actif";
  phase: PhaseEveil;
  jusqu_a: number | null;
}

export interface DecisionEveil extends EtatConversation {
  action: ActionEveil;
  raison: string;
  texte: string;
  commande: string;
  etage: number | null;
  score: number | null;
  juge: boolean | null;
}

export interface ReglagesEveil {
  ambiance: boolean;
  openwakeword: boolean;
  relance_s: number;
}

export interface EtatEveil {
  reglages: ReglagesEveil;
  conversation: EtatConversation;
  acoustique: { active: boolean; paquet: boolean; modele: boolean; utilisee: boolean };
  telechargement: { statut: string; octets: number; total: number | null; raison: string | null };
  ambiance: { phrases: number; derniere: { statut: string; ajoutes?: number; raison?: string; le: string } | null };
}

/** Horodatage sur l'horloge de l'appareil (ms depuis 1970) d'un instant mesuré par `performance.now()`. */
export function horodatage(instant: number): number {
  return Math.round(performance.timeOrigin + instant);
}

export const ecouterPhrase = (audio: Blob, debut: number, fin: number) =>
  envoyerAudio<DecisionEveil>("/v1/voix/ecoute", audio, { "X-Debut": String(debut), "X-Fin": String(fin) });
export const signalerEveil = (evenement: "parole_fin" | "reponse_debut" | "annuler", t = Date.now()) =>
  appeler<EtatConversation>("/v1/voix/ecoute/evenement", { methode: "POST", corps: { evenement, t } });
export const lireEveil = () => appeler<EtatEveil>("/v1/voix/eveil");
export const reglerEveil = (r: Partial<ReglagesEveil>) => appeler<EtatEveil>("/v1/voix/eveil", { methode: "PUT", corps: r });
export const telechargerModeleEveil = () => appeler<EtatEveil>("/v1/voix/eveil/modele", { methode: "POST" });
export const oublierAmbiance = () => appeler<EtatEveil>("/v1/voix/ambiance/oublier", { methode: "POST" });

/** Ce que l'interface sait faire d'une décision du Core. */
export interface Effets {
  envoyer: (texte: string) => void;
  arreter: () => void; // « stop » : la réponse en cours et la lecture à voix haute
  couperVoix: () => void; // « silence »
  notifier: (message: string) => void;
}

/** Applique une décision ; rend vrai si une réponse de JARVIS commence (à suivre jusqu'à la fin de sa voix). */
export function appliquerDecision(d: DecisionEveil, effets: Effets): boolean {
  switch (d.action) {
    case "envoyer":
      if (!d.commande) return false;
      effets.envoyer(d.commande);
      return true;
    case "armer":
      effets.notifier("Je vous écoute.");
      return false;
    case "stop":
      effets.arreter();
      return false;
    case "silence":
      effets.arreter();
      effets.couperVoix();
      effets.notifier("Silence : voix coupée, écoute en veille.");
      return false;
    case "veille":
      effets.notifier("En veille : dites « Jarvis » pour reprendre.");
      return false;
    default:
      return false;
  }
}

/** Attend que la réponse soit finie ET que JARVIS se soit tu, puis le dit au Core (début de la relance). */
export function suivreFinDeReponse(occupe: () => boolean, surFin: (t: number) => void, periode = 150): () => void {
  let vu = false; // la réponse doit d'abord avoir commencé (le flux part après un aller-retour)
  const debut = performance.now();
  const minuterie = window.setInterval(() => {
    const maintenant = performance.now();
    if (occupe()) {
      vu = true;
      return;
    }
    if (vu || maintenant - debut > 3000) {
      window.clearInterval(minuterie);
      surFin(Date.now());
    }
  }, periode);
  return () => {
    window.clearInterval(minuterie);
  };
}

// --- « Dis Jarvis » en fond (préférence de l'appareil) ----------------------------------------------------------

const CLE_FOND = "jarvis2.eveil.fond";
/** Événement de fenêtre : l'écoute en fond a été allumée ou coupée (Réglages) ; détail : booléen. */
export const EVENEMENT_ECOUTE_FOND = "jarvis2:eveil-fond";

export function lireEcouteFond(): boolean {
  try {
    return localStorage.getItem(CLE_FOND) === "oui";
  } catch {
    return false;
  }
}

export function reglerEcouteFond(actif: boolean): void {
  try {
    localStorage.setItem(CLE_FOND, actif ? "oui" : "non");
  } catch {
    /* stockage indisponible : réglage gardé pour cette page seulement */
  }
  window.dispatchEvent(new CustomEvent(EVENEMENT_ECOUTE_FOND, { detail: actif }));
}
