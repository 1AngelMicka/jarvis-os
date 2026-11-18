import { describe, expect, it } from "vitest";

import { base64urlVersOctets, octetsVersBase64url } from "./webauthn";

describe("base64url", () => {
  it("fait l'aller-retour sans remplissage ni caractères + /", () => {
    const octets = new Uint8Array([251, 255, 191, 0, 1, 2, 3]);
    const texte = octetsVersBase64url(octets.buffer);
    expect(texte).toBe("-_-_AAECAw");
    expect(new Uint8Array(base64urlVersOctets(texte ?? ""))).toEqual(octets);
    expect(octetsVersBase64url(null)).toBeNull();
  });
});
