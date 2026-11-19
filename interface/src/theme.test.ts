import { describe, expect, it } from "vitest";

import { estTheme, THEMES } from "./theme";

describe("thèmes", () => {
  it("connaît les cinq thèmes, JARVIS en premier (défaut)", () => {
    expect(THEMES.map((t) => t.id)).toEqual(["jarvis", "studio", "atelier", "console", "presence"]);
  });

  it("refuse une valeur inconnue venue du stockage local", () => {
    expect(estTheme("studio")).toBe(true);
    expect(estTheme("realiste")).toBe(false);
    expect(estTheme(null)).toBe(false);
  });
});
