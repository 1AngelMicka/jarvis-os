import { describe, expect, it, vi } from "vitest";

import { unSeul } from "./api";
import { LecteurSSE } from "./sse";

describe("LecteurSSE", () => {
  it("reconstitue des événements coupés entre plusieurs morceaux", () => {
    const l = new LecteurSSE();
    expect(l.pousser('event: delta\ndata: {"texte":"Bon')).toEqual([]);
    expect(l.pousser('jour"}\n\nevent: fin\r\ndata: {}\r\n\r\n')).toEqual([
      { evenement: "delta", donnees: '{"texte":"Bonjour"}' },
      { evenement: "fin", donnees: "{}" },
    ]);
  });

  it("ignore les commentaires et joint les données multilignes", () => {
    const l = new LecteurSSE();
    expect(l.pousser(": battement\n\ndata: a\ndata: b\n\n")).toEqual([{ evenement: "message", donnees: "a\nb" }]);
  });
});

describe("unSeul", () => {
  it("ne lance qu'un appel pour des demandes simultanées", async () => {
    const appel = vi.fn(() => Promise.resolve(42));
    const [a, b] = await Promise.all([unSeul("x", appel), unSeul("x", appel)]);
    expect(a).toBe(42);
    expect(b).toBe(42);
    expect(appel).toHaveBeenCalledTimes(1);
    await unSeul("x", appel);
    expect(appel).toHaveBeenCalledTimes(2); // une fois terminé, un nouvel appel repart
  });
});
