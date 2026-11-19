// Bureau et téléphone (lot M) : liens jarvis:// reçus de l'application de bureau, appel de décision, contenus
// partagés depuis le téléphone, gadget de bureau. Ici, seulement la lecture des adresses et les événements ;
// la vérification (liste blanche) est faite par l'application de bureau PUIS par le Core.

/** Ouvre le micro (raccourci global « voix », lien jarvis://ecouter). */
export const EVENEMENT_ECOUTER = "jarvis2:ecouter";
/** Lance « regarde mon écran » : à émettre depuis un clic (le navigateur exige un geste pour partager l'écran). */
export const EVENEMENT_ECRAN = "jarvis2:ecran";
/** Préremplit la zone de saisie (texte venu d'un lien : non fiable, jamais envoyé seul). Détail : le texte. */
export const EVENEMENT_PREREMPLIR = "jarvis2:preremplir";

// Une demande reste en attente jusqu'à ce qu'un composant la prenne : au premier chargement, la saisie et le micro
// ne sont pas encore montés quand le lien arrive ; ils la prennent en se montant.
const enAttente = new Map<string, string>();

export function emettre(evenement: string, detail?: string): void {
  enAttente.set(evenement, detail ?? "");
  window.dispatchEvent(new CustomEvent(evenement, { detail }));
}

/** Prend la demande en attente pour cet événement (une seule fois), sinon null. */
export function prendre(evenement: string): string | null {
  const valeur = enAttente.get(evenement);
  enAttente.delete(evenement);
  return valeur ?? null;
}

function fragment(hash: string, cle: string): string | null {
  const brut = hash.startsWith("#") ? hash.slice(1) : hash;
  if (!brut.startsWith(`${cle}=`)) return null;
  try {
    const valeur = decodeURIComponent(brut.slice(cle.length + 1));
    return valeur || null;
  } catch {
    return null;
  }
}

/** `#jarvis=<lien encodé>` (mis par l'application de bureau) → le lien jarvis://, sinon null. */
export function lireLien(hash: string): string | null {
  const lien = fragment(hash, "jarvis");
  return lien && /^jarvis:\/\//i.test(lien) && lien.length <= 2048 ? lien : null;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** `#decision=<id>` (notification poussée au téléphone) → identifiant de la demande, sinon null. */
export function lireDecision(hash: string): string | null {
  const id = fragment(hash, "decision");
  return id && UUID.test(id) ? id.toLowerCase() : null;
}

export interface PartageRecu {
  titre: string;
  texte: string;
  url: string;
}

/** « Partager vers JARVIS » (Web Share Target) : `/?partage_titre=…&partage_texte=…&partage_url=…`. */
export function lirePartage(recherche: string): PartageRecu | null {
  const p = new URLSearchParams(recherche);
  const titre = p.get("partage_titre") ?? "";
  const texte = p.get("partage_texte") ?? "";
  const url = p.get("partage_url") ?? "";
  if (!p.has("partage_titre") && !p.has("partage_texte") && !p.has("partage_url")) return null;
  return { titre: titre.slice(0, 1000), texte: texte.slice(0, 40000), url: url.slice(0, 4000) };
}

/** Gadget de bureau : petite fenêtre ouverte par l'application sur `/?mode=gadget`. */
export function estGadget(recherche: string): boolean {
  return new URLSearchParams(recherche).get("mode") === "gadget";
}

/** Retire de l'adresse ce qui vient d'être lu (lien, décision, partage) : un rechargement ne le rejoue pas. */
export function nettoyerAdresse(): void {
  const p = new URLSearchParams(window.location.search);
  for (const cle of ["partage_titre", "partage_texte", "partage_url"]) p.delete(cle);
  const reste = p.toString();
  history.replaceState(null, "", window.location.pathname + (reste ? `?${reste}` : ""));
}

// --- Notifications Web Push --------------------------------------------------------------------------------

export function pushPossible(): boolean {
  return window.isSecureContext && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

/** Clé publique VAPID (base64url) → octets attendus par `pushManager.subscribe`. */
export function cleServeur(base64url: string): Uint8Array<ArrayBuffer> {
  const b64 = base64url.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (base64url.length % 4)) % 4);
  const brut = atob(b64);
  const octets = new Uint8Array(new ArrayBuffer(brut.length));
  for (let i = 0; i < brut.length; i++) octets[i] = brut.charCodeAt(i);
  return octets;
}

/** Taille lisible d'un fichier. */
export function taille(octets: number): string {
  if (octets < 1024) return `${String(octets)} o`;
  if (octets < 1024 * 1024) return `${(octets / 1024).toFixed(0)} Ko`;
  return `${(octets / (1024 * 1024)).toFixed(1).replace(".", ",")} Mo`;
}
