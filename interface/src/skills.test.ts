import { describe, expect, it } from "vitest";

import { empreinteChangee, empreinteCourte, parCapacite } from "./skills";
import type { Skill } from "./skills";

const base: Skill = {
  id: "1",
  nom: "essai",
  description: "Essai",
  origine: "archive",
  source: "essai.zip",
  confiance: "instructions",
  statut: "approuve",
  capacites: [],
  capacites_acceptees: [],
  dangereuses: [],
  fichiers: [],
  empreinte: "a".repeat(64),
  empreinte_approuvee: "a".repeat(64),
  raison_blocage: null,
  importe_par: "PC",
  approuve_par: "PC",
  cree_le: "2026-11-19T10:00:00+00:00",
  approuve_le: "2026-11-19T10:01:00+00:00",
  bloque_le: null,
};

describe("skills", () => {
  it("abrège l'empreinte", () => {
    expect(empreinteCourte("0123456789abcdef")).toBe("0123456789ab…");
    expect(empreinteCourte(null)).toBe("—");
  });

  it("repère une empreinte changée ou un skill bloqué", () => {
    expect(empreinteChangee({ ...base, empreinte_actuelle: "a".repeat(64) })).toBe(false);
    expect(empreinteChangee({ ...base, empreinte_actuelle: "b".repeat(64) })).toBe(true);
    expect(empreinteChangee({ ...base, empreinte_actuelle: null })).toBe(true);
    expect(empreinteChangee({ ...base, statut: "bloque" })).toBe(true);
    expect(empreinteChangee(base)).toBe(false); // empreinte actuelle pas encore lue
  });

  it("regroupe les détections par capacité dans un ordre stable", () => {
    const groupes = parCapacite([
      { capacite: "ecriture", fichier: "a.py", raison: "x" },
      { capacite: "shell", fichier: "a.py", raison: "script" },
      { capacite: "ecriture", fichier: "b.py", raison: "y" },
    ]);
    expect(groupes.map(([c, l]) => [c, l.length])).toEqual([
      ["shell", 1],
      ["ecriture", 2],
    ]);
  });
});
