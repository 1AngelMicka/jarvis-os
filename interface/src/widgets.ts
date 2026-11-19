// Widgets générés à la demande (phase 14, D 16). Le Core valide et réécrit le fragment (core/jarvis2/widgets.py) ;
// l'interface le filtre ENCORE par DOMPurify avec les mêmes listes fermées (balises, attributs, classes, adresses),
// refuse le widget entier au moindre retrait, puis construit le rendu avec React à partir de l'arbre filtré : jamais
// d'innerHTML. Aucun script, aucun style en ligne, aucun gestionnaire d'événement, aucune adresse externe.

import DOMPurify from "dompurify";

import { appeler, envoyer } from "./api";

export interface Widget {
  id: string; // empreinte du Core (titre + fragment)
  titre: string;
  html: string;
}

export interface WidgetEpingle extends Widget {
  /** Identifiant de la ligne épinglée (le `id` d'un Widget est son empreinte). */
  empreinte: string;
  cree_le: string;
}

// --- Listes fermées (mêmes listes que le Core) -------------------------------------------------------------------

export const BALISES: readonly string[] = [
  "div", "section", "p", "span", "strong", "em", "small", "br",
  "h3", "h4", "ul", "ol", "li",
  "table", "thead", "tbody", "tr", "th", "td",
  "time", "meter", "progress", "a",
];

const NOMBRE = /^-?\d{1,9}(?:\.\d{1,3})?$/;
const LIBRE = /^[^<>"`]{0,120}$/;

/** Attribut → balises où il est permis (null : toutes) et forme exigée de la valeur. */
export const ATTRIBUTS: Readonly<Record<string, { balises: readonly string[] | null; forme: RegExp }>> = {
  class: { balises: null, forme: /^[a-z0-9 -]{0,200}$/ },
  title: { balises: null, forme: LIBRE },
  "aria-label": { balises: null, forme: LIBRE },
  href: { balises: ["a"], forme: /^#[a-z][a-z0-9/-]{0,60}$/ },
  datetime: { balises: ["time"], forme: /^[0-9T:+\-Z. ]{4,40}$/ },
  "data-minuteur": { balises: ["time"], forme: /^[1-9]\d{0,5}$/ },
  value: { balises: ["meter", "progress"], forme: NOMBRE },
  min: { balises: ["meter"], forme: NOMBRE },
  max: { balises: ["meter", "progress"], forme: NOMBRE },
  low: { balises: ["meter"], forme: NOMBRE },
  high: { balises: ["meter"], forme: NOMBRE },
  colspan: { balises: ["td", "th"], forme: /^[1-9]$/ },
};

/** Classes permises : chacune est définie dans styles/widgets.css avec les tokens de DESIGN.md. */
export const CLASSES: ReadonlySet<string> = new Set([
  "w-carte", "w-grille", "w-ligne", "w-pile",
  "w-titre", "w-valeur", "w-geant", "w-libelle", "w-unite", "w-icone", "w-mono", "w-discret",
  "w-accent", "w-succes", "w-attention", "w-danger",
  "w-liste", "w-coche", "w-minuteur", "w-jauge",
]);

/** Vues internes vers lesquelles un lien de widget peut mener (mêmes que `VUES` du Core). */
export const VUES_LIENS: ReadonlySet<string> = new Set([
  "dialogue", "historique", "activite", "demandes", "securite", "memoire", "connaissances",
  "agents", "ateliers", "ameliorations", "connecteurs", "couts", "reglages", "accueil",
]);

/** Vrai si l'attribut `nom` de valeur `valeur` est permis sur `balise` (forme, classes, adresse interne). */
export function attributPermis(balise: string, nom: string, valeur: string): boolean {
  const regle = ATTRIBUTS[nom];
  if (!regle) return false;
  if (regle.balises && !regle.balises.includes(balise)) return false;
  const v = valeur.trim();
  if (!regle.forme.test(v)) return false;
  if (nom === "class") return v.split(/\s+/).filter(Boolean).every((c) => CLASSES.has(c));
  if (nom === "href") return VUES_LIENS.has(v.slice(1).split("/")[0] ?? "");
  return true;
}

// --- Filtre DOMPurify ----------------------------------------------------------------------------------------------

export type Filtrage = { ok: true; fragment: DocumentFragment } | { ok: false; raison: string };

const CONFIG = {
  ALLOWED_TAGS: [...BALISES],
  ALLOWED_ATTR: Object.keys(ATTRIBUTS),
  ALLOW_DATA_ATTR: false,
  ALLOW_ARIA_ATTR: false,
  ALLOW_UNKNOWN_PROTOCOLS: false,
  ALLOWED_URI_REGEXP: /^#[a-z]/,
  KEEP_CONTENT: false,
  WHOLE_DOCUMENT: false,
  RETURN_DOM_FRAGMENT: true as const,
};

const etat: { refus: string | null } = { refus: null };
// Lu par une fonction : le crochet écrit `etat.refus` pendant `sanitize`, TypeScript ne le voit pas
const refusDuCrochet = (): string | null => etat.refus;
let crocheteInstalle = false;

function installerCrochet(): void {
  if (crocheteInstalle) return;
  crocheteInstalle = true;
  // Au-delà de la liste des noms d'attributs : forme de la valeur, classes connues, adresse interne seulement
  DOMPurify.addHook("uponSanitizeAttribute", (noeud, donnees) => {
    const balise = noeud.nodeName.toLowerCase();
    if (!attributPermis(balise, donnees.attrName, donnees.attrValue)) {
      etat.refus ??= `attribut refusé : ${donnees.attrName.slice(0, 30)}`;
      donnees.keepAttr = false;
    }
  });
}

/** Filtre un fragment ; le moindre élément ou attribut retiré refuse le widget entier (jamais de « réparation »). */
export function filtrer(html: string): Filtrage {
  if (typeof window === "undefined" || !DOMPurify.isSupported) return { ok: false, raison: "filtre indisponible" };
  if (!html.trim()) return { ok: false, raison: "fragment vide" };
  if (html.length > 8000) return { ok: false, raison: "fragment trop long" };
  installerCrochet();
  etat.refus = null;
  const fragment = DOMPurify.sanitize(html, CONFIG);
  const retires = DOMPurify.removed;
  const refus = refusDuCrochet();
  if (refus) return { ok: false, raison: refus };
  if (retires.length) {
    const premier = retires[0] as { element?: Node; attribute?: Attr | null } | undefined;
    const nom = premier?.attribute?.name ?? premier?.element?.nodeName.toLowerCase() ?? "?";
    return { ok: false, raison: `élément refusé : ${nom.slice(0, 30)}` };
  }
  return { ok: true, fragment };
}

// --- Minuteur ------------------------------------------------------------------------------------------------------

/** « 4:00 », « 1:02:03 ». */
export function formaterDuree(secondes: number): string {
  const s = Math.max(0, Math.round(secondes));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = String(s % 60).padStart(2, "0");
  return h ? `${String(h)}:${String(m).padStart(2, "0")}:${r}` : `${String(m)}:${r}`;
}

// --- API -----------------------------------------------------------------------------------------------------------

export const listerWidgets = () => appeler<{ widgets: WidgetEpingle[] }>("/v1/widgets");
export const epinglerWidget = (w: Pick<Widget, "titre" | "html">) =>
  envoyer<{ widget: WidgetEpingle; nouveau: boolean }>("/v1/widgets", { titre: w.titre, html: w.html });
export const retirerWidget = (id: string) => appeler<{ retire: string }>(`/v1/widgets/${encodeURIComponent(id)}`, { methode: "DELETE" });
