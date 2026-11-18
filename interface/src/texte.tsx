// Rendu Markdown minimal en nœuds React : jamais de HTML brut (DESIGN.md, règle 2).
// Blocs : code ```, titres #, listes - / 1., paragraphes. En ligne : `code`, **gras**, *italique*, [lien](https://…).

import type { ReactNode } from "react";

type Bloc =
  | { type: "code"; langue: string; texte: string }
  | { type: "titre"; niveau: number; texte: string }
  | { type: "liste"; ordonnee: boolean; items: string[] }
  | { type: "paragraphe"; texte: string };

export function decouperBlocs(source: string): Bloc[] {
  const lignes = source.replace(/\r\n/g, "\n").split("\n");
  const blocs: Bloc[] = [];
  let i = 0;
  while (i < lignes.length) {
    const ligne = lignes[i] ?? "";
    const cloture = /^```\s*([\w+-]*)\s*$/.exec(ligne);
    if (cloture) {
      const corps: string[] = [];
      i++;
      while (i < lignes.length && !/^```\s*$/.test(lignes[i] ?? "")) corps.push(lignes[i++] ?? "");
      i++;
      blocs.push({ type: "code", langue: cloture[1] ?? "", texte: corps.join("\n") });
      continue;
    }
    const titre = /^(#{1,3})\s+(.*)$/.exec(ligne);
    if (titre) {
      blocs.push({ type: "titre", niveau: titre[1]?.length ?? 1, texte: titre[2] ?? "" });
      i++;
      continue;
    }
    const puce = /^\s*(?:[-*•]|(\d+)[.)])\s+(.*)$/.exec(ligne);
    if (puce) {
      const ordonnee = puce[1] !== undefined;
      const items: string[] = [];
      let m: RegExpExecArray | null;
      while (i < lignes.length && (m = /^\s*(?:[-*•]|(\d+)[.)])\s+(.*)$/.exec(lignes[i] ?? "")) !== null) {
        items.push(m[2] ?? "");
        i++;
      }
      blocs.push({ type: "liste", ordonnee, items });
      continue;
    }
    if (!ligne.trim()) {
      i++;
      continue;
    }
    const para: string[] = [];
    while (i < lignes.length && (lignes[i] ?? "").trim() && !/^(```|#{1,3}\s|\s*(?:[-*•]|\d+[.)])\s)/.test(lignes[i] ?? "")) {
      para.push(lignes[i++] ?? "");
    }
    blocs.push({ type: "paragraphe", texte: para.join("\n") });
  }
  return blocs;
}

const MOTIF_EN_LIGNE = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(\[[^\]]+\]\(https?:\/\/[^)\s]+\))/g;

export function enLigne(texte: string, cle = "l"): ReactNode[] {
  const noeuds: ReactNode[] = [];
  let dernier = 0;
  let n = 0;
  for (const m of texte.matchAll(MOTIF_EN_LIGNE)) {
    const debut = m.index;
    if (debut > dernier) noeuds.push(texte.slice(dernier, debut));
    const brut = m[0];
    const k = `${cle}-${n++}`;
    if (m[1]) noeuds.push(<code key={k}>{brut.slice(1, -1)}</code>);
    else if (m[2]) noeuds.push(<strong key={k}>{brut.slice(2, -2)}</strong>);
    else if (m[3]) noeuds.push(<em key={k}>{brut.slice(1, -1)}</em>);
    else {
      const lien = /^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/.exec(brut);
      noeuds.push(
        <a key={k} href={lien?.[2]} target="_blank" rel="noopener noreferrer">
          {lien?.[1]}
        </a>,
      );
    }
    dernier = debut + brut.length;
  }
  if (dernier < texte.length) noeuds.push(texte.slice(dernier));
  return noeuds;
}

export function TexteRiche({ source }: { source: string }) {
  return (
    <div className="md">
      {decouperBlocs(source).map((bloc, i) => {
        switch (bloc.type) {
          case "code":
            return (
              <pre key={i} data-langue={bloc.langue || undefined}>
                <code>{bloc.texte}</code>
              </pre>
            );
          case "titre": {
            const Balise = bloc.niveau === 1 ? "h3" : bloc.niveau === 2 ? "h4" : "h5";
            return <Balise key={i}>{enLigne(bloc.texte, `t${i}`)}</Balise>;
          }
          case "liste": {
            const Balise = bloc.ordonnee ? "ol" : "ul";
            return (
              <Balise key={i}>
                {bloc.items.map((item, j) => (
                  <li key={j}>{enLigne(item, `i${i}-${j}`)}</li>
                ))}
              </Balise>
            );
          }
          default:
            return <p key={i}>{enLigne(bloc.texte, `p${i}`)}</p>;
        }
      })}
    </div>
  );
}
