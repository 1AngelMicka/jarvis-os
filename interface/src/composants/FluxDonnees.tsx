// « Où partent mes données » (phase 14 · C, point 15) : la carte des flux générée par le Core depuis la configuration
// réelle. Pour chaque fonction : le service contacté, ce qui part, si cela reste sur le PC, où le désactiver.
// Tableau quand la place le permet, cartes sur téléphone (même contenu, requête de conteneur dans donnees.css).

import { useCallback, useEffect, useState } from "react";

import "../styles/donnees.css";

import { accorderImages, lireFluxDonnees } from "../api";
import { adresse, resoudre } from "../reglages";
import { DESTINATIONS, ETATS, type Filtre, FILTRES, filtrerFlux, phraseResume } from "../donnees";
import type { CarteFlux, FluxDonnee } from "../types";

function dateCourte(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
}

function Destination({ f }: { f: FluxDonnee }) {
  const d = DESTINATIONS[f.destination];
  return (
    <span className="badge-co" data-ton={d.ton}>
      {d.nom}
    </span>
  );
}

function CeQuiPart({ f }: { f: FluxDonnee }) {
  if (!f.envoie.length) return <p className="flux-rien">Rien ne quitte le PC.</p>;
  return (
    <>
      <ul className="flux-liste">
        {f.envoie.map((e) => (
          <li key={e}>{e}</li>
        ))}
      </ul>
      {f.jamais.length > 0 && <p className="flux-jamais">Jamais : {f.jamais.join(" ; ").toLowerCase()}.</p>}
    </>
  );
}

function Desactiver({ f }: { f: FluxDonnee }) {
  const cible = f.desactiver.reglage ? resoudre(f.desactiver.reglage) : null;
  return (
    <span className="flux-desactiver">
      {cible ? <a href={adresse(cible)}>{f.desactiver.texte}</a> : f.desactiver.texte}
      {f.desactiver.vue === "agents" && <span className="flux-ou"> (vue Agents)</span>}
    </span>
  );
}

function AccordImages({ f, surChanger }: { f: FluxDonnee; surChanger: (accorde: boolean) => void }) {
  const images = f.images;
  if (!images) return null;
  return (
    <p className="flux-images" data-accorde={images.accorde || undefined}>
      <span>
        {images.accorde
          ? `Images autorisées${images.accorde_le ? ` depuis le ${dateCourte(images.accorde_le)}` : ""}.`
          : "Images : accord demandé avant la première."}
      </span>
      {images.accorde && (
        <button
          type="button"
          className="btn btn-mini"
          onClick={() => {
            surChanger(false);
          }}
        >
          Révoquer
        </button>
      )}
    </p>
  );
}

export function FluxDonnees({ surNotifier }: { surNotifier: (message: string) => void }) {
  const [carte, setCarte] = useState<CarteFlux | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [filtre, setFiltre] = useState<Filtre>("tout");

  const charger = useCallback(() => {
    lireFluxDonnees()
      .then((c) => {
        setCarte(c);
        setErreur(null);
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Carte des données indisponible.");
      });
  }, []);

  useEffect(() => {
    charger();
  }, [charger]);

  const changerImages = (f: FluxDonnee, accorde: boolean) => {
    const id = f.id.replace(/^connecteur:/, "");
    accorderImages(id, accorde)
      .then(() => {
        surNotifier(accorde ? "Images autorisées pour ce connecteur." : "Accord retiré : JARVIS redemandera avant d'envoyer une image.");
        charger();
      })
      .catch((e: unknown) => {
        surNotifier(e instanceof Error ? e.message : "Impossible de changer l'accord.");
      });
  };

  if (erreur && !carte) {
    return (
      <div className="vide">
        <p className="vide-titre">Carte des données indisponible</p>
        <p>{erreur}</p>
        <button type="button" className="btn btn-mini" onClick={charger}>
          Réessayer
        </button>
      </div>
    );
  }
  if (!carte) return <div className="squelette squelette--ligne" aria-busy="true" />;

  const liste = filtrerFlux(carte.flux, filtre);
  const r = carte.resume;
  return (
    <div className="flux">
      <p className="flux-resume" role="status">
        {phraseResume(r)}
      </p>
      <p className="sec-texte">
        Liste établie à partir de votre configuration réelle. Aucune clé, adresse de serveur ni lieu n'y figure.
        {r.connecteurs_inactifs > 0 &&
          ` ${String(r.connecteurs_inactifs)} connecteur${r.connecteurs_inactifs > 1 ? "s" : ""} d'IA inactif${r.connecteurs_inactifs > 1 ? "s" : ""} ou sans clé : rien n'y part.`}
      </p>

      <div className="segment" role="radiogroup" aria-label="Afficher">
        {FILTRES.map((o) => (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={filtre === o.id}
            className="segment-btn"
            onClick={() => {
              setFiltre(o.id);
            }}
          >
            {o.nom}
          </button>
        ))}
      </div>

      <div className="flux-conteneur">
        <table className="flux-table">
          <caption className="visuellement-cache">Où partent mes données</caption>
          <thead>
            <tr>
              <th scope="col">Fonction et service contacté</th>
              <th scope="col">Ce qui part</th>
              <th scope="col">Destination</th>
              <th scope="col">Où le désactiver</th>
            </tr>
          </thead>
          <tbody>
            {liste.map((f) => (
              <tr key={f.id} data-etat={f.etat}>
                <th scope="row">
                  <span className="flux-fonction">{f.fonction}</span>
                  <span className="flux-service">{f.service}</span>
                  {f.detail && <span className="flux-detail">{f.detail}</span>}
                  <span className="flux-etat">{ETATS[f.etat]}</span>
                </th>
                <td>
                  <CeQuiPart f={f} />
                  <AccordImages
                    f={f}
                    surChanger={(a) => {
                      changerImages(f, a);
                    }}
                  />
                </td>
                <td>
                  <Destination f={f} />
                </td>
                <td>
                  <Desactiver f={f} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <ul className="flux-cartes">
          {liste.map((f) => (
            <li key={f.id} className="flux-carte" data-etat={f.etat}>
              <div className="flux-carte-tete">
                <h4 className="flux-fonction">{f.fonction}</h4>
                <Destination f={f} />
              </div>
              <p className="flux-carte-service">
                <span className="flux-etat">{ETATS[f.etat]}</span> · {f.service}
              </p>
              {f.detail && <p className="flux-detail">{f.detail}</p>}
              <CeQuiPart f={f} />
              <AccordImages
                f={f}
                surChanger={(a) => {
                  changerImages(f, a);
                }}
              />
              <p className="flux-carte-pied">
                <span className="flux-carte-libelle">Désactiver : </span>
                <Desactiver f={f} />
              </p>
            </li>
          ))}
        </ul>
        {!liste.length && <p className="couts-vide">Aucune fonction dans ce filtre.</p>}
      </div>
    </div>
  );
}
