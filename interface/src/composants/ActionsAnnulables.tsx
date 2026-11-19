import { useCallback, useEffect, useState } from "react";

import { annulerAction, EVENEMENT_DEMANDE_DECIDEE, listerAnnulations } from "../api";
import type { EntreeAnnulation } from "../types";

const HEURE = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });
const AFFICHEES = 5;

interface Props {
  surChangement: (message?: string) => void;
}

/** Pile d'annulation : les dernières actions réversibles exécutées (24 h), chacune avec son bouton « Annuler ». */
export function ActionsAnnulables({ surChangement }: Props) {
  const [entrees, setEntrees] = useState<EntreeAnnulation[] | null>(null);
  const [occupee, setOccupee] = useState<string | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  const charger = useCallback(() => {
    listerAnnulations()
      .then((r) => {
        setEntrees(r.annulations);
      })
      .catch(() => {
        setEntrees([]);
      });
  }, []);

  useEffect(() => {
    charger();
    window.addEventListener(EVENEMENT_DEMANDE_DECIDEE, charger);
    return () => {
      window.removeEventListener(EVENEMENT_DEMANDE_DECIDEE, charger);
    };
  }, [charger]);

  if (!entrees?.length) return null;

  const annuler = (e: EntreeAnnulation) => {
    setOccupee(e.id);
    setErreur(null);
    annulerAction(e.id)
      .then(() => {
        surChangement(`Annulé : ${e.resume} (${e.comment.toLowerCase()})`);
      })
      .catch((x: unknown) => {
        setErreur(x instanceof Error ? x.message : "Annulation impossible.");
        charger();
      })
      .finally(() => {
        setOccupee(null);
      });
  };

  return (
    <section className="annulables" aria-labelledby="annulables-titre">
      <h3 className="annulables-titre" id="annulables-titre">
        Dernières actions annulables
      </h3>
      {erreur && (
        <p className="demande-erreur" role="alert">
          {erreur}
        </p>
      )}
      <ul className="annulables-liste">
        {entrees.slice(0, AFFICHEES).map((e) => (
          <li key={e.id} className="annulable">
            <div className="annulable-texte">
              <p className="annulable-resume">{e.resume}</p>
              <p className="demande-meta">
                {HEURE.format(new Date(e.cree_le))} · {e.comment}
              </p>
            </div>
            <button
              type="button"
              className="btn btn-discret btn-mini"
              disabled={occupee === e.id}
              aria-label={`Annuler : ${e.resume}`}
              onClick={() => {
                annuler(e);
              }}
            >
              Annuler
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
