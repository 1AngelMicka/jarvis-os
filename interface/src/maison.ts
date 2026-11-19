// Home Assistant, satellites, pièces et profils (lot 14 · D 18) : libellés et calculs sans React (testés dans maison.test.ts).

import type { CarteHomeAssistant, EtatWyoming, PieceMaison } from "./types";

export const NIVEAUX_MAISON = { vert: "🟢", jaune: "🟡", rouge: "🔴" } as const;

/** Statut affiché sur la carte Home Assistant. */
export function statutHomeAssistant(c: CarteHomeAssistant): { texte: string; ton: "ok" | "neutre" } {
  if (c.actif) return { texte: "Activé", ton: "ok" };
  if (c.pret) return { texte: "Désactivé", ton: "neutre" };
  return { texte: "À configurer", ton: "neutre" };
}

/** Comment JARVIS parle à Home Assistant, en clair. */
export function transportHomeAssistant(c: CarteHomeAssistant): string {
  if (c.mode === "mcp" && c.oauth) return c.jeton_rest ? "Serveur MCP (OAuth), repli REST prêt" : "Serveur MCP (OAuth)";
  if (c.mode === "mcp" && c.jeton_rest) return "Serveur MCP (jeton longue durée), repli REST prêt";
  if (c.jeton_rest) return "API REST (jeton longue durée)";
  return "Pas encore connecté";
}

/** Adresse acceptée par le Core (réseau local, Tailscale ou ce PC) : vérification légère avant l'envoi. */
export function adresseHomeAssistantPlausible(adresse: string): boolean {
  const texte = adresse.trim();
  if (texte.length < 3 || /\s/.test(texte)) return false;
  try {
    const u = new URL(texte.includes("://") ? texte : `http://${texte}`);
    return (u.protocol === "http:" || u.protocol === "https:") && u.hostname.length > 0 && (u.pathname === "/" || u.pathname === "");
  } catch {
    return false;
  }
}

/** « il y a 3 min », « il y a 2 h », « à l'instant » : présence dans une pièce. */
export function depuis(iso: string | null, maintenant: number = Date.now()): string {
  if (!iso) return "jamais entendue";
  const ecart = Math.max(0, Math.round((maintenant - new Date(iso).getTime()) / 1000));
  if (ecart < 60) return "à l'instant";
  if (ecart < 3600) return `il y a ${String(Math.round(ecart / 60))} min`;
  if (ecart < 86400) return `il y a ${String(Math.round(ecart / 3600))} h`;
  return `il y a ${String(Math.round(ecart / 86400))} j`;
}

/** Ligne de présence d'une pièce. */
export function presence(p: PieceMaison, maintenant: number = Date.now()): string {
  if (!p.vu_le) return "Personne entendue";
  const qui = p.personne ?? "Quelqu'un";
  return p.occupee ? `${qui}, ${depuis(p.vu_le, maintenant)}` : `Personne en ce moment (dernière voix ${depuis(p.vu_le, maintenant)})`;
}

/** Adresse à donner à Home Assistant (intégration Wyoming) ou aux satellites. */
export function adresseWyoming(w: EtatWyoming): string {
  return `${w.hote === "0.0.0.0" ? "adresse de ce PC" : w.hote}:${String(w.port_reel ?? w.port)}`;
}

/** Liste d'adresses saisie (virgules, espaces ou retours à la ligne) → adresses distinctes. */
export function lireClients(texte: string): string[] {
  return [...new Set(texte.split(/[\s,;]+/).map((a) => a.trim()).filter(Boolean))];
}
