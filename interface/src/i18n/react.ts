// Hook React de la langue : un composant qui l'appelle se redessine quand l'utilisateur change de langue.
// `App` l'appelle aussi : tout l'arbre suit, y compris les composants qui n'utilisent que `t()`.

import { useSyncExternalStore } from "react";

import { EVENEMENT_LANGUE, type Langue, langueCourante, t, tn } from "./index";

function abonner(rappel: () => void): () => void {
  window.addEventListener(EVENEMENT_LANGUE, rappel);
  return () => {
    window.removeEventListener(EVENEMENT_LANGUE, rappel);
  };
}

export function useLangue(): { langue: Langue; t: typeof t; tn: typeof tn } {
  const langue = useSyncExternalStore(abonner, langueCourante, langueCourante);
  return { langue, t, tn };
}
