import { describe, expect, it } from "vitest";

import { attributPermis, filtrer, formaterDuree } from "./widgets";

describe("widgets : attributs revérifiés après DOMPurify", () => {
  it("accepte les classes, adresses et valeurs de la liste fermée", () => {
    expect(attributPermis("div", "class", "w-carte w-grille")).toBe(true);
    expect(attributPermis("a", "href", "#memoire")).toBe(true);
    expect(attributPermis("a", "href", "#reglages/themes")).toBe(true);
    expect(attributPermis("time", "data-minuteur", "240")).toBe(true);
    expect(attributPermis("meter", "value", "0.4")).toBe(true);
  });

  it.each([
    ["classe inconnue", "div", "class", "w-carte rouge-vif"],
    ["classe d'un autre composant", "div", "class", "btn-principal"],
    ["javascript:", "a", "href", "javascript:alert(1)"],
    ["adresse externe", "a", "href", "https://exemple.org"],
    ["protocole relatif", "a", "href", "//exemple.org"],
    ["vue inconnue", "a", "href", "#ailleurs"],
    ["href hors de a", "p", "href", "#memoire"],
    ["style", "p", "style", "color:red"],
    ["onerror", "img", "onerror", "alert(1)"],
    ["onclick sur une balise permise", "p", "onclick", "alert(1)"],
    ["src", "a", "src", "x"],
    ["xlink:href (svg)", "a", "xlink:href", "javascript:alert(1)"],
    ["data-minuteur hors de time", "p", "data-minuteur", "60"],
    ["valeur non numérique", "meter", "value", "calc(1)"],
    ["title avec chevrons", "p", "title", "<script>"],
  ])("refuse : %s", (_nom, balise, attribut, valeur) => {
    expect(attributPermis(balise, attribut, valeur)).toBe(false);
  });
});

describe("widgets : filtre", () => {
  it("sans DOM (ou DOMPurify non pris en charge), tout est refusé, rien n'est rendu brut", () => {
    const r = filtrer('<p class="w-libelle">Bonjour</p>');
    expect(r.ok).toBe(false);
  });
});

describe("widgets : minuteur", () => {
  it("formate la durée", () => {
    expect(formaterDuree(240)).toBe("4:00");
    expect(formaterDuree(65)).toBe("1:05");
    expect(formaterDuree(3723)).toBe("1:02:03");
    expect(formaterDuree(-3)).toBe("0:00");
  });
});
