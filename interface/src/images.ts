// Images jointes au dialogue : préparées dans le navigateur avant l'envoi (rien ne part avant « Envoyer »).
// Règles : JPEG, PNG, WebP, GIF ; 5 par message ; au-delà de 1 600 px ou 1 Mo, réduite et recompressée (JPEG ou WebP
// à 85 %) ; GIF jamais redimensionné (l'animation serait perdue), refusé au-delà de 3 Mo. Le Core ne les garde pas.

export const TYPES_ACCEPTES = ["image/jpeg", "image/png", "image/webp", "image/gif"] as const;
export type TypeImage = (typeof TYPES_ACCEPTES)[number];
export const NB_MAX_IMAGES = 5;
export const COTE_MAX = 1600;
export const POIDS_CIBLE = 1024 * 1024;
export const POIDS_MAX = 3 * 1024 * 1024; // même limite que le Core
export const QUALITE = 0.85;

export interface ImageJointe {
  id: string;
  nom: string;
  type: TypeImage;
  dataUrl: string;
  poids: number;
}

export type Plan =
  | { action: "garder" }
  | { action: "refuser"; raison: string }
  | { action: "compresser"; largeur: number; hauteur: number; type: "image/jpeg" | "image/webp" };

export function estTypeAccepte(type: string): type is TypeImage {
  return (TYPES_ACCEPTES as readonly string[]).includes(type);
}

/** Dimensions réduites pour tenir dans `cote` × `cote`, proportions gardées (jamais agrandies). */
export function dimensionsCible(largeur: number, hauteur: number, cote = COTE_MAX): { largeur: number; hauteur: number } {
  const plusGrand = Math.max(largeur, hauteur);
  if (plusGrand <= cote) return { largeur, hauteur };
  const k = cote / plusGrand;
  return { largeur: Math.max(1, Math.round(largeur * k)), hauteur: Math.max(1, Math.round(hauteur * k)) };
}

export function poidsLisible(octets: number): string {
  if (octets < 1024) return `${String(octets)} o`;
  if (octets < 1024 * 1024) return `${String(Math.round(octets / 1024))} Ko`;
  return `${(octets / (1024 * 1024)).toFixed(1).replace(".", ",")} Mo`;
}

/** Que faire de cette image ? (décision pure, testée) */
export function planifier(type: string, poids: number, largeur: number, hauteur: number): Plan {
  if (!estTypeAccepte(type)) return { action: "refuser", raison: "format non pris en charge (JPEG, PNG, WebP ou GIF)" };
  if (type === "image/gif") {
    return poids > POIDS_MAX ? { action: "refuser", raison: `GIF trop lourd (${poidsLisible(poids)}, 3 Mo au plus)` } : { action: "garder" };
  }
  if (Math.max(largeur, hauteur) <= COTE_MAX && poids <= POIDS_CIBLE) return { action: "garder" };
  // PNG (souvent une capture, parfois transparente) : WebP garde la transparence ; JPEG reste JPEG
  return { action: "compresser", ...dimensionsCible(largeur, hauteur), type: type === "image/jpeg" ? "image/jpeg" : "image/webp" };
}

/** Combien d'images peuvent encore être jointes à ce message. */
export function places(dejaJointes: number): number {
  return Math.max(0, NB_MAX_IMAGES - dejaJointes);
}

/** Outils du navigateur, remplaçables dans les tests. */
export interface Outils {
  dimensions: (fichier: Blob) => Promise<{ largeur: number; hauteur: number }>;
  /** Redessine l'image aux dimensions données ; le type rendu peut différer (WebP non pris en charge → PNG). */
  encoder: (fichier: Blob, largeur: number, hauteur: number, type: string, qualite: number) => Promise<Blob>;
  dataUrl: (blob: Blob) => Promise<string>;
}

let compteur = 0;

export class ErreurImage extends Error {}

/** Prépare un fichier pour l'envoi (compression si besoin) ; lève `ErreurImage` avec un message affichable. */
export async function preparerImage(fichier: File, outils: Outils = outilsNavigateur): Promise<ImageJointe> {
  const nom = fichier.name || "image";
  if (!estTypeAccepte(fichier.type)) throw new ErreurImage(`${nom} : format non pris en charge (JPEG, PNG, WebP ou GIF).`);
  let dims = { largeur: 0, hauteur: 0 };
  if (fichier.type !== "image/gif") {
    try {
      dims = await outils.dimensions(fichier);
    } catch {
      throw new ErreurImage(`${nom} : image illisible.`);
    }
  }
  const plan = planifier(fichier.type, fichier.size, dims.largeur, dims.hauteur);
  if (plan.action === "refuser") throw new ErreurImage(`${nom} : ${plan.raison}.`);
  let blob: Blob = fichier;
  let type: TypeImage = fichier.type;
  if (plan.action === "compresser") {
    let rendu = await outils.encoder(fichier, plan.largeur, plan.hauteur, plan.type, QUALITE);
    // Navigateur sans encodeur WebP (il rend du PNG) : JPEG à la place
    if (rendu.type !== plan.type) rendu = await outils.encoder(fichier, plan.largeur, plan.hauteur, "image/jpeg", QUALITE);
    if (!estTypeAccepte(rendu.type)) throw new ErreurImage(`${nom} : compression impossible dans ce navigateur.`);
    // Une recompression plus lourde que l'original n'a pas d'intérêt si l'original tient dans les limites
    if (rendu.size < fichier.size || Math.max(dims.largeur, dims.hauteur) > COTE_MAX) {
      blob = rendu;
      type = rendu.type;
    }
  }
  if (blob.size > POIDS_MAX) throw new ErreurImage(`${nom} : trop lourde même compressée (${poidsLisible(blob.size)}, 3 Mo au plus).`);
  return { id: `img${String(++compteur)}`, nom, type, dataUrl: await outils.dataUrl(blob), poids: blob.size };
}

/** Fichiers images d'un collage ou d'un dépôt (les autres sont ignorés, mais comptés pour le dire). */
export function imagesDe(fichiers: Iterable<File>): { images: File[]; ignores: number } {
  const images: File[] = [];
  let ignores = 0;
  for (const f of fichiers) {
    if (f.type.startsWith("image/")) images.push(f);
    else ignores++;
  }
  return { images, ignores };
}

export const outilsNavigateur: Outils = {
  async dimensions(fichier) {
    const bitmap = await createImageBitmap(fichier);
    const d = { largeur: bitmap.width, hauteur: bitmap.height };
    bitmap.close();
    return d;
  },
  async encoder(fichier, largeur, hauteur, type, qualite) {
    const bitmap = await createImageBitmap(fichier, { resizeWidth: largeur, resizeHeight: hauteur, resizeQuality: "high" });
    const toile = document.createElement("canvas");
    toile.width = largeur;
    toile.height = hauteur;
    const ctx = toile.getContext("2d");
    if (!ctx) throw new ErreurImage("Compression impossible dans ce navigateur.");
    if (type === "image/jpeg") {
      // JPEG sans transparence : fond blanc plutôt que noir
      ctx.fillStyle = "#fff";
      ctx.fillRect(0, 0, largeur, hauteur);
    }
    ctx.drawImage(bitmap, 0, 0, largeur, hauteur);
    bitmap.close();
    return new Promise<Blob>((resoudre, rejeter) => {
      toile.toBlob(
        (b) => {
          if (b) resoudre(b);
          else rejeter(new ErreurImage("Compression impossible dans ce navigateur."));
        },
        type,
        qualite,
      );
    });
  },
  dataUrl(blob) {
    return new Promise<string>((resoudre, rejeter) => {
      const lecteur = new FileReader();
      lecteur.onload = () => {
        if (typeof lecteur.result === "string") resoudre(lecteur.result);
        else rejeter(new ErreurImage("Lecture de l'image impossible."));
      };
      lecteur.onerror = () => {
        rejeter(new ErreurImage("Lecture de l'image impossible."));
      };
      lecteur.readAsDataURL(blob);
    });
  },
};
