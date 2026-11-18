// Jeton de cet appareil. Stocké localement (le stockage peut être indisponible : l'appareil devra alors être
// jumelé à chaque ouverture). Un 401 du Core efface le jeton et ramène à l'écran de jumelage.

const CLE = "jarvis2.jeton";
let enMemoire: string | null = null;

export function lireJeton(): string | null {
  try {
    return localStorage.getItem(CLE) ?? enMemoire;
  } catch {
    return enMemoire;
  }
}

export function ecrireJeton(jeton: string | null): void {
  enMemoire = jeton;
  try {
    if (jeton) localStorage.setItem(CLE, jeton);
    else localStorage.removeItem(CLE);
  } catch {
    /* stockage indisponible : jeton gardé pour cette page seulement */
  }
}

export const EVENEMENT_NON_AUTORISE = "jarvis:non-autorise";
