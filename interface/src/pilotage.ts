// JARVIS pilote l'interface (lot F) : ce que l'interface fait du bloc d'actions validé par le Core.
// Le Core retire le bloc `<actions>…</actions>` de la réponse finale ; pendant le flux, l'interface le masque déjà
// (ni affiché, ni lu à voix haute). Une action « immédiate » (aller vers une vue, ouvrir un élément) s'applique seule en
// mode « oui », sur un clic en mode « demander » ; une « proposition » (mission, atelier, action sensible, règle) attend
// TOUJOURS le clic de l'utilisateur.

import type { ActionPilotage, ModePilotage } from "./types";

// Blocs masqués pendant le flux : actions (lot F) et widgets (14 · D 16), retirés par le Core à la fin
const OUVERTURES = ["<actions", "<widget"];

/** Texte à montrer pendant le flux : tout ce qui précède `<actions` ou `<widget`, sans un début de balise incomplet. */
export function texteVisible(texte: string): string {
  const bas = texte.toLowerCase();
  const debuts = OUVERTURES.map((o) => bas.indexOf(o)).filter((i) => i >= 0);
  if (debuts.length) return texte.slice(0, Math.min(...debuts)).trimEnd();
  // « Voici <ac » : le morceau suivant dira si c'est le bloc ; en attendant, rien n'est montré de cette fin
  for (let n = Math.max(...OUVERTURES.map((o) => o.length)) - 1; n > 0; n--) {
    if (n <= bas.length && OUVERTURES.some((o) => n < o.length && bas.endsWith(o.slice(0, n)))) return texte.slice(0, texte.length - n);
  }
  return texte;
}

/** Vues et panneaux que JARVIS peut ouvrir (même liste que `VUES` du Core, pilotage.py). */
export type VuePilotable =
  | "dialogue"
  | "historique"
  | "activite"
  | "demandes"
  | "securite"
  | "memoire"
  | "connaissances"
  | "agents"
  | "ateliers"
  | "ameliorations"
  | "connecteurs"
  | "couts"
  | "reglages"
  | "accueil";

export const MODES_PILOTAGE: readonly { id: ModePilotage; nom: string }[] = [
  { id: "oui", nom: "Oui" },
  { id: "demander", nom: "Me demander" },
  { id: "non", nom: "Non" },
];

/** Actions immédiates à appliquer seules à la fin d'une réponse en direct (jamais en relisant l'historique). */
export function aAppliquerSeules(actions: readonly ActionPilotage[] | undefined, mode: ModePilotage): ActionPilotage[] {
  if (mode !== "oui" || !actions) return [];
  // Une seule navigation : la dernière vue demandée l'emporte (deux vues ne s'ouvrent pas en même temps)
  // Une action retenue par la barrière d'injection n'est jamais appliquée seule
  const immediates = actions.filter((a) => a.genre === "immediate" && !a.bloquee);
  const derniere = immediates.at(-1);
  return derniere ? [derniere] : [];
}

/** Libellé du bouton d'une action. */
export function libelleBouton(a: ActionPilotage, deja: boolean): string {
  if (a.bloquee && !deja) return "Lancer moi-même";
  if (a.genre === "immediate") return deja ? "Rouvrir" : "Ouvrir";
  switch (a.type) {
    case "proposer_mission":
      return "Lancer la mission";
    case "proposer_atelier":
      return "Ouvrir l'atelier";
    case "proposer_amelioration":
      return "Garder la suggestion";
    case "demander_action":
      return a.niveau === "rouge" ? "Demander (clé d'accès)" : "Demander l'accord";
    case "ajouter_regle":
      return "Ajouter la règle";
    default:
      return "Valider";
  }
}

export const EMOJI_NIVEAU: Record<string, string> = { vert: "🟢", jaune: "🟡", rouge: "🔴" };

/** Émis quand le mode de pilotage change (Réglages) : l'application relit le mode. */
export const EVENEMENT_PILOTAGE = "jarvis2:pilotage";
