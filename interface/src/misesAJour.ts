// Indicateur « nouvelle version » des Réglages (Appareils › Version et mises à jour) : textes et lien sûrs.

import type { EtatMisesAJour } from "./types";

const PAGE_VERSIONS = "https://github.com/1AngelMicka/jarvis-os/releases";
const DATE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", year: "numeric" });

/** Lien vers la page de la version : seulement les versions de ce dépôt (sinon la liste des versions). */
export function lienVersion(url: string | null): string {
  return url && (url === PAGE_VERSIONS || url.startsWith(`${PAGE_VERSIONS}/`)) ? url : PAGE_VERSIONS;
}

function date(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : DATE.format(d);
}

/** Phrase d'état sous la version installée. */
export function resumeMisesAJour(e: EtatMisesAJour): { texte: string; ton: "ok" | "attention" | undefined } {
  if (!e.active) return { texte: "Vérification désactivée : JARVIS ne contacte pas GitHub.", ton: undefined };
  if (e.nouvelle && e.derniere) {
    const publiee = date(e.publiee_le);
    return { texte: `Nouvelle version ${e.derniere} disponible${publiee ? ` (publiée le ${publiee})` : ""}.`, ton: "attention" };
  }
  const verifiee = date(e.verifie_le);
  if (e.erreur) return { texte: `Dernière vérification impossible : ${e.erreur}.`, ton: undefined };
  if (e.derniere) return { texte: `À jour${verifiee ? ` (vérifié le ${verifiee})` : ""}.`, ton: "ok" };
  return { texte: "Pas encore vérifié.", ton: undefined };
}
