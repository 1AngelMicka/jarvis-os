// Thème « Présence » : JARVIS en orbe de particules. Ce module ne dessine rien ; il porte ce que l'orbe lit :
// - l'état (veille, écoute, réflexion, parole, compactage) déduit des états réels de l'interface ;
// - le signal audio (niveau du micro, impulsions de la voix), PUBLIÉ par le fil audio (voix.ts) et LU par la boucle de
//   rendu à son rythme : le rendu ne ralentit jamais l'audio, l'audio ne déclenche jamais un rendu React ;
// - la grille spatiale qui trouve les voisins des particules sans tout comparer à tout ;
// - l'option « HUD en fond d'écran », gardée par appareil.

export type EtatPresence = "veille" | "ecoute" | "reflexion" | "parole" | "compactage";

export const LIBELLES_PRESENCE: Record<EtatPresence, string> = {
  veille: "Prêt",
  ecoute: "Écoute",
  reflexion: "Réflexion",
  parole: "Réponse",
  compactage: "Compactage",
};

export interface Activite {
  /** Une réponse est demandée au moteur. */
  enCours: boolean;
  /** Le premier morceau de la réponse est arrivé. */
  premierMorceau: boolean;
  /** JARVIS lit une réponse à voix haute. */
  parle: boolean;
  /** Le micro est ouvert (dictée ou mains libres). */
  microOuvert: boolean;
  /** Une conversation est en train d'être résumée dans la mémoire. */
  compactage: boolean;
}

/** État de l'orbe : ce qui occupe JARVIS passe avant ce qu'il entend. */
export function etatPresence(a: Activite): EtatPresence {
  if (a.compactage) return "compactage";
  if (a.parle || (a.enCours && a.premierMorceau)) return "parole";
  if (a.enCours) return "reflexion";
  if (a.microOuvert) return "ecoute";
  return "veille";
}

/** Réglages du mouvement par état ; l'orbe glisse d'un jeu à l'autre (jamais de saut). */
export interface Mouvement {
  /** Rayon relatif de la sphère. */
  rayon: number;
  /** Amplitude de la houle de surface. */
  houle: number;
  /** Vitesse du temps du bruit. */
  vitesse: number;
  /** Tours par seconde autour de l'axe vertical. */
  rotation: number;
  /** 0 : sphère ; 1 : particules aplaties en anneau serré (compactage). */
  anneau: number;
  /** Part de la voix ou du micro dans la houle. */
  reactivite: number;
  /** Opacité des liens entre voisins. */
  liens: number;
}

export const MOUVEMENTS: Record<EtatPresence, Mouvement> = {
  veille: { rayon: 0.78, houle: 0.06, vitesse: 0.18, rotation: 0.012, anneau: 0, reactivite: 0.25, liens: 0.22 },
  ecoute: { rayon: 0.8, houle: 0.08, vitesse: 0.3, rotation: 0.02, anneau: 0, reactivite: 1, liens: 0.3 },
  reflexion: { rayon: 0.74, houle: 0.14, vitesse: 0.9, rotation: 0.07, anneau: 0, reactivite: 0.2, liens: 0.4 },
  parole: { rayon: 0.82, houle: 0.1, vitesse: 0.5, rotation: 0.03, anneau: 0, reactivite: 1, liens: 0.32 },
  compactage: { rayon: 0.62, houle: 0.04, vitesse: 0.6, rotation: 0.16, anneau: 1, reactivite: 0.1, liens: 0.12 },
};

/** Rapproche `de` de `vers` d'une fraction qui dépend du temps écoulé (indépendant de la fréquence d'affichage). */
export function rapprocher(de: number, vers: number, dt: number, demiVie: number): number {
  const k = 1 - Math.pow(0.5, dt / Math.max(demiVie, 1e-6));
  return de + (vers - de) * k;
}

export function rapprocherMouvement(de: Mouvement, vers: Mouvement, dt: number, demiVie: number): Mouvement {
  return {
    rayon: rapprocher(de.rayon, vers.rayon, dt, demiVie),
    houle: rapprocher(de.houle, vers.houle, dt, demiVie),
    vitesse: rapprocher(de.vitesse, vers.vitesse, dt, demiVie),
    rotation: rapprocher(de.rotation, vers.rotation, dt, demiVie),
    anneau: rapprocher(de.anneau, vers.anneau, dt, demiVie),
    reactivite: rapprocher(de.reactivite, vers.reactivite, dt, demiVie),
    liens: rapprocher(de.liens, vers.liens, dt, demiVie),
  };
}

/** Densité de pixels du rendu : jamais plus de 2 (au-delà, le coût monte sans gain visible). */
export function densitePixels(dpr: number): number {
  if (!Number.isFinite(dpr) || dpr <= 0) return 1;
  return Math.min(dpr, 2);
}

/** Points répartis régulièrement sur la sphère unité (spirale de Fibonacci) : x, y, z à la suite. */
export function sphereFibonacci(n: number): Float32Array {
  const points = new Float32Array(n * 3);
  const orAngle = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    const y = n === 1 ? 0 : 1 - (i / (n - 1)) * 2;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const a = i * orAngle;
    points[i * 3] = Math.cos(a) * r;
    points[i * 3 + 1] = y;
    points[i * 3 + 2] = Math.sin(a) * r;
  }
  return points;
}

/** Paires de voisins (i < j) à moins de `distance`, trouvées par grille spatiale : chaque point ne regarde que les
 *  27 cases autour de la sienne. Au plus `parPoint` liens partent de chaque point (lisibilité, coût borné). */
export function voisinsParGrille(points: Float32Array, distance: number, parPoint: number): Uint32Array {
  const n = points.length / 3;
  const cle = (x: number, y: number, z: number) => `${String(x)},${String(y)},${String(z)}`;
  const cases = new Map<string, number[]>();
  const caseDe = (v: number) => Math.floor(v / distance);
  for (let i = 0; i < n; i++) {
    const k = cle(caseDe(points[i * 3] ?? 0), caseDe(points[i * 3 + 1] ?? 0), caseDe(points[i * 3 + 2] ?? 0));
    const liste = cases.get(k);
    if (liste) liste.push(i);
    else cases.set(k, [i]);
  }
  const d2 = distance * distance;
  const paires: number[] = [];
  for (let i = 0; i < n; i++) {
    const x = points[i * 3] ?? 0;
    const y = points[i * 3 + 1] ?? 0;
    const z = points[i * 3 + 2] ?? 0;
    const cx = caseDe(x);
    const cy = caseDe(y);
    const cz = caseDe(z);
    let liens = 0;
    for (let dx = -1; dx <= 1 && liens < parPoint; dx++) {
      for (let dy = -1; dy <= 1 && liens < parPoint; dy++) {
        for (let dz = -1; dz <= 1 && liens < parPoint; dz++) {
          for (const j of cases.get(cle(cx + dx, cy + dy, cz + dz)) ?? []) {
            if (j <= i) continue;
            const ex = (points[j * 3] ?? 0) - x;
            const ey = (points[j * 3 + 1] ?? 0) - y;
            const ez = (points[j * 3 + 2] ?? 0) - z;
            if (ex * ex + ey * ey + ez * ez > d2) continue;
            paires.push(i, j);
            if (++liens >= parPoint) break;
          }
        }
      }
    }
  }
  return Uint32Array.from(paires);
}

// ---------- Signal audio (écrit par le fil audio, lu par la boucle de rendu) ----------

const signal = { micro: 0, impulsion: 0, microOuvert: false, parle: false };

/** Événement de fenêtre : le micro s'ouvre ou se ferme (détail : booléen). */
export const EVENEMENT_MICRO = "jarvis2:micro";
/** Événement de fenêtre : JARVIS commence ou cesse de parler (détail : booléen). */
export const EVENEMENT_PAROLE = "jarvis2:parole";

/** Niveau efficace du micro (0 à 1 environ), publié par l'analyse audio à son propre rythme. */
export function publierNiveauMicro(niveau: number): void {
  signal.micro = Number.isFinite(niveau) ? Math.max(0, niveau) : 0;
}

/** Niveau du micro mis à l'échelle de l'affichage (0 à 1) : la voix parlée tourne autour de 0,02 à 0,2. */
export function niveauMicro(): number {
  return signal.microOuvert ? Math.min(1, Math.sqrt(signal.micro / 0.2)) : 0;
}

export function signalerMicro(ouvert: boolean): void {
  if (signal.microOuvert === ouvert) return;
  signal.microOuvert = ouvert;
  if (!ouvert) signal.micro = 0;
  window.dispatchEvent(new CustomEvent(EVENEMENT_MICRO, { detail: ouvert }));
}

export function microOuvert(): boolean {
  return signal.microOuvert;
}

/** Un mot vient d'être prononcé par la voix de JARVIS (la synthèse ne donne pas d'audio à analyser). */
export function impulsionVoix(): void {
  signal.impulsion = 1;
}

/** Lit puis amortit l'impulsion de la voix (appelé à chaque image). */
export function lireImpulsion(dt: number): number {
  const v = signal.impulsion;
  signal.impulsion = rapprocher(v, 0, dt, 0.12);
  return v;
}

export function signalerParole(parle: boolean): void {
  if (signal.parle === parle) return;
  signal.parle = parle;
  window.dispatchEvent(new CustomEvent(EVENEMENT_PAROLE, { detail: parle }));
}

// ---------- Option « HUD en fond d'écran » ----------

const CLE_FOND = "jarvis2.presence.fond";
export const EVENEMENT_FOND = "jarvis2:presence-fond";

export function lireFondEcran(): boolean {
  try {
    return localStorage.getItem(CLE_FOND) === "1";
  } catch {
    return false;
  }
}

export function choisirFondEcran(actif: boolean): void {
  try {
    if (actif) localStorage.setItem(CLE_FOND, "1");
    else localStorage.removeItem(CLE_FOND);
  } catch {
    /* stockage indisponible : choix gardé pour cette page */
  }
  window.dispatchEvent(new CustomEvent(EVENEMENT_FOND, { detail: actif }));
}
