// Registre de la vue Réglages : catégories, sections, recherche et adresses directes (`#reglages/<catégorie ou
// section>`). Une seule liste, pour que la navigation, la recherche et les liens disent toujours la même chose.
// Chaque nouvelle fonctionnalité réglable déclare ici sa section.

import { normaliser } from "./commandes";

export type IdCategorie = "ensemble" | "apparence" | "voix" | "cerveau" | "matin" | "pc" | "memoire" | "securite" | "appareils";

export interface Categorie {
  id: IdCategorie;
  nom: string;
  description: string;
}

export interface Section {
  id: string;
  categorie: IdCategorie;
  titre: string;
  description: string;
  /** Mots de la recherche en plus du titre et de la description (synonymes, libellés des contrôles). */
  motsCles: readonly string[];
  /** Autres adresses qui mènent à cette section (`#reglages/<alias>`). */
  alias?: readonly string[];
}

export const CATEGORIES: readonly Categorie[] = [
  { id: "ensemble", nom: "Vue d'ensemble", description: "État des systèmes et interrupteurs rapides" },
  { id: "apparence", nom: "Interface & apparence", description: "Thème, animations, clavier" },
  { id: "voix", nom: "Voix & écoute", description: "Lecture à voix haute, dictée, mains libres" },
  { id: "cerveau", nom: "Cerveau & coûts", description: "Vos IA, modèles, dépenses et plafonds" },
  { id: "matin", nom: "Accueil & localisation", description: "Accueil du matin, maison, installation" },
  { id: "pc", nom: "PC & mode jeu", description: "Ressources, IA locales, mode jeu, contrôle de Windows" },
  { id: "memoire", nom: "Mémoire & profil", description: "Blocs toujours donnés à JARVIS, tâches de nuit, profil" },
  { id: "securite", nom: "Sécurité", description: "Arrêt d'urgence, clés d'accès, données, audit" },
  { id: "appareils", nom: "Appareils", description: "Appareils autorisés, téléphone, version et mises à jour" },
];

export const SECTIONS: readonly Section[] = [
  {
    id: "apercu",
    categorie: "ensemble",
    titre: "État des systèmes",
    description: "Core, mémoire, IA disponibles, demandes en attente",
    motsCles: ["etat", "statut", "en ligne", "moteurs", "sante"],
  },
  {
    id: "rapides",
    categorie: "ensemble",
    titre: "Interrupteurs rapides",
    description: "Voix, thème et animations en un geste",
    motsCles: ["raccourcis", "basculer", "activer", "couper"],
  },
  {
    id: "themes",
    categorie: "apparence",
    titre: "Thème",
    description: "JARVIS, Studio nocturne, Atelier clair, Console épurée, Présence",
    motsCles: ["apparence", "couleurs", "clair", "sombre", "nuit", "jour", "studio", "atelier", "console", "presence", "orbe"],
    alias: ["theme", "apparence-theme"],
  },
  {
    id: "presence",
    categorie: "apparence",
    titre: "Présence",
    description: "Orbe de particules : HUD en fond d'écran, niveau du micro",
    motsCles: ["orbe", "particules", "fond d'ecran", "fond", "hud", "micro", "webgl"],
    alias: ["orbe", "fond-ecran"],
  },
  {
    id: "animations",
    categorie: "apparence",
    titre: "Animations",
    description: "Mouvements du fond et des panneaux, selon le système ou réduits",
    motsCles: ["mouvement", "reduire", "accessibilite", "effets", "fond", "aurore"],
  },
  {
    id: "clavier",
    categorie: "apparence",
    titre: "Clavier et commandes",
    description: "Palette Ctrl+K, commandes « / », raccourcis",
    motsCles: ["raccourcis", "palette", "ctrl+k", "slash", "aide", "touches"],
    alias: ["raccourcis"],
  },
  {
    id: "pilotage",
    categorie: "apparence",
    titre: "Pilotage par JARVIS",
    description: "JARVIS ouvre une vue ou un élément quand vous le lui demandez ; les lancements restent des propositions",
    motsCles: ["actions", "naviguer", "ouvrir", "automatique", "piloter", "interface", "propositions"],
  },
  {
    id: "commandes-rapides",
    categorie: "apparence",
    titre: "Commandes rapides",
    description: "Une phrase reconnue sans IA déclenche une action (motif avec jokers, priorité, phrase de test)",
    motsCles: ["phrases", "motifs", "jokers", "raccourcis", "sans ia", "automatisation", "declencheurs"],
    alias: ["commandes"],
  },
  {
    id: "lecture",
    categorie: "voix",
    titre: "Voix de JARVIS",
    description: "Lecture à voix haute : voix de l'appareil, Piper (locale) ou ElevenLabs ; coupure quand on parle par-dessus",
    motsCles: ["parole", "synthese", "parler", "lire", "son", "muet", "silence", "ctrl+m", "piper", "elevenlabs", "coupure", "stop"],
    alias: ["voix-jarvis"],
  },
  {
    id: "ecoute",
    categorie: "voix",
    titre: "Écoute et dictée",
    description: "Dictée, mains libres « Jarvis, … », écran décrit sur demande",
    motsCles: ["micro", "transcription", "whisper", "mains libres", "eveil", "dictee", "ecran", "vision"],
  },
  {
    id: "eveil",
    categorie: "voix",
    titre: "Éveil « Dis Jarvis »",
    description: "Écoute en fond, relance sans « Jarvis », commandes stop et silence, mémoire d'ambiance",
    motsCles: ["dis jarvis", "mot d'eveil", "fond", "relance", "veille", "stop", "ambiance", "openwakeword", "juge"],
    alias: ["dis-jarvis", "ambiance"],
  },
  {
    id: "transcription",
    categorie: "voix",
    titre: "Transcription",
    description: "Modèle Whisper, carte graphique ou processeur, préchauffage, fin de tour",
    motsCles: ["whisper", "cuda", "rocm", "gpu", "carte graphique", "latence", "vad", "silero", "prechauffage", "hallucinations"],
  },
  {
    id: "proprietaire",
    categorie: "voix",
    titre: "Reconnaissance de ma voix",
    description: "Vérifier que c'est vous avant une action 🟡🔴 demandée à voix haute",
    motsCles: ["locuteur", "empreinte", "ecapa", "voix", "securite", "biometrie", "proprietaire"],
    alias: ["ma-voix"],
  },
  {
    id: "dictee",
    categorie: "voix",
    titre: "Dictée globale",
    description: "Maintenir Ctrl+Alt+D pour dicter dans n'importe quelle application",
    motsCles: ["dicter", "coller", "raccourci", "corrections", "dictionnaire", "windows", "presse-papiers"],
  },
  {
    id: "connecteurs",
    categorie: "cerveau",
    titre: "Connecteurs",
    description: "Vos IA : compte Claude, clés d'API, modèles locaux",
    motsCles: ["ia", "moteurs", "modeles", "claude", "ollama", "api", "cle", "openai", "anthropic", "cerveau"],
    alias: ["cerveau-modeles", "modeles"],
  },
  {
    id: "couts",
    categorie: "cerveau",
    titre: "Coûts et plafonds",
    description: "Dépenses du jour et du mois, plafond par connecteur, jauges d'abonnement",
    motsCles: ["argent", "depenses", "budget", "plafond", "limite", "abonnement", "jauge", "dollars"],
    alias: ["plafonds"],
  },
  {
    id: "accueil-matin",
    categorie: "matin",
    titre: "Accueil du matin et maison",
    description: "Parlé, texte seul ou désactivé ; lieu de la météo (privé)",
    motsCles: ["matin", "salutation", "meteo", "ville", "maison", "localisation", "lieu", "position", "rejouer"],
    alias: ["localisation"],
  },
  {
    id: "installation",
    categorie: "matin",
    titre: "Installation",
    description: "Diagnostic du premier lancement, réparations, préréglages",
    motsCles: ["diagnostic", "verifications", "assistant", "premier lancement", "reparer", "prereglages"],
    alias: ["diagnostic"],
  },
  {
    id: "blocs-memoire",
    categorie: "memoire",
    titre: "Mémoire",
    description: "Blocs toujours donnés à JARVIS, modèle d'embeddings, tâches de nuit",
    motsCles: ["souvenirs", "blocs", "preferences", "noyau", "nuit", "embeddings", "prive"],
  },
  {
    id: "profil",
    categorie: "memoire",
    titre: "Profil",
    description: "Questionnaire guidé par sections, réponses gardées en mémoire",
    motsCles: ["questionnaire", "entretien", "moi", "qui je suis", "personnel"],
  },
  {
    id: "urgence",
    categorie: "securite",
    titre: "Arrêt d'urgence",
    description: "Tout arrêter tout de suite ; la levée demande une clé d'accès",
    motsCles: ["stop", "arreter", "bloquer", "danger"],
  },
  {
    id: "cles-acces",
    categorie: "securite",
    titre: "Clés d'accès",
    description: "Empreinte, visage ou code de l'appareil pour approuver les actions 🔴",
    motsCles: ["webauthn", "empreinte", "visage", "approuver", "rouge", "passkey"],
    alias: ["cles"],
  },
  {
    id: "donnees",
    categorie: "securite",
    titre: "Où partent mes données",
    description: "Chaque fonction : service contacté, ce qui part, local ou non, où le couper ; accord images",
    motsCles: ["confidentialite", "vie privee", "flux", "cloud", "internet", "envoi", "images", "accord", "local", "rgpd"],
    alias: ["flux", "confidentialite", "vie-privee"],
  },
  {
    id: "audit",
    categorie: "securite",
    titre: "Journal d'audit",
    description: "Toutes les actions, chaînées par empreintes",
    motsCles: ["journal", "historique des actions", "traces", "chaine"],
  },
  {
    id: "regles-protection",
    categorie: "securite",
    titre: "Règles de protection",
    description: "« Ne touche jamais à… », « demande-moi avant… » : appliquées par le Core à chaque action",
    motsCles: ["regles", "interdire", "interdit", "demander avant", "garde-fous", "protection", "jamais"],
    alias: ["regles"],
  },
  {
    id: "autorisations",
    categorie: "securite",
    titre: "Toujours autorisé",
    description: "Actions 🟡 que vous avez choisi de ne plus approuver à chaque fois",
    motsCles: ["toujours autoriser", "autorisation permanente", "confiance", "approbation", "retirer"],
    alias: ["toujours-autoriser"],
  },
  {
    id: "appareils",
    categorie: "appareils",
    titre: "Appareils autorisés",
    description: "Associer, voir et révoquer les appareils",
    motsCles: ["jumelage", "associer", "revoquer", "qr"],
  },
  {
    id: "telephone",
    categorie: "appareils",
    titre: "Téléphone",
    description: "JARVIS hors de chez vous par Tailscale, installation sur l'écran d'accueil",
    motsCles: ["mobile", "iphone", "android", "tailscale", "pwa", "distance"],
  },
  {
    id: "notifications",
    categorie: "appareils",
    titre: "Notifications et appel de décision",
    description: "Recevoir sur cet appareil les demandes 🟡🔴 : oui, non ou plus tard",
    motsCles: ["push", "notification", "web push", "decision", "approuver", "rappel", "plus tard", "telephone"],
    alias: ["push", "decision"],
  },
  {
    id: "envois",
    categorie: "appareils",
    titre: "Envoyer un fichier au téléphone",
    description: "Lien à usage unique, valable quelques minutes",
    motsCles: ["fichier", "lien", "telecharger", "usage unique", "envoyer", "transfert"],
    alias: ["fichiers", "liens"],
  },
  {
    id: "partages",
    categorie: "appareils",
    titre: "Reçu par « Partager vers JARVIS »",
    description: "Textes et liens envoyés depuis le téléphone (toujours non fiables)",
    motsCles: ["partager", "partage", "share", "recu", "lien", "texte"],
  },
  {
    id: "bureau",
    categorie: "appareils",
    titre: "Bureau : raccourcis, gadget, liens jarvis://",
    description: "Raccourcis globaux de l'application de bureau et protocole jarvis://",
    motsCles: ["raccourci", "clavier", "gadget", "widget", "protocole", "jarvis://", "voix", "ecran", "tauri"],
    alias: ["raccourcis-bureau", "gadget", "protocole"],
  },
  {
    id: "ressources-pc",
    categorie: "pc",
    titre: "Ressources du PC",
    description: "Processeur, mémoire vive, carte graphique, mémoire vidéo ; Ollama à la demande",
    motsCles: ["cpu", "ram", "gpu", "vram", "processeur", "memoire video", "carte graphique", "ollama", "ia locales", "decharger", "modele", "courbe", "alerte"],
    alias: ["ressources", "ollama", "ia-locales"],
  },
  {
    id: "mode-jeu",
    categorie: "pc",
    titre: "Mode jeu",
    description: "Veille stricte pendant une partie : automatique, forcée ou jamais",
    motsCles: ["jeu", "jeux", "veille", "veille stricte", "partie", "steam", "plein ecran", "silence"],
    alias: ["jeu", "veille-stricte"],
  },
  {
    id: "controle-pc",
    categorie: "pc",
    titre: "Contrôle du PC",
    description: "Volume, luminosité, média en cours, fenêtres, modes de Windows, verrouillage, extinction",
    motsCles: ["volume", "son", "sourdine", "luminosite", "ecran", "musique", "media", "pause", "fenetres", "verrouiller", "eteindre", "extinction", "mode nuit", "concentration", "notifications", "plan d'alimentation", "windows"],
    alias: ["controle", "pc-controle", "windows"],
  },
  {
    id: "veille-claude",
    categorie: "appareils",
    titre: "Veille de vos sessions Claude Code",
    description: "Être prévenu quand une session vous attend ou attend une permission (lecture seule)",
    motsCles: ["claude code", "sessions", "alerte", "notification", "permission", "vous attend", "terminal", "ateliers"],
    alias: ["veille", "sessions-claude"],
  },
  {
    id: "version",
    categorie: "appareils",
    titre: "Version et mises à jour",
    description: "Version du Core, nouvelle version disponible, vérification quotidienne",
    motsCles: ["mise a jour", "mises a jour", "mettre a jour", "nouvelle version", "version", "numero", "a propos", "github", "notes de version"],
    alias: ["mises-a-jour", "mise-a-jour"],
  },
];

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
  const reste = normaliser([s.description, categorie(s.categorie).nom, s.id, ...(s.alias ?? []), ...s.motsCles].join(" "));
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
