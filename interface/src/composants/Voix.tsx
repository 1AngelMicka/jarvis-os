import { useEffect, useRef, useState } from "react";

import { decrireImage, transcrireAudio } from "../api";
import { capturerEcran, EcouteMainsLibres, Enregistreur, EVENEMENT_SILENCE, EVENEMENT_VOIX, type LecteurVocal } from "../voix";

interface Props {
  lecteur: LecteurVocal;
  enCours: boolean;
  bloquee: boolean;
  surEnvoyer: (texte: string) => void;
  surDescription: (texte: string) => void;
  surNotifier: (message: string) => void;
}

/** Commandes de voix et de vision de la console : dictée, mains libres (« Jarvis, … »), lecture à voix haute,
 *  description de l'écran sur demande. Tout est transcrit et décrit sur le PC. */
export function CommandesVoix({ lecteur, enCours, bloquee, surEnvoyer, surDescription, surNotifier }: Props) {
  const [dictee, setDictee] = useState(false);
  const [mainsLibres, setMainsLibres] = useState(false);
  const [parole, setParole] = useState(lecteur.actif);
  const [ecran, setEcran] = useState(false);
  const enregistreur = useRef<Enregistreur | null>(null);
  const ecoute = useRef<EcouteMainsLibres | null>(null);
  const arme = useRef(0); // « Jarvis » seul : la phrase suivante (8 s) est la commande
  const etat = useRef({ enCours, bloquee });
  etat.current = { enCours, bloquee };
  const micro = "mediaDevices" in navigator && "getUserMedia" in navigator.mediaDevices && typeof MediaRecorder !== "undefined";
  const partage = "mediaDevices" in navigator && "getDisplayMedia" in navigator.mediaDevices;

  useEffect(
    () => () => {
      ecoute.current?.arreter();
      lecteur.arreter();
    },
    [lecteur],
  );

  const basculerParole = (actif: boolean) => {
    lecteur.actif = actif;
    if (!actif) lecteur.arreter();
    setParole(actif);
  };

  // Ctrl+M, « /silence », la palette ou les Réglages coupent (ou rallument) la voix : le bouton suit
  useEffect(() => {
    const couper = () => {
      setParole(false);
    };
    const allumer = () => {
      setParole(true);
    };
    window.addEventListener(EVENEMENT_SILENCE, couper);
    window.addEventListener(EVENEMENT_VOIX, allumer);
    return () => {
      window.removeEventListener(EVENEMENT_SILENCE, couper);
      window.removeEventListener(EVENEMENT_VOIX, allumer);
    };
  }, []);

  const traiterPhrase = (audio: Blob) => {
    transcrireAudio(audio)
      .then((t) => {
        if (etat.current.bloquee) return;
        if (t.eveil) {
          if (t.commande) {
            surEnvoyer(t.commande);
          } else {
            arme.current = performance.now() + 8000;
            surNotifier("Je vous écoute.");
          }
        } else if (performance.now() < arme.current && t.texte) {
          arme.current = 0;
          surEnvoyer(t.texte);
        }
      })
      .catch(() => {
        /* phrase incomprise : ignorée en mains libres */
      });
  };

  const basculerMainsLibres = () => {
    if (mainsLibres) {
      ecoute.current?.arreter();
      ecoute.current = null;
      setMainsLibres(false);
      return;
    }
    const e = new EcouteMainsLibres(traiterPhrase, () => lecteur.parle || etat.current.enCours);
    e.demarrer()
      .then(() => {
        ecoute.current = e;
        setMainsLibres(true);
        basculerParole(true);
        surNotifier("Mains libres : dites « Jarvis, … ».");
      })
      .catch(() => {
        surNotifier("Micro refusé ou indisponible.");
      });
  };

  const basculerDictee = () => {
    if (!dictee) {
      const r = new Enregistreur();
      r.demarrer()
        .then(() => {
          enregistreur.current = r;
          setDictee(true);
        })
        .catch(() => {
          surNotifier("Micro refusé ou indisponible.");
        });
      return;
    }
    setDictee(false);
    const r = enregistreur.current;
    enregistreur.current = null;
    if (!r) return;
    void r
      .arreter()
      .then(transcrireAudio)
      .then((t) => {
        const texte = t.eveil ? t.commande || t.texte : t.texte;
        if (texte) surEnvoyer(texte);
        else surNotifier("Rien entendu.");
      })
      .catch((e: unknown) => {
        surNotifier(e instanceof Error ? e.message : "Transcription impossible.");
      });
  };

  const decrireEcran = () => {
    setEcran(true);
    capturerEcran()
      .then((image) => decrireImage(image))
      .then((r) => {
        surDescription(r.description);
      })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "NotAllowedError") return; // partage annulé
        surNotifier(e instanceof Error ? e.message : "Description impossible.");
      })
      .finally(() => {
        setEcran(false);
      });
  };

  return (
    <div className="console-voix" role="group" aria-label="Voix et écran">
      {micro && (
        <button
          type="button"
          className="segment-btn"
          aria-pressed={dictee}
          disabled={bloquee}
          title="Dicter un message (transcrit sur le PC)"
          onClick={basculerDictee}
        >
          {dictee ? "Envoyer la dictée" : "Dicter"}
        </button>
      )}
      {micro && (
        <button
          type="button"
          className="segment-btn"
          aria-pressed={mainsLibres}
          disabled={bloquee}
          title="Mains libres : dites « Jarvis, … » ; la réponse est lue à voix haute"
          onClick={basculerMainsLibres}
        >
          Mains libres
        </button>
      )}
      {lecteur.disponible && (
        <button
          type="button"
          className="segment-btn"
          aria-pressed={parole}
          title="Lire les réponses à voix haute (voix locale du système)"
          onClick={() => {
            basculerParole(!parole);
          }}
        >
          Voix
        </button>
      )}
      {partage && (
        <button
          type="button"
          className="segment-btn"
          disabled={ecran || bloquee}
          title="Décrire mon écran : vous choisissez quoi partager, un modèle local le décrit (rien n'est gardé)"
          onClick={decrireEcran}
        >
          {ecran ? "Description…" : "Écran"}
        </button>
      )}
    </div>
  );
}
