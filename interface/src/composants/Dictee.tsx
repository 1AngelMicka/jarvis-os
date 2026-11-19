import { useEffect, useRef, useState } from "react";

import { Enregistreur } from "../voix";
import { Dictee as Gestionnaire, dicter, EVENEMENT_DICTEE, type EtatDicteeEnCours, messageDictee, prechaufferVoix } from "../voixAvancee";
import "../styles/voix-avancee.css";

const DUREE_BULLE = 2600;

/** Dictée globale : l'application de bureau émet « debut » / « fin » quand le raccourci est tenu puis relâché ;
 *  le Core transcrit, corrige, met en forme et colle dans l'application au premier plan. Bulle discrète d'état. */
export function DicteeGlobale() {
  const [etat, setEtat] = useState<EtatDicteeEnCours>({ etape: "repos" });
  const gestionnaire = useRef<Gestionnaire | null>(null);
  const prechauffee = useRef(false);

  useEffect(() => {
    const g = new Gestionnaire(
      () => new Enregistreur(),
      (audio) => dicter(audio, true),
      setEtat,
    );
    gestionnaire.current = g;
    const surDictee = (e: Event) => {
      const detail = (e as CustomEvent<unknown>).detail;
      if (detail === "debut") {
        if (!prechauffee.current) {
          prechauffee.current = true;
          prechaufferVoix().catch(() => {
            prechauffee.current = false; // modèle absent : l'erreur viendra de la dictée elle-même
          });
        }
        g.commencer();
      } else if (detail === "fin") void g.finir();
    };
    window.addEventListener(EVENEMENT_DICTEE, surDictee);
    return () => {
      window.removeEventListener(EVENEMENT_DICTEE, surDictee);
      gestionnaire.current = null;
    };
  }, []);

  useEffect(() => {
    if (etat.etape !== "fini" && etat.etape !== "erreur") return;
    const minuterie = window.setTimeout(() => {
      setEtat({ etape: "repos" });
    }, DUREE_BULLE);
    return () => {
      window.clearTimeout(minuterie);
    };
  }, [etat]);

  const message = messageDictee(etat);
  return (
    <div className="dictee-bulle" role="status" aria-live="polite" data-etape={etat.etape} hidden={message === null}>
      {etat.etape === "ecoute" && <span className="dictee-point" aria-hidden="true" />}
      {message}
    </div>
  );
}
