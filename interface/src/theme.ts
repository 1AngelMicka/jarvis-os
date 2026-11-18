// Thème de l'interface, choisi par appareil (stockage local, comme les autres préférences). Appliqué avant le premier
// rendu (main.tsx) : pas d'éclair d'un autre thème au chargement.

export const THEMES = [
  { id: "jarvis", nom: "JARVIS" },
  { id: "studio", nom: "Studio nocturne" },
  { id: "atelier", nom: "Atelier clair" },
  { id: "console", nom: "Console épurée" },
] as const;

export type Theme = (typeof THEMES)[number]["id"];

const CLE = "jarvis2.theme";
const CLAIRS: readonly Theme[] = ["atelier"];

export function estTheme(valeur: unknown): valeur is Theme {
  return THEMES.some((t) => t.id === valeur);
}

export function lireTheme(): Theme {
  try {
    const t = localStorage.getItem(CLE);
    if (estTheme(t)) return t;
  } catch {
    /* stockage indisponible : thème par défaut */
  }
  return "jarvis";
}

/** Applique le thème au document (couleurs du navigateur et de la barre système comprises) et le mémorise. */
export function appliquerTheme(theme: Theme, memoriser = false): void {
  const racine = document.documentElement;
  racine.dataset.theme = theme;
  const clair = CLAIRS.includes(theme);
  document.querySelector('meta[name="color-scheme"]')?.setAttribute("content", clair ? "light" : "dark");
  const fond = getComputedStyle(racine).getPropertyValue("--c-vide").trim().split(/\s+/).join(", ");
  if (fond) document.querySelector('meta[name="theme-color"]')?.setAttribute("content", `rgb(${fond})`);
  if (!memoriser) return;
  try {
    localStorage.setItem(CLE, theme);
  } catch {
    /* stockage indisponible : thème gardé pour cette page seulement */
  }
}
