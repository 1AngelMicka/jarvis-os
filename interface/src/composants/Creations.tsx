import { useCallback, useEffect, useState } from "react";

import { creerCreation, lienCreation, listerCreations, modifierCreation } from "../api";

interface CreationListe {
  id: string;
  titre: string;
  description: string;
  version_courante: number;
  maj_le: string;
}

/** Créations : petites pages générées par JARVIS, ouvertes dans un bac à sable (origine isolée, aucun réseau). */
export function SectionCreations({ surChangement }: { surChangement: (m?: string) => void }) {
  const [liste, setListe] = useState<CreationListe[] | null>(null);
  const [titre, setTitre] = useState("");
  const [demande, setDemande] = useState("");
  const [modif, setModif] = useState("");
  const [ouverte, setOuverte] = useState<{ id: string; url: string; version: number } | null>(null);
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const charger = useCallback(() => {
    listerCreations()
      .then((r) => {
        setListe(r.creations);
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Lecture impossible.");
      });
  }, []);
  useEffect(charger, [charger]);

  const ouvrir = (id: string) => {
    lienCreation(id)
      .then((l) => {
        setOuverte({ id, url: l.url, version: l.version });
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Ouverture impossible.");
      });
  };

  const agir = (appel: Promise<{ id: string }>, message: string) => {
    setOccupe(true);
    setErreur(null);
    appel
      .then((r) => {
        surChangement(message);
        charger();
        ouvrir(r.id);
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Échec.");
      })
      .finally(() => {
        setOccupe(false);
      });
  };

  return (
    <section className="famille-co" aria-labelledby="agents-creations">
      <h3 className="sec-titre" id="agents-creations">
        Créations
      </h3>
      <p className="sec-texte">
        Une petite page (outil, jeu, visualisation) écrite par JARVIS, ouverte dans un bac à sable : isolée de JARVIS, sans accès au
        réseau. Chaque modification garde la version précédente.
      </p>
      <form
        className="mission-form"
        onSubmit={(e) => {
          e.preventDefault();
          agir(creerCreation(titre.trim(), demande.trim()), `Création « ${titre.trim()} » prête.`);
          setTitre("");
          setDemande("");
        }}
      >
        <label className="visuellement-cache" htmlFor="creation-titre">
          Titre de la création
        </label>
        <input
          id="creation-titre"
          className="creation-titre"
          value={titre}
          placeholder="Titre (ex. Minuteur de cuisine)"
          onChange={(e) => {
            setTitre(e.target.value);
          }}
        />
        <label className="visuellement-cache" htmlFor="creation-demande">
          Ce que doit faire la page
        </label>
        <textarea
          id="creation-demande"
          rows={2}
          value={demande}
          placeholder="Ce que doit faire la page…"
          onChange={(e) => {
            setDemande(e.target.value);
          }}
        />
        <button type="submit" className="btn btn-principal btn-mini" disabled={occupe || !titre.trim() || demande.trim().length < 3}>
          {occupe ? "Création…" : "Créer"}
        </button>
      </form>
      {erreur && <p className="securite-erreur">{erreur}</p>}
      {liste && liste.length > 0 && (
        <ul className="cartes-co">
          {liste.map((c) => (
            <li key={c.id} className="carte-co">
              <div className="carte-co-tete">
                <h4 className="carte-co-nom">{c.titre}</h4>
                <span className="badge-co">v{c.version_courante}</span>
              </div>
              <p className="carte-co-detail">{c.description}</p>
              <div className="carte-co-actions">
                <button
                  type="button"
                  className="btn btn-mini"
                  onClick={() => {
                    if (ouverte?.id === c.id) setOuverte(null);
                    else ouvrir(c.id);
                  }}
                >
                  {ouverte?.id === c.id ? "Fermer" : "Ouvrir"}
                </button>
              </div>
              {ouverte?.id === c.id && (
                <>
                  <iframe className="creation-cadre" title={`Création : ${c.titre}`} src={ouverte.url} sandbox="allow-scripts allow-forms allow-modals" />
                  <form
                    className="carte-co-cle"
                    onSubmit={(e) => {
                      e.preventDefault();
                      agir(modifierCreation(c.id, modif.trim()), `« ${c.titre} » modifiée.`);
                      setModif("");
                    }}
                  >
                    <label className="visuellement-cache" htmlFor={`modif-${c.id}`}>
                      Modification
                    </label>
                    <input
                      id={`modif-${c.id}`}
                      value={modif}
                      placeholder="Modifier (ex. ajoute un bouton pause)"
                      onChange={(e) => {
                        setModif(e.target.value);
                      }}
                    />
                    <button type="submit" className="btn btn-mini" disabled={occupe || modif.trim().length < 3}>
                      Modifier
                    </button>
                  </form>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
