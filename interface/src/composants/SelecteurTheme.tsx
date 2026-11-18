import { useEffect, useId, useState } from "react";

import { appliquerTheme, estTheme, lireTheme, type Theme, THEMES } from "../theme";

const EVENEMENT = "jarvis2:theme";

/** Choix du thème ; plusieurs sélecteurs à l'écran restent d'accord (événement de fenêtre). */
export function SelecteurTheme({ className, libelleVisible = false }: { className?: string; libelleVisible?: boolean }) {
  const [theme, setTheme] = useState<Theme>(lireTheme);
  const id = useId();

  useEffect(() => {
    const suivre = (e: Event) => {
      const t = (e as CustomEvent<unknown>).detail;
      if (estTheme(t)) setTheme(t);
    };
    window.addEventListener(EVENEMENT, suivre);
    return () => {
      window.removeEventListener(EVENEMENT, suivre);
    };
  }, []);

  return (
    <span className={["selecteur-theme", className].filter(Boolean).join(" ")}>
      <label htmlFor={id} className={libelleVisible ? "selecteur-theme-libelle" : "visuellement-cache"}>
        Thème
      </label>
      <select
        id={id}
        className="select"
        value={theme}
        onChange={(e) => {
          const t = e.target.value;
          if (!estTheme(t)) return;
          appliquerTheme(t, true);
          setTheme(t);
          window.dispatchEvent(new CustomEvent(EVENEMENT, { detail: t }));
        }}
      >
        {THEMES.map((t) => (
          <option key={t.id} value={t.id}>
            {t.nom}
          </option>
        ))}
      </select>
    </span>
  );
}
