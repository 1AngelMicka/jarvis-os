import { describe, expect, it } from "vitest";

import { texteEtat, texteEvenement, texteRoute, texteScore, texteSource, tonScore, type RouteMessage } from "./routage";

const route: RouteMessage = {
  type: "code",
  libelle: "Code",
  raison: "règles : bloc de code",
  source: "regles",
  connecteur: "claude_code",
};

describe("routage", () => {
  it("nomme la route avec le connecteur", () => {
    expect(texteRoute(route, (id) => (id === "claude_code" ? "Claude Code" : id))).toBe("Code · Claude Code");
    expect(texteRoute({ ...route, connecteur: null }, (id) => id)).toBe("Code");
  });

  it("dit d'où vient le classement", () => {
    expect(texteSource("modele")).toBe("petit modèle local");
    expect(texteSource("prive")).toBe("sujet privé");
  });

  it("annonce les mesures qui manquent en rodage", () => {
    expect(texteEtat({ etat: "rodage", succes: 2, erreurs: 1 }, 5)).toBe("en rodage (encore 2 mesures)");
    expect(texteEtat({ etat: "rodage", succes: 3, erreurs: 1 }, 5)).toBe("en rodage (encore 1 mesure)");
    expect(texteEtat({ etat: "retrogradee", succes: 3, erreurs: 4 }, 5)).toBe("rétrogradée");
  });

  it("donne un ton au score selon le seuil", () => {
    expect(texteScore(null)).toBe("—");
    expect(texteScore(72)).toBe("72 / 100");
    expect(tonScore(42, 60)).toBe("danger");
    expect(tonScore(65, 60)).toBe("attention");
    expect(tonScore(90, 60)).toBeUndefined();
    expect(tonScore(null, 60)).toBeUndefined();
  });

  it("traduit les événements de l'historique", () => {
    expect(texteEvenement({ type: "code", connecteur: "x", evenement: "retablie", raison: "", le: "" })).toBe("rétablie");
  });
});
