import { useCallback, useEffect, useState } from "react";

import { lireMisesAJour, reglerMisesAJour } from "../api";
import { lienVersion, resumeMisesAJour } from "../misesAJour";
import type { EtatMisesAJour } from "../types";

/** Nouvelle version du Core : vérifiée au plus une fois par jour par le Core, jamais installée sans votre accord. */
export function MisesAJour() {
  const [etat, setEtat] = useState<EtatMisesAJour | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(false);

  const charger = useCallback(() => {
    lireMisesAJour()
      .then((e) => {
        setErreur(null);
        setEtat(e);
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "État des mises à jour illisible.");
      });
  }, []);
  useEffect(charger, [charger]);

  const regler = (verifier: boolean) => {
    setEnCours(true);
    reglerMisesAJour(verifier)
      .then((e) => {
        setErreur(null);
        setEtat(e);
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Réglage impossible.");
      })
      .finally(() => {
        setEnCours(false);
      });
  };

  if (!etat) return erreur ? <p className="carte-co-message">{erreur}</p> : <div className="squelette squelette--ligne" />;
  const resume = resumeMisesAJour(etat);
  return (
    <div className="maj">
      <p className="maj-etat" role="status">
        {etat.nouvelle && (
          <span className="badge-co" data-ton="attention">
            Nouvelle version
          </span>
        )}
        <span>{resume.texte}</span>
      </p>
      {etat.nouvelle && (
        <>
          {etat.notes && (
            <details className="maj-notes">
              <summary>Notes de la version {etat.derniere}</summary>
              {/* Texte brut : affiché tel quel, jamais interprété */}
              <pre className="maj-notes-texte">{etat.notes}</pre>
            </details>
          )}
          <p className="sec-texte">
            Pour l'installer, lancez dans un terminal <code>{etat.commande}</code> : la commande montre la version et demande votre accord
            avant toute installation.
          </p>
          <a className="maj-lien" href={lienVersion(etat.url)} target="_blank" rel="noopener noreferrer">
            Voir la version sur GitHub
          </a>
        </>
      )}
      <label className="carte-co-case carte-co-case--ligne">
        <input
          type="checkbox"
          checked={etat.active}
          disabled={enCours}
          onChange={(e) => {
            regler(e.target.checked);
          }}
        />
        <span>Vérifier les nouvelles versions (une fois par jour)</span>
      </label>
      <p className="sec-texte">
        Seule une demande à l'API publique de GitHub part (votre adresse IP, sans compte) ; rien n'est installé sans votre accord.
      </p>
      {erreur && <p className="carte-co-message">{erreur}</p>}
    </div>
  );
}
