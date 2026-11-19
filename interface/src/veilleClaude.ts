// Alertes de la veille des sessions Claude Code (lecture seule, désactivée par défaut) : quand une session de
// l'utilisateur l'attend ou réclame une permission, JARVIS le dit (bandeau), à voix haute si l'utilisateur l'a
// choisi, et par une notification du système quand l'interface n'est pas au premier plan (téléphone compris).

import { useEffect, useRef } from "react";

import { lireVeille } from "./api";
import type { AlerteVeille, ReglagesVeille } from "./types";

/** Événement de fenêtre : les réglages de la veille ont changé (relire tout de suite). */
export const EVENEMENT_VEILLE = "jarvis2:veille";
const SONDAGE_ACTIF = 5000;
const SONDAGE_INACTIF = 60000;

export function signalerVeille(): void {
  window.dispatchEvent(new Event(EVENEMENT_VEILLE));
}

/** Notification du système, seulement si l'utilisateur l'a autorisée et que la page est cachée. */
async function notificationSysteme(texte: string): Promise<void> {
  if (!("Notification" in window) || Notification.permission !== "granted" || document.visibilityState === "visible") return;
  const options = { body: texte, tag: "jarvis2-veille-claude", icon: "/icone-192.png" };
  try {
    const inscription = "serviceWorker" in navigator ? await navigator.serviceWorker.getRegistration() : undefined;
    if (inscription) {
      await inscription.showNotification("JARVIS", options);
      return;
    }
  } catch {
    /* service worker indisponible : notification directe */
  }
  try {
    new Notification("JARVIS", options);
  } catch {
    /* refusée par le navigateur (certains mobiles exigent le service worker) : le bandeau suffit */
  }
}

export function demanderPermissionNotifications(): Promise<NotificationPermission | "indisponible"> {
  if (!("Notification" in window)) return Promise.resolve("indisponible");
  if (Notification.permission !== "default") return Promise.resolve(Notification.permission);
  return Notification.requestPermission();
}

/** Sonde la veille et annonce ses nouvelles alertes ; ne rejoue jamais les alertes d'avant le chargement. */
export function useAlertesVeille(annoncer: (alerte: AlerteVeille, reglages: ReglagesVeille) => void): void {
  const annonce = useRef(annoncer);
  annonce.current = annoncer;
  useEffect(() => {
    let dernier: number | null = null;
    let minuterie: number | undefined;
    let arrete = false;
    const sonder = () => {
      window.clearTimeout(minuterie);
      lireVeille(dernier ?? 0)
        .then((v) => {
          if (dernier !== null && v.dernier < dernier) dernier = 0; // Core redémarré : ses alertes repartent de 1
          const nouvelles = v.alertes.filter((a) => dernier !== null && a.id > dernier);
          const max = v.alertes.reduce((m, a) => Math.max(m, a.id), dernier ?? 0);
          dernier = max;
          for (const a of nouvelles) {
            annonce.current(a, v.reglages);
            if (v.reglages.notification) void notificationSysteme(a.texte);
          }
          if (!arrete) minuterie = window.setTimeout(sonder, v.reglages.actif ? SONDAGE_ACTIF : SONDAGE_INACTIF);
        })
        .catch(() => {
          if (!arrete) minuterie = window.setTimeout(sonder, SONDAGE_INACTIF);
        });
    };
    sonder();
    window.addEventListener(EVENEMENT_VEILLE, sonder);
    return () => {
      arrete = true;
      window.clearTimeout(minuterie);
      window.removeEventListener(EVENEMENT_VEILLE, sonder);
    };
  }, []);
}
