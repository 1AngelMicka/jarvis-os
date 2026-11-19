// Animations de l'interface, choisies par appareil : « selon le système » (prefers-reduced-motion), « normales » ou
// « réduites ». Appliquées avant le premier rendu (main.tsx) par `html[data-animations="reduites"]` (DESIGN.md, règle 5).

export const CHOIX_ANIMATIONS = [
  { id: "systeme", nom: "Selon le système" },
  { id: "normales", nom: "Normales" },
  { id: "reduites", nom: "Réduites" },
] as const;

export type ChoixAnimations = (typeof CHOIX_ANIMATIONS)[number]["id"];

const CLE = "jarvis2.animations";
const REQUETE = "(prefers-reduced-motion: reduce)";

export function estChoixAnimations(v: unknown): v is ChoixAnimations {
  return CHOIX_ANIMATIONS.some((c) => c.id === v);
}

export function lireAnimations(): ChoixAnimations {
  try {
    const v = localStorage.getItem(CLE);
    if (estChoixAnimations(v)) return v;
  } catch {
    /* stockage indisponible */
  }
  return "systeme";
}

/** Le choix donne-t-il des animations réduites, compte tenu de la préférence du système ? */
export function sontReduites(choix: ChoixAnimations, systemeReduit: boolean): boolean {
  return choix === "reduites" || (choix === "systeme" && systemeReduit);
}

function systemeReduit(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(REQUETE).matches;
}

export function appliquerAnimations(choix: ChoixAnimations): void {
  const racine = document.documentElement;
  if (sontReduites(choix, systemeReduit())) racine.dataset.animations = "reduites";
  else delete racine.dataset.animations;
}

/** Au démarrage : applique le choix et suit les changements de la préférence du système. */
export function initialiserAnimations(): void {
  appliquerAnimations(lireAnimations());
  if (typeof window.matchMedia !== "function") return;
  window.matchMedia(REQUETE).addEventListener("change", () => {
    appliquerAnimations(lireAnimations());
  });
}

export const EVENEMENT_ANIMATIONS = "jarvis2:animations";

export function choisirAnimations(choix: ChoixAnimations): void {
  try {
    localStorage.setItem(CLE, choix);
  } catch {
    /* stockage indisponible : choix gardé pour cette page */
  }
  appliquerAnimations(choix);
  window.dispatchEvent(new CustomEvent(EVENEMENT_ANIMATIONS, { detail: choix }));
}
