// Registre de la vue Réglages : catégories, sections, recherche et adresses directes (`#reglages/<catégorie ou
// section>`). Une seule liste, pour que la navigation, la recherche et les liens disent toujours la même chose.
// Chaque nouvelle fonctionnalité réglable déclare ici sa section.

import { normaliser } from "./commandes";
import { type Cle, t, traduire } from "./i18n";

export type IdCategorie = "ensemble" | "apparence" | "voix" | "cerveau" | "matin" | "pc" | "memoire" | "securite" | "appareils";

/** Sections connues : celles dont le dictionnaire donne le titre (`reglages.section.<id>.titre`). */
type IdSection = { [K in Cle]: K extends `reglages.section.${infer S}.titre` ? S : never }[Cle];

export interface Categorie {
  id: IdCategorie;
  /** Nom et description dans la langue courante. */
  readonly nom: string;
  readonly description: string;
}

export interface Section {
  id: string;
  categorie: IdCategorie;
  /** Titre et description dans la langue courante (dictionnaires de `src/i18n`). */
  readonly titre: string;
  readonly description: string;
  /** Mots de la recherche en plus du titre et de la description (synonymes, libellés des contrôles). */
  motsCles: readonly string[];
  /** Autres adresses qui mènent à cette section (`#reglages/<alias>`). */
  alias?: readonly string[];
}

interface SectionBrute {
  id: IdSection;
  categorie: IdCategorie;
  motsCles: readonly string[];
  alias?: readonly string[];
}

// Les textes vivent dans les dictionnaires : les getters les lisent dans la langue courante, à chaque affichage.
function versCategorie(id: IdCategorie): Categorie {
  return {
    id,
    get nom() {
      return t(`reglages.cat.${id}.nom`);
    },
    get description() {
      return t(`reglages.cat.${id}.description`);
    },
  };
}

function versSection(b: SectionBrute): Section {
  return {
    ...b,
    get titre() {
      return t(`reglages.section.${b.id}.titre`);
    },
    get description() {
      return t(`reglages.section.${b.id}.description`);
    },
  };
}

const IDS_CATEGORIES: readonly IdCategorie[] = [
  "ensemble",
  "apparence",
  "voix",
  "cerveau",
  "matin",
  "pc",
  "memoire",
  "securite",
  "appareils",
];

export const CATEGORIES: readonly Categorie[] = IDS_CATEGORIES.map(versCategorie);

const BRUTES: readonly SectionBrute[] = [
  {
    id: "apercu",
    categorie: "ensemble",
    motsCles: ["etat", "statut", "en ligne", "moteurs", "sante"],
  },
  {
    id: "rapides",
    categorie: "ensemble",
    motsCles: ["raccourcis", "basculer", "activer", "couper"],
  },
  {
    id: "langue",
    categorie: "apparence",
    motsCles: ["langue", "language", "francais", "anglais", "english", "french", "traduction", "translation"],
    alias: ["language", "langues"],
  },
  {
    id: "themes",
    categorie: "apparence",
    motsCles: ["apparence", "couleurs", "clair", "sombre", "nuit", "jour", "studio", "atelier", "console", "presence", "orbe"],
    alias: ["theme", "apparence-theme"],
  },
  {
    id: "presence",
    categorie: "apparence",
    motsCles: ["orbe", "particules", "fond d'ecran", "fond", "hud", "micro", "webgl"],
    alias: ["orbe", "fond-ecran"],
  },
  {
    id: "animations",
    categorie: "apparence",
    motsCles: ["mouvement", "reduire", "accessibilite", "effets", "fond", "aurore"],
  },
  {
    id: "clavier",
    categorie: "apparence",
    motsCles: ["raccourcis", "palette", "ctrl+k", "slash", "aide", "touches"],
    alias: ["raccourcis"],
  },
  {
    id: "pilotage",
    categorie: "apparence",
    motsCles: ["actions", "naviguer", "ouvrir", "automatique", "piloter", "interface", "propositions"],
  },
  {
    id: "commandes-rapides",
    categorie: "apparence",
    motsCles: ["phrases", "motifs", "jokers", "raccourcis", "sans ia", "automatisation", "declencheurs"],
    alias: ["commandes"],
  },
  {
    id: "lecture",
    categorie: "voix",
    motsCles: ["parole", "synthese", "parler", "lire", "son", "muet", "silence", "ctrl+m", "piper", "elevenlabs", "coupure", "stop"],
    alias: ["voix-jarvis"],
  },
  {
    id: "ecoute",
    categorie: "voix",
    motsCles: ["micro", "transcription", "whisper", "mains libres", "eveil", "dictee", "ecran", "vision"],
  },
  {
    id: "eveil",
    categorie: "voix",
    motsCles: ["dis jarvis", "mot d'eveil", "fond", "relance", "veille", "stop", "ambiance", "openwakeword", "juge"],
    alias: ["dis-jarvis", "ambiance"],
  },
  {
    id: "transcription",
    categorie: "voix",
    motsCles: ["whisper", "cuda", "rocm", "gpu", "carte graphique", "latence", "vad", "silero", "prechauffage", "hallucinations"],
  },
  {
    id: "proprietaire",
    categorie: "voix",
    motsCles: ["locuteur", "empreinte", "ecapa", "voix", "securite", "biometrie", "proprietaire"],
    alias: ["ma-voix"],
  },
  {
    id: "dictee",
    categorie: "voix",
    motsCles: ["dicter", "coller", "raccourci", "corrections", "dictionnaire", "windows", "presse-papiers"],
  },
  {
    id: "connecteurs",
    categorie: "cerveau",
    motsCles: ["ia", "moteurs", "modeles", "claude", "ollama", "api", "cle", "openai", "anthropic", "cerveau"],
    alias: ["cerveau-modeles", "modeles"],
  },
  {
    id: "couts",
    categorie: "cerveau",
    motsCles: ["argent", "depenses", "budget", "plafond", "limite", "abonnement", "jauge", "dollars"],
    alias: ["plafonds"],
  },
  {
    id: "routes",
    categorie: "cerveau",
    titre: "Routes par type de tâche",
    description: "Une IA pour le code, le raisonnement, les questions rapides et le privé ; scores et rétrogradations",
    motsCles: ["routeur", "route", "classifieur", "code", "raisonnement", "rapide", "prive", "score", "retrogradation", "modele"],
    alias: ["routeur"],
  },
  {
    id: "accueil-matin",
    categorie: "matin",
    motsCles: ["matin", "salutation", "meteo", "ville", "maison", "localisation", "lieu", "position", "rejouer"],
    alias: ["localisation"],
  },
  {
    id: "installation",
    categorie: "matin",
    motsCles: ["diagnostic", "verifications", "assistant", "premier lancement", "reparer", "prereglages"],
    alias: ["diagnostic"],
  },
  {
    id: "blocs-memoire",
    categorie: "memoire",
    motsCles: ["souvenirs", "blocs", "preferences", "noyau", "nuit", "embeddings", "prive"],
  },
  {
    id: "profil",
    categorie: "memoire",
    motsCles: ["questionnaire", "entretien", "moi", "qui je suis", "personnel"],
  },
  {
    id: "urgence",
    categorie: "securite",
    motsCles: ["stop", "arreter", "bloquer", "danger"],
  },
  {
    id: "cles-acces",
    categorie: "securite",
    motsCles: ["webauthn", "empreinte", "visage", "approuver", "rouge", "passkey"],
    alias: ["cles"],
  },
  {
    id: "donnees",
    categorie: "securite",
    motsCles: ["confidentialite", "vie privee", "flux", "cloud", "internet", "envoi", "images", "accord", "local", "rgpd"],
    alias: ["flux", "confidentialite", "vie-privee"],
  },
  {
    id: "audit",
    categorie: "securite",
    motsCles: ["journal", "historique des actions", "traces", "chaine"],
  },
  {
    id: "regles-protection",
    categorie: "securite",
    motsCles: ["regles", "interdire", "interdit", "demander avant", "garde-fous", "protection", "jamais"],
    alias: ["regles"],
  },
  {
    id: "autorisations",
    categorie: "securite",
    motsCles: ["toujours autoriser", "autorisation permanente", "confiance", "approbation", "retirer"],
    alias: ["toujours-autoriser"],
  },
  {
    id: "appareils",
    categorie: "appareils",
    motsCles: ["jumelage", "associer", "revoquer", "qr"],
  },
  {
    id: "telephone",
    categorie: "appareils",
    motsCles: ["mobile", "iphone", "android", "tailscale", "pwa", "distance"],
  },
  {
    id: "notifications",
    categorie: "appareils",
    motsCles: ["push", "notification", "web push", "decision", "approuver", "rappel", "plus tard", "telephone"],
    alias: ["push", "decision"],
  },
  {
    id: "envois",
    categorie: "appareils",
    motsCles: ["fichier", "lien", "telecharger", "usage unique", "envoyer", "transfert"],
    alias: ["fichiers", "liens"],
  },
  {
    id: "partages",
    categorie: "appareils",
    motsCles: ["partager", "partage", "share", "recu", "lien", "texte"],
  },
  {
    id: "bureau",
    categorie: "appareils",
    motsCles: ["raccourci", "clavier", "gadget", "widget", "protocole", "jarvis://", "voix", "ecran", "tauri"],
    alias: ["raccourcis-bureau", "gadget", "protocole"],
  },
  {
    id: "ressources-pc",
    categorie: "pc",
    motsCles: ["cpu", "ram", "gpu", "vram", "processeur", "memoire video", "carte graphique", "ollama", "ia locales", "decharger", "modele", "courbe", "alerte"],
    alias: ["ressources", "ollama", "ia-locales"],
  },
  {
    id: "mode-jeu",
    categorie: "pc",
    motsCles: ["jeu", "jeux", "veille", "veille stricte", "partie", "steam", "plein ecran", "silence"],
    alias: ["jeu", "veille-stricte"],
  },
  {
    id: "controle-pc",
    categorie: "pc",
    motsCles: ["volume", "son", "sourdine", "luminosite", "ecran", "musique", "media", "pause", "fenetres", "verrouiller", "eteindre", "extinction", "mode nuit", "concentration", "notifications", "plan d'alimentation", "windows"],
    alias: ["controle", "pc-controle", "windows"],
  },
  {
    id: "veille-claude",
    categorie: "appareils",
    motsCles: ["claude code", "sessions", "alerte", "notification", "permission", "vous attend", "terminal", "ateliers"],
    alias: ["veille", "sessions-claude"],
  },
  {
    id: "version",
    categorie: "appareils",
    motsCles: ["mise a jour", "numero", "a propos"],
  },
];

export const SECTIONS: readonly Section[] = BRUTES.map(versSection);

export function categorie(id: IdCategorie): Categorie {
  const trouvee = CATEGORIES.find((c) => c.id === id);
  if (!trouvee) throw new Error(`Catégorie inconnue : ${id}`);
  return trouvee;
}

export function sectionsDe(id: IdCategorie): Section[] {
  return SECTIONS.filter((s) => s.categorie === id);
}

/** Score d'une section pour la recherche (0 : écartée). Tous les mots doivent être trouvés. */
function score(s: Section, mots: string[]): number {
  const titre = normaliser(s.titre);
  // Dans la langue courante, et en français (les mots-clés le sont) : « thème » trouve aussi la section en anglais
  const enFrancais = (c: Cle) => traduire("fr", c);
  const id = s.id as IdSection;
  const reste = normaliser(
    [
      s.description,
      categorie(s.categorie).nom,
      enFrancais(`reglages.section.${id}.titre`),
      enFrancais(`reglages.section.${id}.description`),
      enFrancais(`reglages.cat.${s.categorie}.nom`),
      s.id,
      ...(s.alias ?? []),
      ...s.motsCles,
    ].join(" "),
  );
  let total = 0;
  for (const mot of mots) {
    if (titre.startsWith(mot)) total += 4;
    else if (titre.split(" ").some((m) => m.startsWith(mot))) total += 3;
    else if (titre.includes(mot)) total += 2;
    else if (reste.includes(mot)) total += 1;
    else return 0;
  }
  return total;
}

/** Recherche dans les titres, descriptions, catégories et mots-clés, sans tenir compte des accents. */
export function chercherSections(requete: string): Section[] {
  const mots = normaliser(requete).split(" ").filter(Boolean);
  if (!mots.length) return [];
  return SECTIONS.map((s, i) => ({ s, n: score(s, mots), i }))
    .filter((x) => x.n > 0)
    .sort((a, b) => b.n - a.n || a.i - b.i)
    .map((x) => x.s);
}

export interface Cible {
  categorie: IdCategorie;
  /** Section à montrer dans la catégorie (absente : le haut de la catégorie). */
  section?: string;
}

/** Une catégorie, une section ou un alias → où aller ; null si inconnu. */
export function resoudre(nom: string): Cible | null {
  const n = normaliser(nom);
  if (!n) return null;
  const cat = CATEGORIES.find((c) => c.id === n);
  if (cat) return { categorie: cat.id };
  const s = SECTIONS.find((x) => x.id === n) ?? SECTIONS.find((x) => x.alias?.includes(n));
  return s ? { categorie: s.categorie, section: s.id } : null;
}

const PREFIXE = "#reglages";

/** `#reglages` ou `#reglages/<nom>` → cible (null : autre adresse ; `#reglages` seul : `{}` sans catégorie). */
export function lireAdresse(hash: string): Cible | Record<string, never> | null {
  if (hash !== PREFIXE && !hash.startsWith(`${PREFIXE}/`)) return null;
  const nom = decodeURIComponent(hash.slice(PREFIXE.length + 1));
  return resoudre(nom) ?? {};
}

export function adresse(cible: Cible): string {
  return `${PREFIXE}/${cible.section ?? cible.categorie}`;
}

const CLE_CATEGORIE = "jarvis2.reglages.categorie";

/** Dernière catégorie ouverte sur cet appareil (vue d'ensemble par défaut). */
export function lireDerniereCategorie(): IdCategorie {
  try {
    const c = localStorage.getItem(CLE_CATEGORIE);
    if (CATEGORIES.some((x) => x.id === c)) return c as IdCategorie;
  } catch {
    /* stockage indisponible */
  }
  return "ensemble";
}

export function ecrireDerniereCategorie(id: IdCategorie): void {
  try {
    localStorage.setItem(CLE_CATEGORIE, id);
  } catch {
    /* stockage indisponible : la catégorie n'est pas retenue */
  }
}
