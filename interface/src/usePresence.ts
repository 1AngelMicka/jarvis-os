// Ce que le HUD doit savoir du thème « Présence » : est-il choisi, l'orbe est-il en fond d'écran, JARVIS parle-t-il,
// le micro est-il ouvert. Suit les événements de fenêtre (aucune lecture répétée).

import { useEffect, useState } from "react";

import { EVENEMENT_FOND, EVENEMENT_MICRO, EVENEMENT_PAROLE, lireFondEcran, microOuvert } from "./presence";
import { EVENEMENT_THEME, lireTheme } from "./theme";

export function usePresence(): { actif: boolean; fond: boolean; parle: boolean; micro: boolean } {
  const [theme, setTheme] = useState(lireTheme);
  const [fond, setFond] = useState(lireFondEcran);
  const [parle, setParle] = useState(false);
  const [micro, setMicro] = useState(microOuvert);

  useEffect(() => {
    const surTheme = () => {
      setTheme(lireTheme());
    };
    const surFond = (e: Event) => {
      setFond((e as CustomEvent<unknown>).detail === true);
    };
    const surParole = (e: Event) => {
      setParle((e as CustomEvent<unknown>).detail === true);
    };
    const surMicro = (e: Event) => {
      setMicro((e as CustomEvent<unknown>).detail === true);
    };
    window.addEventListener(EVENEMENT_THEME, surTheme);
    window.addEventListener(EVENEMENT_FOND, surFond);
    window.addEventListener(EVENEMENT_PAROLE, surParole);
    window.addEventListener(EVENEMENT_MICRO, surMicro);
    return () => {
      window.removeEventListener(EVENEMENT_THEME, surTheme);
      window.removeEventListener(EVENEMENT_FOND, surFond);
      window.removeEventListener(EVENEMENT_PAROLE, surParole);
      window.removeEventListener(EVENEMENT_MICRO, surMicro);
    };
  }, []);

  const actif = theme === "presence";
  return { actif, fond: actif && fond, parle, micro };
}
