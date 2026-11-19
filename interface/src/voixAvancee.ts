// Voix, lot K3 : état de la transcription, reconnaissance du propriétaire, fin de tour, dictée globale.
// Ici seulement les appels au Core et la logique sans affichage (testée) ; l'écran est dans ReglagesVoix.tsx.

import { appeler, envoyer, envoyerAudio } from "./api";
import type { Telechargement } from "./types";

export interface AppareilVoix {
  famille: "cuda" | "rocm" | "processeur";
  libelle: string;
  type_calcul: string;
  raison: string | null;
}

export interface EtatTranscription {
  modele: string;
  conseille: boolean;
  telecharge: boolean;
  charge: boolean;
  prechauffe: boolean;
  chargement_ms: number | null;
  appareil: AppareilVoix;
  disjoncteur: { ouvert: boolean; reste_s: number | null; echecs: number; derniere_erreur: string | null };
  fin_de_tour: { modele: string | null };
}

export interface FinDeTour {
  fini: boolean;
  probabilite: number;
  raison: string;
  juge: string | null;
}

export interface Anticipation {
  texte: string;
  fin_de_tour: FinDeTour;
}

export interface Empreinte {
  id: string;
  cree_le: string;
  parole_s: number;
}

export interface EtatProprietaire {
  actif: boolean;
  seuil: number;
  disponible: boolean;
  raison: string | null;
  ferme: boolean;
  empreintes: Empreinte[];
  empreintes_max: number;
  modele: Telechargement;
}

export type StyleDictee = "phrase" | "message" | "code" | "brut";

export interface Correction {
  de: string;
  vers: string;
}

export interface EtatDictee {
  actif: boolean;
  corrections: Correction[];
  styles: Record<string, StyleDictee>;
  styles_possibles: StyleDictee[];
  collage_possible: boolean;
}

export interface ResultatDictee {
  texte: string;
  style: StyleDictee;
  programme: string | null;
  colle: boolean;
}

export const lireTranscription = () => appeler<EtatTranscription>("/v1/voix/transcription");
export const prechaufferVoix = () => envoyer<{ prechauffe: boolean; duree_ms: number; raison?: string }>("/v1/voix/prechauffer");
export const anticiperPhrase = (audio: Blob) => envoyerAudio<Anticipation>("/v1/voix/anticipee", audio);

export const lireProprietaire = () => appeler<EtatProprietaire>("/v1/voix/proprietaire");
export const reglerProprietaire = (r: { actif?: boolean; seuil?: number }) =>
  appeler<EtatProprietaire>("/v1/voix/proprietaire", { methode: "PUT", corps: r });
export const ajouterEmpreinte = (audio: Blob) =>
  envoyerAudio<EtatProprietaire & { empreinte: Empreinte }>("/v1/voix/proprietaire/empreintes", audio);
export const retirerEmpreinte = (id: string) =>
  appeler<EtatProprietaire>(`/v1/voix/proprietaire/empreintes/${encodeURIComponent(id)}`, { methode: "DELETE" });

export const lireDictee = () => appeler<EtatDictee>("/v1/dictee");
export const reglerDictee = (r: { actif?: boolean; corrections?: Correction[]; styles?: Record<string, StyleDictee> }) =>
  appeler<EtatDictee>("/v1/dictee", { methode: "PUT", corps: r });
export const dicter = (audio: Blob, coller: boolean) =>
  envoyerAudio<ResultatDictee>(`/v1/dictee${coller ? "?coller=1" : ""}`, audio);

/** Mains libres : Whisper préchauffé, phrase anticipée dès le début du silence, coupure si la fin de tour est sûre.
 *  Une erreur (modèle absent…) retire l'anticipation : l'écoute garde son fonctionnement simple. */
export function brancherAnticipation(ecoute: { anticiper: ((audio: Blob) => Promise<boolean>) | null }): void {
  prechaufferVoix().catch(() => {
    /* modèle absent : la transcription le dira */
  });
  ecoute.anticiper = (audio) =>
    anticiperPhrase(audio)
      .then((r) => r.fin_de_tour.fini && r.fin_de_tour.probabilite >= 0.8)
      .catch(() => {
        ecoute.anticiper = null;
        return false;
      });
}

export const NOMS_STYLES: Record<StyleDictee, string> = {
  phrase: "Phrase (majuscule, point)",
  message: "Message (sans point final)",
  code: "Code et terminal (tel quel)",
  brut: "Brut",
};

/** « de → vers » une par ligne (ou « de = vers ») → corrections ; lignes vides ou sans flèche ignorées. */
export function lireCorrections(texte: string): Correction[] {
  const vues = new Set<string>();
  const sortie: Correction[] = [];
  for (const ligne of texte.split("\n")) {
    const morceaux = ligne.split(/\s*(?:→|->|=>|=)\s*/u);
    if (morceaux.length < 2) continue;
    const de = (morceaux[0] ?? "").trim().replace(/\s+/g, " ").slice(0, 80);
    const vers = morceaux.slice(1).join(" ").trim().slice(0, 200);
    const cle = de.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
    if (!de || vues.has(cle)) continue;
    vues.add(cle);
    sortie.push({ de, vers });
  }
  return sortie.slice(0, 200);
}

export function ecrireCorrections(corrections: readonly Correction[]): string {
  return corrections.map((c) => `${c.de} → ${c.vers}`).join("\n");
}

/** Raccourci maintenu de l'application de bureau (Ctrl+Alt+D, sinon Ctrl+Maj+Alt+D si déjà pris). */
export const RACCOURCI_DICTEE = "Ctrl+Alt+D";
export const RACCOURCI_DICTEE_SECOURS = "Ctrl+Maj+Alt+D";

/** Événement émis par l'application de bureau : détail « debut » (raccourci enfoncé) ou « fin » (relâché). */
export const EVENEMENT_DICTEE = "jarvis2:dictee";

export type EtatDicteeEnCours =
  | { etape: "repos" }
  | { etape: "ecoute" }
  | { etape: "transcription" }
  | { etape: "fini"; resultat: ResultatDictee }
  | { etape: "erreur"; message: string };

export interface MicroDictee {
  demarrer(): Promise<void>;
  arreter(): Promise<Blob>;
}

/** Dictée maintenue : `debut` ouvre le micro, `fin` envoie l'enregistrement (trop court : ignoré). */
export class Dictee {
  private micro: MicroDictee | null = null;
  private debut = 0;
  private ouverture: Promise<void> | null = null;

  constructor(
    private readonly fabrique: () => MicroDictee,
    private readonly envoi: (audio: Blob) => Promise<ResultatDictee>,
    private readonly surEtat: (e: EtatDicteeEnCours) => void,
    private readonly horloge: () => number = () => performance.now(),
    readonly dureeMin = 350,
  ) {}

  get enCours(): boolean {
    return this.micro !== null;
  }

  commencer(): void {
    if (this.micro) return; // répétition de la touche tenue
    const micro = this.fabrique();
    this.micro = micro;
    this.debut = this.horloge();
    this.surEtat({ etape: "ecoute" });
    this.ouverture = micro.demarrer().catch(() => {
      this.micro = null;
      this.surEtat({ etape: "erreur", message: "Micro refusé ou indisponible." });
    });
  }

  async finir(): Promise<void> {
    const micro = this.micro;
    if (!micro) return;
    await this.ouverture;
    if (this.micro !== micro) return; // ouverture du micro ratée
    this.micro = null;
    const audio = await micro.arreter();
    if (this.horloge() - this.debut < this.dureeMin || audio.size === 0) {
      this.surEtat({ etape: "repos" });
      return;
    }
    this.surEtat({ etape: "transcription" });
    try {
      this.surEtat({ etape: "fini", resultat: await this.envoi(audio) });
    } catch (e: unknown) {
      this.surEtat({ etape: "erreur", message: e instanceof Error ? e.message : "Dictée impossible." });
    }
  }
}

/** Message court de l'état de la dictée (bulle discrète). */
export function messageDictee(e: EtatDicteeEnCours): string | null {
  switch (e.etape) {
    case "repos":
      return null;
    case "ecoute":
      return "Dictée : parlez, puis relâchez le raccourci";
    case "transcription":
      return "Transcription…";
    case "fini":
      if (!e.resultat.texte) return "Rien entendu";
      return e.resultat.colle ? `Collé${e.resultat.programme ? ` dans ${e.resultat.programme}` : ""}` : "Texte prêt";
    case "erreur":
      return e.message;
  }
}
