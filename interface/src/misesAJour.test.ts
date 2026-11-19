import { describe, expect, it } from "vitest";

import { lienVersion, resumeMisesAJour } from "./misesAJour";
import type { EtatMisesAJour } from "./types";

const BASE: EtatMisesAJour = {
  active: true,
  installee: "0.8.0",
  derniere: "0.9.0",
  nouvelle: true,
  notes: "Notes",
  url: "https://github.com/1AngelMicka/jarvis-os/releases/tag/v0.9.0",
  publiee_le: "2026-11-10T09:00:00Z",
  verifie_le: "2026-11-19T08:00:00+00:00",
  erreur: null,
  commande: "jarvis2 mettre-a-jour",
};

describe("indicateur de nouvelle version", () => {
  it("annonce la nouvelle version avec sa date", () => {
    expect(resumeMisesAJour(BASE)).toEqual({ texte: "Nouvelle version 0.9.0 disponible (publiée le 10 novembre 2026).", ton: "attention" });
  });

  it("dit à jour, désactivé, en erreur ou pas encore vérifié", () => {
    expect(resumeMisesAJour({ ...BASE, nouvelle: false }).ton).toBe("ok");
    expect(resumeMisesAJour({ ...BASE, active: false }).texte).toContain("désactivée");
    expect(resumeMisesAJour({ ...BASE, nouvelle: false, erreur: "GitHub injoignable" }).texte).toBe("Dernière vérification impossible : GitHub injoignable.");
    expect(resumeMisesAJour({ ...BASE, nouvelle: false, derniere: null, verifie_le: null }).texte).toBe("Pas encore vérifié.");
  });

  it("n'ouvre que les pages des versions de ce dépôt", () => {
    expect(lienVersion(BASE.url)).toBe(BASE.url);
    expect(lienVersion("https://exemple.invalid/piege")).toBe("https://github.com/1AngelMicka/jarvis-os/releases");
    expect(lienVersion("https://github.com/1AngelMicka/jarvis-os/releases.evil.example")).toBe("https://github.com/1AngelMicka/jarvis-os/releases");
    expect(lienVersion(null)).toBe("https://github.com/1AngelMicka/jarvis-os/releases");
  });
});
