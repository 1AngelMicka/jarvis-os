import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./styles/tokens.css";
import "./styles/hud.css";

const racine = document.getElementById("racine");
if (!racine) throw new Error("Élément #racine absent de index.html");

// Interface installable (PWA) : seulement l'interface compilée, en contexte sûr (localhost ou HTTPS Tailscale)
if (import.meta.env.PROD && "serviceWorker" in navigator && window.isSecureContext) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      /* sans service worker, JARVIS fonctionne pareil (pas d'installation sur l'écran d'accueil) */
    });
  });
}

createRoot(racine).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
