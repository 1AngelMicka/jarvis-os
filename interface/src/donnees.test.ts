import { describe, expect, it } from "vitest";

import { DESTINATIONS, filtrerFlux, lignesMemoire, phraseMemoire, phraseResume } from "./donnees";
import type { FluxDonnee } from "./types";

function flux(id: string, destination: FluxDonnee["destination"]): FluxDonnee {
  return {
    id,
    categorie: "ia",
    fonction: id,
    service: "s",
    destination,
    local: destination === "pc",
    etat: "actif",
    envoie: [],
    jamais: [],
    detail: null,
    desactiver: { texte: "t", reglage: null, vue: null },
    images: null,
  };
}

describe("où partent mes données", () => {
  const liste = [flux("a", "pc"), flux("b", "internet"), flux("c", "reseau"), flux("d", "variable")];

  it("filtre ce qui sort et ce qui reste (un programme MCP compte comme sortant)", () => {
    expect(filtrerFlux(liste, "tout").map((f) => f.id)).toEqual(["a", "b", "c", "d"]);
    expect(filtrerFlux(liste, "sort").map((f) => f.id)).toEqual(["b", "c", "d"]);
    expect(filtrerFlux(liste, "reste").map((f) => f.id)).toEqual(["a"]);
  });

  it("phrase de synthèse au singulier, au pluriel et sans sortie", () => {
    const base = { flux: 4, locaux: 1, connecteurs_inactifs: 0 };
    expect(phraseResume({ ...base, sortants_actifs: 0, internet_actifs: 0 })).toBe("En ce moment, rien ne sort du PC sans votre accord.");
    expect(phraseResume({ ...base, sortants_actifs: 1, internet_actifs: 1 })).toBe("1 fonction active envoie des données hors du PC, dont 1 vers Internet.");
    expect(phraseResume({ ...base, sortants_actifs: 3, internet_actifs: 0 })).toBe("3 fonctions actives envoient des données hors du PC.");
  });

  it("Internet est signalé, le PC rassure", () => {
    expect(DESTINATIONS.internet.ton).toBe("attention");
    expect(DESTINATIONS.pc.ton).toBe("ok");
  });
});

describe("section Mémoire", () => {
  it("synthèse des niveaux, vide, singulier et pluriel", () => {
    expect(phraseMemoire({ public: 0, semi_prive: 0, prive: 0 })).toBe("Aucun souvenir pour l'instant.");
    expect(phraseMemoire({ public: 1, semi_prive: 1, prive: 0 })).toBe(
      "Sur 2 souvenirs, 1 peut partir vers une IA externe, 1 seulement s'il est utile au message, 0 jamais.",
    );
    expect(phraseMemoire({ public: 12, semi_prive: 340, prive: 8 })).toBe(
      "Sur 360 souvenirs, 12 peuvent partir vers une IA externe, 340 seulement s'ils sont utiles au message, 8 jamais.",
    );
  });

  it("une ligne par règle, avec le nombre de son niveau", () => {
    const lignes = lignesMemoire({
      niveaux: { public: 2, semi_prive: 30, prive: 4 },
      regles: [
        { niveau: "public", libelle: "Public", vers_cloud: "Partout." },
        { niveau: "prive", libelle: "Privé", vers_cloud: "Jamais." },
      ],
      porte_rappel: "",
    });
    expect(lignes).toEqual([
      { niveau: "public", nom: "public", nombre: 2, libelle: "Public", vers_cloud: "Partout." },
      { niveau: "prive", nom: "privé", nombre: 4, libelle: "Privé", vers_cloud: "Jamais." },
    ]);
  });
});
