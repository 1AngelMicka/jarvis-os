import { describe, expect, it } from "vitest";

import {
  avecNiveau,
  avecRemplacement,
  confidentialiteDe,
  LIBELLES_NIVEAU,
  lireCompteurs,
  lireMemoireFlux,
  niveauBloc,
  niveauSouvenir,
  phraseCompteurs,
  versionsOrdonnees,
} from "./niveaux";
import type { Souvenir, VersionSouvenir } from "./types";

function souvenir(id: string, extra: Partial<Souvenir> = {}): Souvenir {
  return {
    id,
    contenu: `texte ${id}`,
    type: "fait",
    tags: [],
    source: null,
    confidentialite: "normal",
    origine: "conversation",
    cree_le: "2026-01-01T10:00:00Z",
    maj_le: "2026-01-01T10:00:00Z",
    importance: 0.5,
    acces: 0,
    ...extra,
  };
}

function version(id: string, valid_to: string | null): VersionSouvenir {
  return { ...souvenir(id), valid_to, superseded_by: null };
}

describe("niveaux de confidentialité", () => {
  it("libellés lisibles, avec le tiret de semi-privé", () => {
    expect(LIBELLES_NIVEAU.public.nom).toBe("public");
    expect(LIBELLES_NIVEAU.semi_prive.nom).toBe("semi-privé");
    expect(LIBELLES_NIVEAU.prive.nom).toBe("privé");
  });

  it("le niveau envoyé par le Core prime", () => {
    expect(niveauSouvenir({ niveau: "public", confidentialite: "normal" })).toBe("public");
    expect(niveauBloc({ niveau: "semi_prive", confidentialite: "normal" })).toBe("semi_prive");
  });

  it("ancien Core : déduit de la confidentialité (souvenir semi-privé, bloc public par défaut)", () => {
    expect(niveauSouvenir({ confidentialite: "local_uniquement" })).toBe("prive");
    expect(niveauSouvenir({ confidentialite: "normal" })).toBe("semi_prive");
    expect(niveauBloc({ confidentialite: "local_uniquement" })).toBe("prive");
    expect(niveauBloc({ confidentialite: "normal" })).toBe("public");
  });

  it("privé ⇔ local_uniquement", () => {
    expect(confidentialiteDe("prive")).toBe("local_uniquement");
    expect(confidentialiteDe("semi_prive")).toBe("normal");
    expect(confidentialiteDe("public")).toBe("normal");
  });

  it("mise à jour optimiste puis retour arrière, sans toucher aux autres souvenirs", () => {
    const liste = [souvenir("a"), souvenir("b", { niveau: "public" })];
    const apres = avecNiveau(liste, "a", "prive");
    expect(apres[0]).toMatchObject({ niveau: "prive", confidentialite: "local_uniquement" });
    expect(apres[1]).toBe(liste[1]);
    expect(avecNiveau(apres, "a", "semi_prive")[0]).toMatchObject({ niveau: "semi_prive", confidentialite: "normal" });
    expect(liste[0]?.niveau).toBeUndefined();
  });

  it("le nouveau souvenir prend la place de l'ancien et annonce ses versions", () => {
    const liste = [souvenir("a"), souvenir("b"), souvenir("c")];
    const r = avecRemplacement(liste, "b", souvenir("b2", { contenu: "nouveau" }));
    expect(r.map((s) => s.id)).toEqual(["a", "b2", "c"]);
    expect(r[1]?.remplace).toBe(true);
  });

  it("versions de la plus ancienne à l'actuelle", () => {
    const v = versionsOrdonnees([version("actuelle", null), version("v2", "2026-03-01T00:00:00Z"), version("v1", "2026-02-01T00:00:00Z")]);
    expect(v.map((x) => x.id)).toEqual(["v1", "v2", "actuelle"]);
  });

  it("compteurs : phrase au singulier et au pluriel, lecture tolérante", () => {
    expect(phraseCompteurs({ public: 12, semi_prive: 1, prive: 0 })).toBe("12 publics · 1 semi-privé · 0 privé");
    expect(phraseCompteurs({ public: 1, semi_prive: 340, prive: 8 })).toBe("1 public · 340 semi-privés · 8 privés");
    expect(lireCompteurs({ public: 1, semi_prive: 2, prive: 3 })).toEqual({ public: 1, semi_prive: 2, prive: 3 });
    expect(lireCompteurs(undefined)).toBeNull();
    expect(lireCompteurs({ public: 1, semi_prive: 2 })).toBeNull();
    expect(lireCompteurs({ public: -1, semi_prive: 2, prive: 3 })).toBeNull();
  });
});

describe("section Mémoire de « Où partent mes données »", () => {
  const niveaux = { public: 3, semi_prive: 40, prive: 5 };

  it("absente ou illisible (ancien Core) : null", () => {
    expect(lireMemoireFlux(undefined)).toBeNull();
    expect(lireMemoireFlux(null)).toBeNull();
    expect(lireMemoireFlux({ regles: [] })).toBeNull();
    expect(lireMemoireFlux({ niveaux, regles: "x" })).toBeNull();
  });

  it("règles remises dans l'ordre, règles inconnues ignorées, libellé par défaut, porte facultative", () => {
    const m = lireMemoireFlux({
      niveaux,
      regles: [
        { niveau: "prive", libelle: "Privé", vers_cloud: "Jamais." },
        { niveau: "secret", libelle: "?", vers_cloud: "?" },
        { niveau: "public", libelle: "", vers_cloud: "Partout, expurgé." },
        { niveau: "semi_prive", vers_cloud: "Seulement s'il est pertinent." },
        "n'importe quoi",
      ],
    });
    expect(m?.regles.map((r) => r.niveau)).toEqual(["public", "semi_prive", "prive"]);
    expect(m?.regles[0]?.libelle).toBe("public");
    expect(m?.regles[1]?.libelle).toBe("semi-privé");
    expect(m?.porte_rappel).toBe("");
    expect(m?.niveaux).toEqual(niveaux);
  });
});
