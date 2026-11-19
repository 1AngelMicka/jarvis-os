// Voix de JARVIS : lecture à voix haute phrase par phrase pendant la réponse, par la voix choisie (navigateur, Piper
// ou ElevenLabs : voir synthese.ts) ; enregistrement du micro (à la demande ou mains libres) pour la transcription
// sur le PC.

import { impulsionVoix, publierNiveauMicro, signalerMicro, signalerParole } from "./presence";
import { FileSynthese, sortieNavigateur } from "./synthese";

const FIN_DE_PHRASE = /[^.!?…\n]+[.!?…]+["»)]*\s+|[^\n]+\n+/g;

/** Lecteur à voix haute : `pousser` reçoit les morceaux du flux, chaque phrase complète est dite tout de suite. */
export class LecteurVocal {
  actif = false;
  private tampon = "";
  /** Coupé par l'utilisateur qui parle par-dessus : le reste de cette réponse n'est pas lu. */
  interrompu = false;
  // Phrases synthétisées en parallèle, lues dans l'ordre ; voix du système en secours. Créée au premier usage.
  private fileLecture: FileSynthese | null = null;

  get disponible(): boolean {
    return "speechSynthesis" in window || "AudioContext" in window;
  }

  get parle(): boolean {
    return this.fileLecture?.parle ?? false;
  }

  private get file(): FileSynthese {
    this.fileLecture ??= new FileSynthese(sortieNavigateur(impulsionVoix), {
      debut: () => {
        signalerParole(true);
      },
      fin: () => {
        signalerParole(false);
      },
    });
    return this.fileLecture;
  }

  private dire(phrase: string): void {
    if (this.disponible) this.file.dire(phrase);
  }

  /** Niveau de ce que JARVIS envoie au haut-parleur (référence de la coupure quand on parle par-dessus). */
  niveauSortie(): number {
    return this.fileLecture?.niveau() ?? 0;
  }

  /** L'utilisateur parle par-dessus : la lecture s'arrête, le reste de la réponse en cours n'est pas lu. */
  interrompre(): void {
    this.arreter();
    this.interrompu = true;
  }

  pousser(morceau: string): void {
    if (!this.actif || this.interrompu) return;
    this.tampon += morceau;
    let reste = this.tampon;
    for (const m of this.tampon.matchAll(FIN_DE_PHRASE)) {
      this.dire(m[0]);
      reste = reste.slice(m[0].length);
    }
    this.tampon = reste;
  }

  /** Lit un texte entier tout de suite, même si la lecture des réponses est coupée (demande explicite). */
  lire(texte: string): void {
    this.interrompu = false;
    for (const m of `${texte}\n`.matchAll(FIN_DE_PHRASE)) this.dire(m[0]);
  }

  finir(): void {
    if (this.actif && !this.interrompu && this.tampon.trim()) this.dire(this.tampon);
    this.tampon = "";
    this.interrompu = false; // la réponse suivante sera lue
  }

  arreter(): void {
    this.tampon = "";
    this.fileLecture?.arreter();
  }
}

/** Événement de fenêtre : la voix a été coupée ailleurs (Ctrl+M, « /silence », palette). */
export const EVENEMENT_SILENCE = "jarvis2:silence";

/** Coupe la lecture à voix haute tout de suite, et la désactive jusqu'à ce qu'on la rallume. */
export function couperVoix(lecteur: LecteurVocal): void {
  lecteur.actif = false;
  lecteur.arreter();
  window.dispatchEvent(new CustomEvent(EVENEMENT_SILENCE));
}

/** Événement de fenêtre : la lecture à voix haute a été allumée ou coupée ailleurs (Réglages) ; détail : booléen. */
export const EVENEMENT_VOIX = "jarvis2:voix";

/** Allume ou coupe la lecture à voix haute des réponses ; les boutons à l'écran suivent. */
export function reglerVoix(lecteur: LecteurVocal, actif: boolean): void {
  if (!actif) {
    couperVoix(lecteur);
    return;
  }
  lecteur.actif = true;
  window.dispatchEvent(new CustomEvent(EVENEMENT_VOIX, { detail: true }));
}

/** Voix françaises installées sur l'appareil (locales seulement : jamais une voix en ligne). */
export function voixLocales(): { nom: string; langue: string; defaut: boolean }[] {
  if (!("speechSynthesis" in window)) return [];
  return window.speechSynthesis
    .getVoices()
    .filter((v) => v.localService && v.lang.toLowerCase().startsWith("fr"))
    .map((v) => ({ nom: v.name, langue: v.lang, defaut: v.default }));
}

function typeAudio(): string {
  for (const t of ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm", "audio/mp4"]) {
    if (MediaRecorder.isTypeSupported(t)) return t;
  }
  return "";
}

/** Niveau efficace (RMS) d'un extrait audio. */
function niveauEfficace(donnees: Float32Array): number {
  let somme = 0;
  for (const x of donnees) somme += x * x;
  return Math.sqrt(somme / Math.max(1, donnees.length));
}

/** Enregistrement à la demande : `demarrer` puis `arreter` renvoie l'audio. */
export class Enregistreur {
  private flux: MediaStream | null = null;
  private rec: MediaRecorder | null = null;
  private morceaux: Blob[] = [];
  private contexte: AudioContext | null = null;
  private minuterie: number | undefined;

  async demarrer(): Promise<void> {
    this.flux = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    this.morceaux = [];
    this.rec = new MediaRecorder(this.flux, { mimeType: typeAudio() });
    this.rec.ondataavailable = (e) => {
      if (e.data.size) this.morceaux.push(e.data);
    };
    this.rec.start();
    this.mesurer(this.flux);
  }

  /** Niveau du micro pour l'affichage, sur son propre minuteur (jamais lié au rendu). */
  private mesurer(flux: MediaStream): void {
    try {
      this.contexte = new AudioContext();
      const analyseur = this.contexte.createAnalyser();
      analyseur.fftSize = 1024;
      this.contexte.createMediaStreamSource(flux).connect(analyseur);
      const donnees = new Float32Array(analyseur.fftSize);
      signalerMicro(true);
      this.minuterie = window.setInterval(() => {
        analyseur.getFloatTimeDomainData(donnees);
        publierNiveauMicro(niveauEfficace(donnees));
      }, 50);
    } catch {
      /* pas d'analyse possible : l'enregistrement continue sans jauge */
    }
  }

  arreter(): Promise<Blob> {
    return new Promise((resoudre) => {
      const rec = this.rec;
      if (!rec) {
        resoudre(new Blob());
        return;
      }
      window.clearInterval(this.minuterie);
      void this.contexte?.close();
      this.contexte = null;
      signalerMicro(false);
      rec.onstop = () => {
        this.flux?.getTracks().forEach((p) => {
          p.stop();
        });
        resoudre(new Blob(this.morceaux, { type: rec.mimeType }));
      };
      rec.stop();
    });
  }
}

/** Écoute mains libres : détecte chaque phrase dite (niveau sonore puis silence) et la remet à `surPhrase`.
 *  Rien ne part tant que personne ne parle ; l'écoute se met en pause pendant que JARVIS parle. */
export class EcouteMainsLibres {
  private flux: MediaStream | null = null;
  private contexte: AudioContext | null = null;
  private minuterie: number | undefined;
  private rec: MediaRecorder | null = null;
  private morceaux: Blob[] = [];
  private dernierSon = 0;
  private debut = 0;

  constructor(
    /** `debut` / `fin` : instants `performance.now()` du premier et du dernier son de la phrase. */
    private readonly surPhrase: (audio: Blob, debut: number, fin: number) => void,
    private readonly enPause: () => boolean,
  ) {}

  /** Flux du micro ouvert (pour la coupure quand on parle par-dessus). */
  get fluxMicro(): MediaStream | null {
    return this.flux;
  }

  async demarrer(): Promise<void> {
    this.flux = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    this.contexte = new AudioContext();
    const analyseur = this.contexte.createAnalyser();
    analyseur.fftSize = 1024;
    this.contexte.createMediaStreamSource(this.flux).connect(analyseur);
    const donnees = new Float32Array(analyseur.fftSize);
    signalerMicro(true);
    this.minuterie = window.setInterval(() => {
      analyseur.getFloatTimeDomainData(donnees);
      const niveau = niveauEfficace(donnees);
      publierNiveauMicro(niveau);
      const maintenant = performance.now();
      if (this.enPause()) {
        if (this.rec?.state === "recording") this.couper(false);
        return;
      }
      if (niveau > 0.02) {
        this.dernierSon = maintenant;
        if (!this.rec || this.rec.state !== "recording") this.commencer(maintenant);
      } else if (this.rec?.state === "recording" && maintenant - this.dernierSon > 900) {
        this.couper(maintenant - this.debut > 600); // plus de 0,6 s de parole : une phrase à transcrire
      }
      if (this.rec?.state === "recording" && maintenant - this.debut > 15_000) this.couper(true);
    }, 60);
  }

  private commencer(maintenant: number): void {
    if (!this.flux) return;
    this.morceaux = [];
    this.debut = maintenant;
    this.rec = new MediaRecorder(this.flux, { mimeType: typeAudio() });
    this.rec.ondataavailable = (e) => {
      if (e.data.size) this.morceaux.push(e.data);
    };
    this.rec.start();
  }

  private couper(garder: boolean): void {
    const rec = this.rec;
    if (!rec) return;
    this.rec = null;
    const debut = this.debut;
    const fin = this.dernierSon;
    rec.onstop = () => {
      if (garder) this.surPhrase(new Blob(this.morceaux, { type: rec.mimeType }), debut, fin);
    };
    rec.stop();
  }

  arreter(): void {
    window.clearInterval(this.minuterie);
    signalerMicro(false);
    this.couper(false);
    this.flux?.getTracks().forEach((p) => {
      p.stop();
    });
    void this.contexte?.close();
    this.flux = null;
    this.contexte = null;
  }
}

/** Capture d'écran DÉCLENCHÉE par l'utilisateur (le navigateur demande quelle fenêtre ou quel écran partager). */
export async function capturerEcran(): Promise<string> {
  const flux = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
  try {
    const video = document.createElement("video");
    video.muted = true;
    video.srcObject = flux;
    await video.play();
    const toile = document.createElement("canvas");
    const echelle = Math.min(1, 1600 / Math.max(video.videoWidth, 1));
    toile.width = Math.round(video.videoWidth * echelle);
    toile.height = Math.round(video.videoHeight * echelle);
    toile.getContext("2d")?.drawImage(video, 0, 0, toile.width, toile.height);
    return toile.toDataURL("image/jpeg", 0.85);
  } finally {
    flux.getTracks().forEach((p) => {
      p.stop();
    });
  }
}
