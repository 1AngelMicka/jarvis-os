// Synthèse vocale au choix (lot K2) : voix du navigateur (locale), Piper (voix neuronale sur le PC) ou ElevenLabs
// (en ligne, avec la clé de l'utilisateur rangée dans le coffre du Core).
// - Les phrases sont synthétisées EN PARALLÈLE par le Core (quelques-unes d'avance) et lues DANS L'ORDRE.
// - Secours : si le moteur choisi échoue (Piper absent, clé refusée, phrase privée, Core injoignable), la phrase est
//   dite avec la voix du système : JARVIS n'est jamais muet.
// - Les secrets sont masqués avant toute lecture à voix haute (le Core masque aussi, plus finement, de son côté).
// - Coupure quand on parle par-dessus : détecteur trame de 10 ms par trame (annulation d'écho du navigateur si elle
//   est active, sinon RMS du micro contre celui du haut-parleur, casque détecté), même algorithme que `coupure.py`.

import { appeler, envoyer, ErreurApi } from "./api";
import { lireJeton } from "./auth";

export type MoteurSynthese = "navigateur" | "piper" | "elevenlabs";

export interface ReglagesSynthese {
  moteur: MoteurSynthese;
  voix_piper: string;
  voix_elevenlabs: string;
  coupure: boolean;
}

export interface EtatTelechargement {
  statut: string;
  octets: number;
  total: number | null;
  raison: string | null;
  taille_estimee: number | null;
}

export interface EtatSynthese {
  reglages: ReglagesSynthese;
  piper: { programme: boolean; voix: { id: string; nom: string; taille: number; prete: boolean }[]; telechargement: EtatTelechargement };
  elevenlabs: { cle: boolean; apercu: string | null };
  annulation_echo: boolean;
}

export const REGLAGES_DEFAUT: ReglagesSynthese = { moteur: "navigateur", voix_piper: "fr_FR-siwis-medium", voix_elevenlabs: "", coupure: true };

export const lireSynthese = () => appeler<EtatSynthese>("/v1/synthese");
export const reglerSynthese = (r: Partial<ReglagesSynthese>) => appeler<EtatSynthese>("/v1/synthese", { methode: "PUT", corps: r });
export const enregistrerCleElevenLabs = (cle: string) => appeler<EtatSynthese>("/v1/synthese/cle", { methode: "PUT", corps: { cle } });
export const supprimerCleElevenLabs = () => appeler<EtatSynthese>("/v1/synthese/cle", { methode: "DELETE" });
export const telechargerVoixPiper = () => envoyer<EtatSynthese>("/v1/synthese/piper/telecharger");

// --- Texte lu à voix haute ---------------------------------------------------------------------------------------

const SECRET_DIT = "(secret masqué)";
const SECRETS: RegExp[] = [
  /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g,
  /\bsk-(?:ant-|proj-|svcacct-|admin-)?[A-Za-z0-9_-]{16,}/g,
  /\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}/g,
  /\bAIza[0-9A-Za-z_-]{30,}/g,
  /\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})/g,
  /\bxox[abposr]-[A-Za-z0-9-]{10,}/g,
  /\b(?:AKIA|ASIA)[0-9A-Z]{16}\b/g,
  /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/g,
  /\[(?:SECRET :|CODE À)[^\]\n]*\]/g, // étiquettes déjà posées par le Core
];
// La valeur seule est masquée : « mot de passe : (secret masqué) » reste compréhensible
const SECRETS_VALEUR =
  /(\b(?:password|passwd|pwd|mot[ _]de[ _]passe|mdp|secret|token|jeton|api[_-]?key|cl[ée] d'api)["']?\s*[:=]\s*["']?)[^\s"']{6,}/gi;
const JETON_PORTEUR = /(\b(?:bearer|token)\s+)[A-Za-z0-9._~+/-]{16,}=*/gi;
const CODE_UNIQUE = /(\b(?:code|otp|pin)(?:\s+(?:de\s+)?(?:v[ée]rification|confirmation|connexion|s[ée]curit[ée]))?\s*(?:[:=]|est)\s*)\d{4,8}\b/gi;
const LONGUE_CHAINE = /\b(?=[A-Za-z0-9+/_-]*\d)(?=[A-Za-z0-9+/_-]*[A-Za-z])[A-Za-z0-9+/_-]{32,}={0,2}/g;

/** Texte prêt à dire : mise en forme retirée, secrets masqués (une clé lue à voix haute s'entend). */
export function textePourLecture(phrase: string): string {
  // Masquer AVANT de retirer la mise en forme : « ghp_… » ou « sk_live_… » perdraient sinon leur forme reconnaissable
  let texte = phrase.replace(/\*\*|__|`/g, "");
  for (const motif of SECRETS) texte = texte.replace(motif, SECRET_DIT);
  texte = texte.replace(SECRETS_VALEUR, `$1${SECRET_DIT}`).replace(JETON_PORTEUR, `$1${SECRET_DIT}`).replace(CODE_UNIQUE, `$1${SECRET_DIT}`);
  texte = texte.replace(LONGUE_CHAINE, SECRET_DIT);
  return texte.replace(/[*_`#>|]/g, " ").replace(/\s+/g, " ").trim();
}

const ARRET = /^(?:jarvis[\s,]*)?(?:stop|arr[eê]te(?:-toi)?|stoppe|ça suffit|c'est bon|tais[- ]toi|silence|chut)[\s.!]*$/i;
const SILENCE = /(?:tais[- ]toi|silence|chut)/i;

/** Phrase d'arrêt dite pendant la lecture : « stop » arrête la phrase, « silence » coupe la voix. */
export function commandeArret(texte: string): "stop" | "silence" | null {
  const t = texte.trim();
  if (!ARRET.test(t)) return null;
  return SILENCE.test(t) ? "silence" : "stop";
}

// --- Réglages courants (partagés par les lecteurs de la page) ------------------------------------------------------

let courants: ReglagesSynthese = REGLAGES_DEFAUT;
export const EVENEMENT_SYNTHESE = "jarvis2:synthese";

export function reglagesSynthese(): ReglagesSynthese {
  return courants;
}

export function appliquerReglagesSynthese(r: ReglagesSynthese): void {
  courants = r;
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(EVENEMENT_SYNTHESE, { detail: r }));
}

/** Au démarrage : les réglages du Core (sans eux, la voix du navigateur, locale). */
export function chargerReglagesSynthese(): void {
  lireSynthese()
    .then((e) => {
      appliquerReglagesSynthese(e.reglages);
    })
    .catch(() => {
      /* Core injoignable ou ancien : voix du navigateur */
    });
}

// --- Synthèse par le Core et voix du système ----------------------------------------------------------------------

/** Une phrase en audio par le Core (Piper ou ElevenLabs) ; une erreur = la voix du système prendra le relais. */
export async function synthetiserParLeCore(texte: string, moteur: Exclude<MoteurSynthese, "navigateur">, signal: AbortSignal): Promise<ArrayBuffer> {
  const jeton = lireJeton();
  const rep = await fetch("/v1/synthese/dire", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(jeton ? { Authorization: `Bearer ${jeton}` } : {}) },
    body: JSON.stringify({ texte, moteur }),
    signal,
  });
  // 204 : ce moteur ne peut pas dire la phrase (raison dans X-Voix-Raison) ; la voix du système prend le relais
  if (!rep.ok || rep.status === 204) throw new ErreurApi(`Synthèse ${moteur} indisponible`, rep.status);
  return rep.arrayBuffer();
}

export function voixFrancaiseLocale(): SpeechSynthesisVoice | null {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return null;
  const voix = window.speechSynthesis.getVoices().filter((v) => v.localService && v.lang.toLowerCase().startsWith("fr"));
  return voix.find((v) => v.default) ?? voix[0] ?? null;
}

/** Dit une phrase avec une voix LOCALE du système (jamais une voix en ligne) ; résolue à la fin de la phrase. */
export function direAvecLeSysteme(texte: string, surMot: () => void): Promise<void> {
  return new Promise((resoudre) => {
    const voix = voixFrancaiseLocale();
    if (!voix) {
      resoudre(); // aucune voix française locale : rien n'est envoyé à un service en ligne
      return;
    }
    const enonce = new SpeechSynthesisUtterance(texte);
    enonce.voice = voix;
    enonce.lang = voix.lang;
    enonce.onboundary = surMot;
    enonce.onend = () => {
      resoudre();
    };
    enonce.onerror = () => {
      resoudre();
    };
    window.speechSynthesis.speak(enonce);
  });
}

// --- File de lecture : en parallèle, dans l'ordre ------------------------------------------------------------------

export interface Sortie {
  /** Synthèse par le Core (rejet = secours). */
  synthetiser: (texte: string, moteur: Exclude<MoteurSynthese, "navigateur">, signal: AbortSignal) => Promise<ArrayBuffer>;
  /** Joue un audio jusqu'au bout (rejet = secours) ; `arreter` coupe le son en cours. */
  jouer: (audio: ArrayBuffer) => Promise<void>;
  /** Voix du système (secours, et moteur « navigateur »). */
  direSysteme: (texte: string) => Promise<void>;
  /** Une voix française locale existe-t-elle ? Sinon, Piper prend le relais (JARVIS n'est jamais muet). */
  systemeDisponible: () => boolean;
  arreter: () => void;
  /** Niveau (RMS) de ce que JARVIS envoie au haut-parleur : référence de la coupure. */
  niveau: () => number;
}

interface Entree {
  texte: string;
  audio: Promise<ArrayBuffer | null> | null; // null : voix du système
}

export const AVANCE = 3; // phrases synthétisées d'avance

export class FileSynthese {
  private file: Entree[] = [];
  private enLecture = false;
  private generation = 0;
  private abandon = new AbortController();
  parle = false;

  constructor(
    private readonly sortie: Sortie,
    private readonly evenements: { debut: () => void; fin: () => void },
    private readonly reglages: () => ReglagesSynthese = reglagesSynthese,
  ) {}

  /** Met une phrase dans la file ; sa synthèse commence tout de suite si la file a de la place d'avance. */
  dire(phrase: string): void {
    const texte = textePourLecture(phrase);
    if (!texte) return;
    this.file.push({ texte, audio: null });
    this.preparer();
    if (!this.enLecture) void this.lire(this.generation);
  }

  /** Lance la synthèse des prochaines phrases (au plus AVANCE en cours ou prêtes). */
  private preparer(): void {
    const choisi = this.reglages().moteur;
    const moteur = choisi === "navigateur" && !this.sortie.systemeDisponible() ? "piper" : choisi;
    if (moteur === "navigateur") return;
    const signal = this.abandon.signal;
    for (const e of this.file.slice(0, AVANCE)) {
      if (e.audio) continue;
      e.audio = this.sortie.synthetiser(e.texte, moteur, signal).catch(() => null);
    }
  }

  private async lire(generation: number): Promise<void> {
    this.enLecture = true;
    while (generation === this.generation && this.file.length) {
      const e = this.file[0];
      if (!e) break;
      this.preparer();
      const audio = e.audio ? await e.audio : null;
      if (generation !== this.generation) return;
      this.file.shift();
      this.preparer();
      this.signaler(true);
      let dite = false;
      if (audio) {
        try {
          await this.sortie.jouer(audio);
          dite = true;
        } catch {
          /* audio illisible : voix du système */
        }
      }
      if (generation !== this.generation) return;
      if (!dite) await this.sortie.direSysteme(e.texte);
    }
    if (generation === this.generation) {
      this.enLecture = false;
      this.signaler(false);
    }
  }

  private signaler(parle: boolean): void {
    if (parle === this.parle) return;
    this.parle = parle;
    if (parle) this.evenements.debut();
    else this.evenements.fin();
  }

  niveau(): number {
    return this.parle ? this.sortie.niveau() : 0;
  }

  /** Coupe tout : la phrase en cours, la file, les synthèses en route. */
  arreter(): void {
    this.generation += 1;
    this.abandon.abort();
    this.abandon = new AbortController();
    this.file = [];
    this.enLecture = false;
    this.sortie.arreter();
    this.signaler(false);
  }
}

/** Sortie réelle : Web Audio (pas d'élément <audio> : la CSP n'autorise aucun média externe) et voix du système. */
export function sortieNavigateur(surMot: () => void): Sortie {
  let contexte: AudioContext | null = null;
  let analyseur: AnalyserNode | null = null;
  let source: AudioBufferSourceNode | null = null;
  let systeme = false;
  const donnees = new Float32Array(512);
  const ouvrir = (): { contexte: AudioContext; analyseur: AnalyserNode } => {
    if (!contexte || !analyseur) {
      contexte = new AudioContext();
      analyseur = contexte.createAnalyser();
      analyseur.fftSize = 512;
      analyseur.connect(contexte.destination);
    }
    return { contexte, analyseur };
  };
  let rythme = 0;
  return {
    synthetiser: synthetiserParLeCore,
    async jouer(audio) {
      const { contexte: ctx, analyseur: an } = ouvrir();
      if (ctx.state === "suspended") await ctx.resume();
      const tampon = await ctx.decodeAudioData(audio);
      await new Promise<void>((resoudre) => {
        const s = ctx.createBufferSource();
        s.buffer = tampon;
        s.connect(an);
        s.onended = () => {
          window.clearInterval(rythme);
          if (source === s) source = null;
          resoudre();
        };
        source = s;
        rythme = window.setInterval(surMot, 260); // l'orbe vibre au rythme de la parole
        s.start();
      });
    },
    async direSysteme(texte) {
      systeme = true;
      try {
        await direAvecLeSysteme(texte, surMot);
      } finally {
        systeme = false;
      }
    },
    systemeDisponible: () => voixFrancaiseLocale() !== null,
    arreter() {
      window.clearInterval(rythme);
      try {
        source?.stop();
      } catch {
        /* déjà arrêtée */
      }
      source = null;
      if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    },
    niveau() {
      if (source && analyseur) {
        analyseur.getFloatTimeDomainData(donnees);
        return niveauEfficace(donnees);
      }
      return systeme ? NIVEAU_VOIX_SYSTEME : 0; // la voix du système ne se mesure pas : niveau supposé
    },
  };
}

const NIVEAU_VOIX_SYSTEME = 0.1;

export function niveauEfficace(donnees: Float32Array): number {
  let somme = 0;
  for (const x of donnees) somme += x * x;
  return Math.sqrt(somme / Math.max(1, donnees.length));
}

// --- Coupure quand on parle par-dessus -------------------------------------------------------------------------------

export const TRAME_MS = 10;
const SEUIL_PAROLE = 0.02;
const MARGE_ECHO = 2.5;
const MARGE_ECHO_ANNULE = 1.2; // l'annulation d'écho laisse un résidu
const TRAMES_DECISION = 12; // 120 ms de suite
const COUPLAGE_CASQUE = 0.03;
const DELAI_MAX_MS = 400;
const CASQUE = /casque|[ée]couteur|headset|headphone|earphone|earbud|airpods|buds|bluetooth|hands-?free/i;

export function casqueParNom(noms: string[]): boolean {
  return noms.some((n) => CASQUE.test(n));
}

/** Délai (ms) haut-parleur → micro par intercorrélation normalisée des enveloppes (une valeur par trame). */
export function mesurerDelai(reference: number[], micro: number[]): number | null {
  const n = Math.min(reference.length, micro.length);
  if (n < 10) return null;
  const ref = reference.slice(-n);
  const mic = micro.slice(-n);
  const moyR = ref.reduce((a, b) => a + b, 0) / n;
  if (Math.sqrt(ref.reduce((a, x) => a + (x - moyR) ** 2, 0)) < 1e-6) return null;
  let meilleur = 0;
  let decalageRetenu: number | null = null;
  for (let d = 0; d <= Math.min(DELAI_MAX_MS / TRAME_MS, n - 5); d++) {
    const r = ref.slice(0, n - d);
    const m = mic.slice(d);
    const mr = r.reduce((a, b) => a + b, 0) / r.length;
    const mm = m.reduce((a, b) => a + b, 0) / m.length;
    let num = 0;
    let dr = 0;
    let dm = 0;
    for (let i = 0; i < r.length; i++) {
      const a = (r[i] ?? 0) - mr;
      const b = (m[i] ?? 0) - mm;
      num += a * b;
      dr += a * a;
      dm += b * b;
    }
    const den = Math.sqrt(dr * dm);
    if (den < 1e-9) continue;
    if (num / den > meilleur) {
      meilleur = num / den;
      decalageRetenu = d;
    }
  }
  return decalageRetenu === null || meilleur < 0.5 ? null : decalageRetenu * TRAME_MS;
}

/** Décide, trame par trame (niveaux RMS de 10 ms), si l'utilisateur parle par-dessus JARVIS. */
export class DetecteurCoupure {
  private hp: number[] = [];
  private mic: number[] = [];
  private couplage: number | null = null;
  private suite = 0;
  private trames = 0;
  delaiMs = 0;

  constructor(
    public casque = false,
    readonly annulationEcho = false,
  ) {}

  get mode(): "casque" | "annulation_echo" | "rms" {
    if (this.casque) return "casque";
    return this.annulationEcho ? "annulation_echo" : "rms";
  }

  private hpDecale(): number {
    const recul = Math.floor(this.delaiMs / TRAME_MS);
    if (!this.hp.length) return 0;
    return this.hp[Math.max(0, this.hp.length - 1 - recul)] ?? 0;
  }

  trame(niveauMicro: number, niveauHautParleur: number): boolean {
    this.trames += 1;
    this.hp.push(niveauHautParleur);
    this.mic.push(niveauMicro);
    if (this.hp.length > 200) this.hp.shift();
    if (this.mic.length > 200) this.mic.shift();
    let seuil = SEUIL_PAROLE;
    if (!this.casque) {
      const echo = (this.couplage ?? 1) * this.hpDecale();
      seuil = Math.max(SEUIL_PAROLE, echo * (this.annulationEcho ? MARGE_ECHO_ANNULE : MARGE_ECHO));
    }
    const parle = niveauMicro > seuil;
    if (!parle) {
      if (niveauHautParleur > SEUIL_PAROLE) {
        const rapport = niveauMicro / niveauHautParleur;
        this.couplage = this.couplage === null ? rapport : Math.min(rapport, 0.98 * this.couplage + 0.02 * rapport);
      }
      if (this.trames % 50 === 0) {
        const delai = mesurerDelai(this.hp, this.mic);
        if (delai !== null) this.delaiMs = delai;
      }
      if (this.couplage !== null && this.couplage < COUPLAGE_CASQUE && this.trames > 100) this.casque = true;
    }
    this.suite = parle ? this.suite + 1 : 0;
    if (this.suite >= TRAMES_DECISION) {
      this.suite = 0;
      return true;
    }
    return false;
  }
}

/** Écoute le micro (flux déjà ouvert par les mains libres) pendant que JARVIS lit, et appelle `surCoupure` quand
 *  l'utilisateur parle par-dessus. Trames de 10 ms ; rien n'est enregistré ni envoyé. */
export class GardeCoupure {
  private contexte: AudioContext | null = null;
  private minuterie: number | undefined;
  private detecteur: DetecteurCoupure | null = null;

  constructor(
    private readonly flux: MediaStream,
    private readonly lecteur: { parle: boolean; niveauSortie: () => number },
    private readonly surCoupure: () => void,
  ) {}

  async demarrer(): Promise<void> {
    const piste = this.flux.getAudioTracks()[0];
    const annulation = piste?.getSettings().echoCancellation === true;
    let casque = false;
    try {
      const appareils = await navigator.mediaDevices.enumerateDevices();
      casque = casqueParNom(appareils.filter((a) => a.kind !== "videoinput").map((a) => a.label));
    } catch {
      /* liste des périphériques indisponible : le couplage mesuré le dira */
    }
    this.contexte = new AudioContext();
    const analyseur = this.contexte.createAnalyser();
    analyseur.fftSize = 512; // ~10 ms à 48 kHz
    this.contexte.createMediaStreamSource(this.flux).connect(analyseur);
    const donnees = new Float32Array(analyseur.fftSize);
    this.minuterie = window.setInterval(() => {
      if (!this.lecteur.parle) {
        this.detecteur = null; // nouvelle lecture : nouvel apprentissage du couplage et du délai
        return;
      }
      this.detecteur ??= new DetecteurCoupure(casque, annulation);
      analyseur.getFloatTimeDomainData(donnees);
      if (this.detecteur.trame(niveauEfficace(donnees), this.lecteur.niveauSortie())) {
        this.detecteur = null;
        this.surCoupure();
      }
    }, TRAME_MS);
  }

  arreter(): void {
    window.clearInterval(this.minuterie);
    void this.contexte?.close();
    this.contexte = null;
  }
}
