import { useEffect, useId, useState } from "react";

import { useLangue } from "../i18n/react";
import { choisirTheme, estTheme, EVENEMENT_THEME as EVENEMENT, lireTheme, type Theme, THEMES } from "../theme";

/** Choix du thème ; plusieurs sélecteurs à l'écran restent d'accord (événement de fenêtre). */
export function SelecteurTheme({ className, libelleVisible = false }: { className?: string; libelleVisible?: boolean }) {
  const { t } = useLangue();
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
        {t("theme.libelle")}
      </label>
      <select
        id={id}
        className="select"
        value={theme}
        onChange={(e) => {
          const v = e.target.value;
          if (!estTheme(v)) return;
          choisirTheme(v);
          setTheme(v);
        }}
      >
        {THEMES.map((x) => (
          <option key={x.id} value={x.id}>
            {t(`theme.${x.id}`)}
          </option>
        ))}
      </select>
    </span>
  );
}
