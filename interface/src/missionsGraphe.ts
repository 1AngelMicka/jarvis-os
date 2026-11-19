// Missions « projet » : lecture du plan Markdown à cases côté client, pour l'aperçu du graphe pendant la saisie.
// Mêmes règles que le Core (le Core reste la référence : c'est lui qui valide avant l'exécution) :
//   - [ ] E1 : Titre de l'étape
//     Détail facultatif sur les lignes indentées suivantes.
//   - [x] E2 : Autre étape (après E1)
// Erreurs : identifiant en double, dépendance inconnue, cycle, plus de 30 étapes.

/** Nombre d'étapes au plus dans un plan. */
export const MAX_ETAPES = 30;

export interface EtapeLue {
  id: string;
  titre: string;
  detail: string;
  apres: string[];
  /** Profondeur dans le graphe (0 = sans dépendance) : une colonne par niveau. */
  niveau: number;
  /** Case cochée : l'étape est déjà faite. */
  faite: boolean;
}

export interface PlanLu {
  etapes: EtapeLue[];
  /** Erreurs de lecture, en français (vide = exécutable). */
  erreurs: string[];
  faites: number;
  total: number;
}

// Case de premier niveau : « - [ ] E1 : Titre » (puce - * ou +, case vide ou cochée, deux-points ou tiret)
const CASE = /^\s*[-*+]\s+\[([ xX])\]\s+(E\d+)\s*[:\-–—]\s*(.*)$/;
// Dépendances en fin de ligne : « (après E1, E2) », « après » insensible à la casse, « apres » accepté
const APRES = /\(\s*apr[eè]s\s*:?\s*([^)]*)\)\s*$/i;

/** Lit le plan Markdown : étapes, dépendances, niveaux et erreurs. */
export function lirePlan(texte: string): PlanLu {
  const etapes: EtapeLue[] = [];
  const erreurs: string[] = [];
  let courante: { etape: EtapeLue; lignes: string[] } | null = null;

  const clore = () => {
    if (courante) courante.etape.detail = courante.lignes.join("\n").trim();
    courante = null;
  };

  for (const ligne of texte.replace(/\r\n?/g, "\n").split("\n")) {
    const c = CASE.exec(ligne);
    if (c) {
      clore();
      let titre = (c[3] ?? "").trim();
      let apres: string[] = [];
      const d = APRES.exec(titre);
      if (d) {
        apres = (d[1] ?? "")
          .split(/[,;]|\bet\b/)
          .map((x) => x.trim().toUpperCase())
          .filter((x) => x !== "");
        titre = titre.slice(0, d.index).trim();
      }
      const etape: EtapeLue = { id: (c[2] ?? "").toUpperCase(), titre, detail: "", apres: [...new Set(apres)], niveau: 0, faite: c[1] !== " " };
      etapes.push(etape);
      courante = { etape, lignes: [] };
      continue;
    }
    // Ligne indentée (ou vide) après une case : détail de l'étape ; toute autre ligne la clôt
    if (courante && (ligne.trim() === "" || /^\s+\S/.test(ligne))) {
      courante.lignes.push(ligne.trim());
    } else {
      clore();
    }
  }
  clore();

  // Identifiants en double
  const vus = new Set<string>();
  const doublons = new Set<string>();
  for (const e of etapes) {
    if (vus.has(e.id)) doublons.add(e.id);
    vus.add(e.id);
  }
  for (const id of doublons) erreurs.push(`Identifiant en double : ${id}.`);

  // Dépendances inconnues
  for (const e of etapes) {
    for (const dep of e.apres) {
      if (!vus.has(dep)) erreurs.push(`${e.id} dépend de ${dep}, qui n'existe pas.`);
    }
  }

  if (etapes.length > MAX_ETAPES) erreurs.push(`Trop d'étapes : ${String(etapes.length)} (${String(MAX_ETAPES)} au plus).`);

  // Niveaux (profondeur) et cycles : parcours en profondeur, la première occurrence d'un identifiant fait foi
  const parId = new Map<string, EtapeLue>();
  for (const e of etapes) if (!parId.has(e.id)) parId.set(e.id, e);
  const niveaux = new Map<string, number>();
  const pile: string[] = [];
  const cycles = new Set<string>();
  const profondeur = (id: string): number => {
    const connu = niveaux.get(id);
    if (connu !== undefined) return connu;
    const i = pile.indexOf(id);
    if (i >= 0) {
      const boucle = [...pile.slice(i), id];
      // Une seule mention par cycle, quel que soit son point d'entrée
      const cle = [...new Set(boucle)].sort().join(",");
      if (!cycles.has(cle)) {
        cycles.add(cle);
        erreurs.push(`Cycle de dépendances : ${boucle.join(" → ")}.`);
      }
      return 0;
    }
    const e = parId.get(id);
    if (!e) return 0;
    pile.push(id);
    let n = 0;
    for (const dep of e.apres) if (parId.has(dep)) n = Math.max(n, profondeur(dep) + 1);
    pile.pop();
    niveaux.set(id, n);
    return n;
  };
  for (const e of etapes) e.niveau = profondeur(e.id);

  return { etapes, erreurs, faites: etapes.filter((e) => e.faite).length, total: etapes.length };
}

/** Regroupe les étapes par niveau, dans l'ordre (colonne 0 d'abord) ; l'ordre du plan est gardé dans chaque colonne. */
export function grouperParNiveau<T extends { niveau: number }>(etapes: readonly T[]): T[][] {
  const colonnes = new Map<number, T[]>();
  for (const e of etapes) {
    const n = Number.isFinite(e.niveau) && e.niveau > 0 ? Math.floor(e.niveau) : 0;
    const col = colonnes.get(n);
    if (col) col.push(e);
    else colonnes.set(n, [e]);
  }
  return [...colonnes.entries()].sort((a, b) => a[0] - b[0]).map(([, col]) => col);
}
