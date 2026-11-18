// Préférences de l'appareil (moteur, modèle, effort). Le stockage local peut être indisponible
// (navigation privée, stockage bloqué) : l'interface fonctionne alors avec les valeurs par défaut.

export interface Preferences {
  moteur?: string;
  modeles?: Record<string, string>;
  effort?: string;
}

const CLE = "jarvis2.preferences";

export function lirePreferences(): Preferences {
  try {
    const brut = localStorage.getItem(CLE);
    return brut ? (JSON.parse(brut) as Preferences) : {};
  } catch {
    return {};
  }
}

export function ecrirePreferences(p: Preferences): void {
  try {
    localStorage.setItem(CLE, JSON.stringify(p));
  } catch {
    /* stockage indisponible : préférence gardée pour cette page seulement */
  }
}
