import { describe, expect, it } from "vitest";

import { aAppliquerSeules, libelleBouton, texteVisible } from "./pilotage";
import type { ActionPilotage } from "./types";

const nav = (vue: string): ActionPilotage => ({ type: "naviguer", genre: "immediate", niveau: "vert", libelle: `Ouvrir ${vue}`, parametres: { vue } });
const mission: ActionPilotage = { type: "proposer_mission", genre: "proposition", niveau: "vert", libelle: "Lancer", parametres: {} };

describe("texte visible pendant le flux", () => {
  it("masque le bloc d'actions et ce qui suit", () => {
    expect(texteVisible('Voici vos missions.\n<actions>[{"type": "nav')).toBe("Voici vos missions.");
    expect(texteVisible("Je vous montre <ACTIONS>[]</ACTIONS>")).toBe("Je vous montre");
  });
  it("retient un début de balise encore incomplet", () => {
    expect(texteVisible("Voici <ac")).toBe("Voici ");
    expect(texteVisible("Voici <")).toBe("Voici ");
    expect(texteVisible("a < b")).toBe("a < b");
    expect(texteVisible("Bonjour")).toBe("Bonjour");
  });
  it("masque aussi un bloc de widget (14 · D 16), le premier bloc l'emporte", () => {
    expect(texteVisible('Minuteur prêt.\n<widget titre="Thé"><div class="w-carte">')).toBe("Minuteur prêt.");
    expect(texteVisible("Voici <wid")).toBe("Voici ");
    expect(texteVisible('Ok <widget titre="a"></widget><actions>[]')).toBe("Ok");
    expect(texteVisible("un <w")).toBe("un ");
  });
});

describe("actions appliquées seules", () => {
  it("seulement en mode « oui », une seule navigation, jamais une proposition", () => {
    expect(aAppliquerSeules([nav("agents"), mission], "demander")).toEqual([]);
    expect(aAppliquerSeules([nav("agents"), mission], "non")).toEqual([]);
    expect(aAppliquerSeules([mission], "oui")).toEqual([]);
    expect(aAppliquerSeules([nav("agents"), nav("couts"), mission], "oui")).toEqual([nav("couts")]);
  });
  it("n'applique jamais seule une action retenue par la barrière d'injection", () => {
    const theme: ActionPilotage = { type: "regler", genre: "immediate", niveau: "vert", libelle: "Thème", parametres: {}, bloquee: "Barrière" };
    expect(aAppliquerSeules([nav("agents"), theme], "oui")).toEqual([nav("agents")]);
    expect(aAppliquerSeules([theme], "oui")).toEqual([]);
  });
});

describe("libellés", () => {
  it("dit ce que fait le bouton", () => {
    expect(libelleBouton(nav("agents"), true)).toBe("Rouvrir");
    expect(libelleBouton(mission, false)).toBe("Lancer la mission");
    expect(libelleBouton({ ...mission, type: "demander_action", niveau: "rouge" }, false)).toBe("Demander (clé d'accès)");
    expect(libelleBouton({ ...mission, type: "proposer_amelioration" }, false)).toBe("Garder la suggestion");
    expect(libelleBouton({ ...mission, bloquee: "Barrière" }, false)).toBe("Lancer moi-même");
  });
});
