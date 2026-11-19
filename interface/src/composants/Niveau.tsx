// Pastille du niveau de confidentialité, qui est aussi son sélecteur (lot 14 · C 14) : un `<select>` natif, donc
// utilisable au clavier (Tab, flèches) et lu correctement par les lecteurs d'écran.

import { LIBELLES_NIVEAU, NIVEAUX } from "../niveaux";
import type { Niveau } from "../types";

export function SelecteurNiveau({
  niveau,
  etiquette,
  occupe = false,
  surChoisir,
}: {
  niveau: Niveau;
  /** Nom accessible, ex. « Niveau du souvenir ». */
  etiquette: string;
  occupe?: boolean;
  surChoisir: (n: Niveau) => void;
}) {
  return (
    <select
      className="niveau-select"
      data-niveau={niveau}
      value={niveau}
      aria-label={etiquette}
      aria-busy={occupe || undefined}
      title={LIBELLES_NIVEAU[niveau].aide}
      onChange={(e) => {
        const n = NIVEAUX.find((x) => x === e.target.value);
        if (n && n !== niveau) surChoisir(n);
      }}
    >
      {NIVEAUX.map((n) => (
        <option key={n} value={n}>
          {LIBELLES_NIVEAU[n].nom}
        </option>
      ))}
    </select>
  );
}
