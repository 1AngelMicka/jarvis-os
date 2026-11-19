import { describe, expect, it } from "vitest";

import { adresseHomeAssistantPlausible, adresseWyoming, depuis, lireClients, presence, statutHomeAssistant, transportHomeAssistant } from "./maison";
import type { CarteHomeAssistant, EtatWyoming } from "./types";

const carte = (r: Partial<CarteHomeAssistant> = {}): CarteHomeAssistant => ({
  id: "home_assistant",
  nom: "Home Assistant",
  description: "",
  actif: false,
  adresse: null,
  mode: "mcp",
  oauth: false,
  jeton_rest: false,
  code_alarme: false,
  pret: false,
  outils: [],
  ...r,
});

describe("Home Assistant", () => {
  it("statut et transport", () => {
    expect(statutHomeAssistant(carte()).texte).toBe("À configurer");
    expect(statutHomeAssistant(carte({ pret: true })).texte).toBe("Désactivé");
    expect(statutHomeAssistant(carte({ actif: true, pret: true }))).toEqual({ texte: "Activé", ton: "ok" });
    expect(transportHomeAssistant(carte())).toBe("Pas encore connecté");
    expect(transportHomeAssistant(carte({ oauth: true }))).toBe("Serveur MCP (OAuth)");
    expect(transportHomeAssistant(carte({ oauth: true, jeton_rest: true }))).toContain("repli REST");
    expect(transportHomeAssistant(carte({ mode: "rest", jeton_rest: true }))).toBe("API REST (jeton longue durée)");
  });

  it("adresse plausible", () => {
    expect(adresseHomeAssistantPlausible("homeassistant.local:8123")).toBe(true);
    expect(adresseHomeAssistantPlausible("http://192.168.1.30:8123")).toBe(true);
    expect(adresseHomeAssistantPlausible("http://ha.local/lovelace")).toBe(false);
    expect(adresseHomeAssistantPlausible("ftp://ha.local")).toBe(false);
    expect(adresseHomeAssistantPlausible("ha local")).toBe(false);
  });
});

describe("pièces et Wyoming", () => {
  const t = Date.parse("2026-11-19T12:00:00Z");
  it("présence lisible", () => {
    expect(depuis(null, t)).toBe("jamais entendue");
    expect(depuis("2026-11-19T11:59:30Z", t)).toBe("à l'instant");
    expect(depuis("2026-11-19T11:55:00Z", t)).toBe("il y a 5 min");
    expect(depuis("2026-11-19T09:00:00Z", t)).toBe("il y a 3 h");
    const piece = { piece: "Salon", satellites: 1, vu_le: "2026-11-19T11:55:00Z", personne: "Léa", occupee: true };
    expect(presence(piece, t)).toBe("Léa, il y a 5 min");
    expect(presence({ ...piece, occupee: false }, t)).toContain("Personne en ce moment");
    expect(presence({ ...piece, vu_le: null }, t)).toBe("Personne entendue");
  });

  it("adresse Wyoming et clients", () => {
    const w: EtatWyoming = { actif: true, hote: "0.0.0.0", port: 10300, clients: [], en_ecoute: true, port_reel: 10300, satellites_connectes: [] };
    expect(adresseWyoming(w)).toBe("adresse de ce PC:10300");
    expect(adresseWyoming({ ...w, hote: "127.0.0.1", port_reel: null })).toBe("127.0.0.1:10300");
    expect(lireClients("192.168.1.30, 192.168.1.31\n192.168.1.30")).toEqual(["192.168.1.30", "192.168.1.31"]);
  });
});
