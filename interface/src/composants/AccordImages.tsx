// Accord séparé avant d'envoyer une image jointe à un connecteur cloud (phase 14 · C, point 15) : demandé la
// première fois pour chaque connecteur, mémorisé par le Core, révocable dans Réglages › Où partent mes données.

import { useEffect, useId, useRef } from "react";

import "../styles/donnees.css";

import { Fenetre } from "./Palette";

interface Props {
  nom: string;
  nbImages: number;
  surAccepter: () => void;
  surRefuser: () => void;
}

export function FenetreAccordImages({ nom, nbImages, surAccepter, surRefuser }: Props) {
  const id = useId();
  const plusieurs = nbImages > 1;
  const refuser = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    // La fenêtre s'ouvre après ce rendu (showModal donne le focus au premier lien) : le choix prudent le reprend
    const minuteur = window.setTimeout(() => refuser.current?.focus(), 0);
    return () => {
      window.clearTimeout(minuteur);
    };
  }, []);
  return (
    <Fenetre etiquette="Accord avant d'envoyer une image" surFermer={surRefuser} className="palette--accord">
      <div className="palette-confirmation" aria-labelledby={`${id}-titre`} aria-describedby={`${id}-texte`}>
        <p className="palette-confirmation-titre" id={`${id}-titre`}>
          Envoyer {plusieurs ? "ces images" : "cette image"} à « {nom} » ?
        </p>
        <div className="palette-confirmation-texte" id={`${id}-texte`}>
          <p>
            {plusieurs ? "Elles quitteront" : "Elle quittera"} le PC pour le service en ligne de ce connecteur. Rien n'est encore parti.
          </p>
          <p>
            Votre accord vaut pour ce connecteur seulement ; il se retire à tout moment dans <a href="#reglages/donnees">Où partent mes données</a>. Pour
            qu'aucune image ne sorte, choisissez une IA locale (Ollama avec un modèle de vision).
          </p>
        </div>
        <div className="palette-confirmation-actions">
          <button type="button" className="btn" ref={refuser} onClick={surRefuser}>
            Ne pas envoyer
          </button>
          <button type="button" className="btn btn-principal" onClick={surAccepter}>
            Autoriser et envoyer
          </button>
        </div>
      </div>
    </Fenetre>
  );
}
