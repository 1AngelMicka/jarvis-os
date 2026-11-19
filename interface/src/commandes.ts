// Commandes de l'interface : palette Ctrl+K, commandes « / » dans la saisie, raccourcis clavier. Une seule liste,
// pour que la palette, les suggestions et l'aide disent toujours la même chose.

import { type Cle, t } from "./i18n";
import { THEMES, type Theme } from "./theme";

export type IdCommande =
  | "nouvelle"
  | "historique"
  | "chercher"
  | "theme"
  | "memoire"
  | "connecteurs"
  | "agents"
  | "ateliers"
  | "dialogue"
  | "installation"
  | "reglages"
  | "demandes"
  | "annuler"
  | "securite"
  | "silence"
  | "image"
  | "resumer"
  | "urgence"
  | "aide"
  | "palette";

export interface Commande {
  id: IdCommande;
  nom: string;
  description: string;
  /** Mot tapé après « / » dans la saisie (absent : commande de palette seulement). */
  slash?: string;
  alias?: readonly string[];
  /** Ce qui suit la commande « / » (affiché dans les suggestions et l'aide). */
  argument?: string;
  raccourci?: string;
  motsCles?: readonly string[];
  /** Action irréversible ou de sécurité : confirmation demandée. */
  danger?: boolean;
}

export const COMMANDES: readonly Commande[] = [
  { id: "nouvelle", nom: "Nouvelle conversation", description: "Repartir d'un dialogue vide", slash: "nouvelle", alias: ["new", "n"], motsCles: ["vider", "commencer"] },
  { id: "historique", nom: "Ouvrir l'historique", description: "Liste des conversations", slash: "historique", alias: ["hist", "h"], raccourci: "Ctrl+H", motsCles: ["conversations", "liste"] },
  { id: "chercher", nom: "Chercher une conversation", description: "Dans les titres et les messages", slash: "chercher", alias: ["recherche", "cherche"], argument: "mots", motsCles: ["trouver", "rechercher"] },
  { id: "theme", nom: "Changer de thème", description: "JARVIS, Studio nocturne, Atelier clair, Console épurée, Présence", slash: "theme", alias: ["themes"], argument: "nom du thème", motsCles: ["apparence", "couleurs", "clair", "sombre"] },
  { id: "memoire", nom: "Ouvrir la mémoire", description: "Tout ce que JARVIS sait, par origine", slash: "memoire", alias: ["souvenirs"], motsCles: ["souvenirs", "vue"] },
  { id: "connecteurs", nom: "Ouvrir les connecteurs", description: "Vos IA : comptes, clés, modèles locaux", slash: "connecteurs", alias: ["ia", "moteurs"], motsCles: ["vue", "modèles"] },
  { id: "agents", nom: "Ouvrir les agents", description: "Missions, recettes, créations, outils MCP", slash: "agents", alias: ["missions"], motsCles: ["vue"] },
  { id: "ateliers", nom: "Ouvrir les ateliers", description: "Claude Code dans vos projets", slash: "ateliers", alias: ["atelier"], motsCles: ["vue", "projets", "code"] },
  { id: "dialogue", nom: "Revenir au dialogue", description: "Fermer la vue en cours", slash: "dialogue", motsCles: ["vue", "retour"] },
  { id: "reglages", nom: "Ouvrir les réglages", description: "Thème, voix, accueil du matin, IA, coûts, mémoire, sécurité", slash: "reglages", alias: ["parametres", "systeme", "options", "preferences"], argument: "réglage cherché", motsCles: ["vue", "configuration", "regler"] },
  { id: "installation", nom: "Diagnostic de l'installation", description: "Vérifications du premier lancement", slash: "installation", alias: ["diagnostic"], motsCles: ["vue", "accueil"] },
  { id: "demandes", nom: "Voir les demandes", description: "Actions en attente de votre accord", slash: "demandes", alias: ["approbations"], motsCles: ["accord", "file"] },
  { id: "annuler", nom: "Annuler la dernière action", description: "Défait la dernière action réversible (24 h)", slash: "annuler", alias: ["undo", "defaire"], motsCles: ["annulation", "revenir", "corbeille"] },
  { id: "securite", nom: "Ouvrir la sécurité", description: "Appareils, clés d'accès, apparence", slash: "securite", alias: ["appareils"], motsCles: ["clés", "jumelage"] },
  { id: "silence", nom: "Couper la voix", description: "JARVIS arrête de parler", slash: "silence", alias: ["chut", "muet"], raccourci: "Ctrl+M", motsCles: ["voix", "parole", "son"] },
  { id: "image", nom: "Joindre une image", description: "Ou collez (Ctrl+V), ou glissez-la", slash: "image", alias: ["joindre", "photo"], motsCles: ["photo", "capture", "fichier"] },
  { id: "resumer", nom: "Résumer la conversation", description: "Le résumé va dans la mémoire", slash: "resumer", alias: ["resume"], motsCles: ["mémoire"] },
  { id: "urgence", nom: "Arrêt d'urgence", description: "Tout arrêter tout de suite (confirmation)", slash: "urgence", alias: ["stop"], danger: true, motsCles: ["arrêter", "stop", "sécurité"] },
  { id: "aide", nom: "Aide : commandes et raccourcis", description: "Tout ce qui se fait au clavier", slash: "aide", alias: ["help", "?"], raccourci: "?", motsCles: ["clavier", "raccourcis"] },
  { id: "palette", nom: "Palette de commandes", description: "Chercher et lancer une commande", raccourci: "Ctrl+K", motsCles: ["commandes"] },
];

/** Raccourcis affichés dans l'aide (ceux des commandes, plus ceux de la saisie). */
/** Raccourcis clavier ; touches et effets dans la langue courante (getters : relus à chaque affichage). */
const BRUTS: readonly { touches: string; effet: Cle }[] = [
  { touches: "Ctrl+K", effet: "raccourci.palette" },
  { touches: "Ctrl+H", effet: "raccourci.historique" },
  { touches: "Ctrl+M", effet: "raccourci.silence" },
  { touches: "/", effet: "raccourci.ecrire" },
  { touches: "?", effet: "raccourci.aide" },
  { touches: "Entrée", effet: "raccourci.envoyer" },
  { touches: "Maj+Entrée", effet: "raccourci.nouvelleLigne" },
  { touches: "Échap", effet: "raccourci.arreter" },
  { touches: "Ctrl+V", effet: "raccourci.collerImage" },
];

/** Touches dont le nom change avec la langue (les autres s'écrivent pareil partout). */
const TOUCHES_TRADUITES: Readonly<Record<string, Cle>> = {
  Entrée: "touche.entree",
  "Maj+Entrée": "touches.majEntree",
  Échap: "touche.echap",
};

export const RACCOURCIS: readonly { readonly touches: string; readonly effet: string }[] = BRUTS.map((r) => ({
  get touches() {
    const cle = TOUCHES_TRADUITES[r.touches];
    return cle ? t(cle) : r.touches;
  },
  get effet() {
    return t(r.effet);
  },
}));

/** Minuscules, sans accents ni espaces superflus : « Thème » = « theme ». */
export function normaliser(texte: string): string {
  return texte.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().replace(/\s+/g, " ").trim();
}

export function commande(id: IdCommande): Commande {
  const trouvee = COMMANDES.find((c) => c.id === id);
  if (!trouvee) throw new Error(`Commande inconnue : ${id}`);
  return trouvee;
}

export type Analyse =
  | { type: "texte" }
  | { type: "commande"; commande: Commande; argument: string }
  | { type: "inconnue"; nom: string };

/** Le texte de la saisie est-il une commande « / » ? « // » au début envoie le texte tel quel (sans un « / »). */
export function analyserCommande(texte: string): Analyse {
  const t = texte.trim();
  if (!t.startsWith("/") || t.startsWith("//")) return { type: "texte" };
  const [tete = "", ...reste] = t.slice(1).split(/\s+/);
  const nom = normaliser(tete);
  if (!nom) return { type: "inconnue", nom: "" };
  const trouvee = COMMANDES.find((c) => c.slash && (c.slash === nom || c.alias?.includes(nom)));
  return trouvee ? { type: "commande", commande: trouvee, argument: reste.join(" ") } : { type: "inconnue", nom: tete };
}

/** Texte à envoyer pour un message qui commence par « // » : un seul « / » reste. */
export function texteAEnvoyer(texte: string): string {
  const t = texte.trim();
  return t.startsWith("//") ? t.slice(1) : t;
}

/** Suggestions pendant la frappe d'une commande « / » (avant le premier espace) : préfixe du nom ou d'un alias. */
export function suggererSlash(texte: string): Commande[] {
  if (!texte.startsWith("/") || texte.startsWith("//") || /\s/.test(texte)) return [];
  const debut = normaliser(texte.slice(1));
  const avecSlash = COMMANDES.filter((c) => c.slash);
  if (!debut) return [...avecSlash];
  const exactes = avecSlash.filter((c) => c.slash?.startsWith(debut));
  const parAlias = avecSlash.filter((c) => !exactes.includes(c) && c.alias?.some((a) => a.startsWith(debut)));
  return [...exactes, ...parAlias];
}

/** Score d'une commande pour la recherche de la palette (0 : écartée). Tous les mots doivent être trouvés. */
export function score(c: Commande, requete: string): number {
  const mots = normaliser(requete).split(" ").filter(Boolean);
  if (!mots.length) return 1;
  const nom = normaliser(c.nom);
  const reste = normaliser([c.description, c.slash ?? "", ...(c.alias ?? []), ...(c.motsCles ?? [])].join(" "));
  let total = 0;
  for (const mot of mots) {
    if (nom.startsWith(mot)) total += 4;
    else if (nom.split(" ").some((m) => m.startsWith(mot))) total += 3;
    else if (nom.includes(mot)) total += 2;
    else if (reste.includes(mot)) total += 1;
    else return 0;
  }
  return total;
}

export function filtrerCommandes(requete: string, commandes: readonly Commande[] = COMMANDES): Commande[] {
  return commandes
    .map((c, i) => ({ c, s: score(c, requete), i }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s || a.i - b.i)
    .map((x) => x.c);
}

const SYNONYMES_THEMES: Record<Theme, readonly string[]> = {
  jarvis: ["jarvis", "defaut", "verre", "aurore"],
  studio: ["studio", "nocturne", "graphite", "sombre", "nuit"],
  atelier: ["atelier", "clair", "papier", "jour"],
  console: ["console", "epuree", "mono", "terminal"],
  presence: ["presence", "orbe", "particules"],
};

/** « /theme clair » → « atelier » ; sans argument ou inconnu : null. */
export function themeDepuis(argument: string): Theme | null {
  const a = normaliser(argument);
  if (!a) return null;
  for (const t of THEMES) {
    if (normaliser(t.nom) === a || SYNONYMES_THEMES[t.id].some((s) => s.startsWith(a) || a.split(" ").includes(s))) return t.id;
  }
  return null;
}

/** Thème suivant dans la liste (« /theme » sans argument). */
export function themeSuivant(actuel: Theme): Theme {
  const i = THEMES.findIndex((t) => t.id === actuel);
  return THEMES[(i + 1) % THEMES.length]?.id ?? "jarvis";
}

/** Raccourci clavier → commande (Ctrl ou Cmd + K, H, M). Rien quand une autre touche de modification est pressée. */
export function commandeDuRaccourci(e: { key: string; ctrlKey: boolean; metaKey: boolean; altKey: boolean; shiftKey: boolean }): IdCommande | null {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey) return null;
  switch (e.key.toLowerCase()) {
    case "k":
      return "palette";
    case "h":
      return "historique";
    case "m":
      return "silence";
    default:
      return null;
  }
}
