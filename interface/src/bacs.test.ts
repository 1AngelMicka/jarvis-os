import { describe, expect, it } from "vitest";

import { descriptionBac, etatBac, libelleChoix, ligneEvenementBac, optionsBac, suffixeBac } from "./bacs";
import type { BacASable } from "./types";

const BACS: BacASable[] = [
  { id: "docker", nom: "Docker", disponible: true, raison: "Docker Desktop tourne" },
  { id: "windows_sandbox", nom: "Windows Sandbox", disponible: false, raison: "fonctionnalité Windows non activée" },
];

describe("choix du bac à sable", () => {
  it("propose Automatique, chaque bac avec son état, puis Sans bac à sable", () => {
    expect(optionsBac(BACS).map((o) => o.valeur)).toEqual(["auto", "docker", "windows_sandbox", "aucun"]);
    expect(optionsBac(BACS)[2]?.libelle).toBe("Windows Sandbox — indisponible");
  });

  it("garde le choix actuel même si le bac n'est plus détecté", () => {
    expect(optionsBac(BACS, "podman").map((o) => o.valeur)).toEqual(["auto", "docker", "windows_sandbox", "podman", "aucun"]);
    expect(optionsBac([], "aucun").map((o) => o.valeur)).toEqual(["auto", "aucun"]);
  });

  it("nomme les choix et signale l'absence de réseau des conteneurs", () => {
    expect(libelleChoix("auto")).toBe("Automatique");
    expect(libelleChoix("aucun")).toBe("Sans bac à sable 🟡");
    expect(descriptionBac("docker", BACS)).toBe("Docker (sans réseau)");
    expect(descriptionBac("bubblewrap")).toBe("bubblewrap (sans réseau)");
  });
});

describe("état du bac à sable d'un atelier", () => {
  it("n'affiche rien avec un Core antérieur", () => {
    expect(etatBac({})).toBeNull();
  });

  it("montre le bac effectif", () => {
    expect(etatBac({ bac_a_sable: "auto", bac: { effectif: "docker", refus: null } }, BACS)).toEqual({
      texte: "Bac à sable : Docker (sans réseau) · choix automatique",
      ton: "ok",
      refuse: false,
    });
  });

  it("signale le choix sans bac à sable en 🟡", () => {
    expect(etatBac({ bac_a_sable: "aucun", bac: { effectif: null, refus: null } })).toMatchObject({ ton: "attention", refuse: false });
  });

  it("le refus passe avant tout et donne sa raison", () => {
    const e = etatBac({ bac_a_sable: "auto", bac: { effectif: null, refus: "aucun bac à sable disponible" } });
    expect(e).toEqual({ texte: "Refusé : aucun bac à sable disponible", ton: "risque", refuse: true });
  });
});

describe("événements du fil", () => {
  it("libelle les trois nouveaux types", () => {
    expect(ligneEvenementBac("bac_a_sable", { choix: "docker", avant: "auto" }, BACS)).toBe("Bac à sable : Docker (avant : Automatique)");
    expect(ligneEvenementBac("bac_a_sable_refuse", { raison: "Docker arrêté" })).toBe("Lancement refusé, aucun bac à sable : Docker arrêté");
    expect(ligneEvenementBac("sans_bac_a_sable", {})).toContain("directement sur le PC");
    expect(ligneEvenementBac("texte", {})).toBeNull();
  });

  it("indique le bac d'une consigne seulement si le Core l'envoie", () => {
    expect(suffixeBac({ texte: "x" })).toBe("");
    expect(suffixeBac({ bac: "podman" })).toBe(" [Podman (sans réseau)]");
    expect(suffixeBac({ bac: null })).toBe(" [sans bac à sable 🟡]");
  });
});
