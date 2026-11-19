import { useEffect, useRef, useState } from "react";

import { decrireImage, ErreurApi, transcrireAudio } from "../api";
import { appliquerDecision, ecouterPhrase, EVENEMENT_ECOUTE_FOND, horodatage, lireEcouteFond, signalerEveil, suivreFinDeReponse } from "../eveil";
import { capturerEcran, couperVoix, EcouteMainsLibres, Enregistreur, EVENEMENT_SILENCE, EVENEMENT_VOIX, type LecteurVocal } from "../voix";

interface Props {
  lecteur: LecteurVocal;
  enCours: boolean;
  bloquee: boolean;
  /** Serveur sans écran : le Core refuse les captures, le bouton le dit au lieu de disparaître. */
  sansEcran: boolean;
  surEnvoyer: (texte: string) => void;
  /** « Stop » dit à voix haute : arrête la réponse en cours. */
  surArreter?: () => void;
  surDescription: (texte: string) => void;
  surNotifier: (message: string) => void;
}

/** Commandes de voix et de vision de la console : dictée, mains libres (« Jarvis, … »), lecture à voix haute,
 *  description de l'écran sur demande (indisponible en mode sans écran). Tout est transcrit et décrit sur le PC. */
export function CommandesVoix({ lecteur, enCours, bloquee, sansEcran, surEnvoyer, surArreter, surDescription, surNotifier }: Props) {
  const [dictee, setDictee] = useState(false);
  const [mainsLibres, setMainsLibres] = useState(false);
  const [parole, setParole] = useState(lecteur.actif);
  const [ecran, setEcran] = useState(false);
  const enregistreur = useRef<Enregistreur | null>(null);
  const ecoute = useRef<EcouteMainsLibres | null>(null);
  const finSuivie = useRef<(() => void) | null>(null); // réponse suivie jusqu'à la fin de la voix de JARVIS
  const modeleSignale = useRef(false);
  const etat = useRef({ enCours, bloquee, surEnvoyer, surArreter, surNotifier });
  etat.current = { enCours, bloquee, surEnvoyer, surArreter, surNotifier };
  const micro = "mediaDevices" in navigator && "getUserMedia" in navigator.mediaDevices && typeof MediaRecorder !== "undefined";
  const partage = "mediaDevices" in navigator && "getDisplayMedia" in navigator.mediaDevices;

  useEffect(
    () => () => {
      ecoute.current?.arreter();
      finSuivie.current?.();
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

  // Le Core décide (mot d'éveil, relance, « stop », « silence ») sur les horodatages de la phrase
  const traiterPhrase = (audio: Blob, debut: number, fin: number) => {
    ecouterPhrase(audio, horodatage(debut), horodatage(fin))
      .then((d) => {
        const e = etat.current;
        if (e.bloquee) return;
        const repond = appliquerDecision(d, {
          envoyer: e.surEnvoyer,
          arreter: () => {
            lecteur.arreter();
            e.surArreter?.();
          },
          couperVoix: () => {
            couperVoix(lecteur);
          },
          notifier: e.surNotifier,
        });
        if (!repond) return;
        finSuivie.current?.();
        finSuivie.current = suivreFinDeReponse(
          () => etat.current.enCours || lecteur.parle,
          (t) => {
            finSuivie.current = null;
            void signalerEveil("parole_fin", t).catch(() => undefined);
          },
        );
      })
      .catch((e: unknown) => {
        // Modèle de transcription absent : dit une fois ; une phrase incomprise est ignorée en mains libres
        if (e instanceof ErreurApi && e.statut === 409 && !modeleSignale.current) {
          modeleSignale.current = true;
          etat.current.surNotifier(e.message);
        }
      });
  };

  // L'écoute se met en pause pendant que JARVIS parle (écho) ; pendant qu'il réfléchit, « stop » reste entendu
  const demarrerEcoute = (annonce: boolean) => {
    if (ecoute.current) return;
    const e = new EcouteMainsLibres(traiterPhrase, () => lecteur.parle);
    ecoute.current = e;
    e.demarrer()
      .then(() => {
        setMainsLibres(true);
        basculerParole(true);
        if (annonce) surNotifier("Mains libres : dites « Jarvis, … ».");
      })
      .catch(() => {
        ecoute.current = null;
        surNotifier("Micro refusé ou indisponible.");
      });
  };

  const arreterEcoute = () => {
    ecoute.current?.arreter();
    ecoute.current = null;
    finSuivie.current?.();
    finSuivie.current = null;
    setMainsLibres(false);
  };

  const basculerMainsLibres = () => {
    if (mainsLibres) arreterEcoute();
    else demarrerEcoute(true);
  };

  // « Dis Jarvis » en fond (préférence de l'appareil) : l'écoute démarre avec l'interface et suit les Réglages
  const ecouteFond = useRef({ demarrerEcoute, arreterEcoute });
  ecouteFond.current = { demarrerEcoute, arreterEcoute };
  useEffect(() => {
    if (!micro) return;
    if (lireEcouteFond()) ecouteFond.current.demarrerEcoute(false);
    const suivre = (e: Event) => {
      if ((e as CustomEvent<unknown>).detail === true) ecouteFond.current.demarrerEcoute(true);
      else ecouteFond.current.arreterEcoute();
    };
    window.addEventListener(EVENEMENT_ECOUTE_FOND, suivre);
    return () => {
      window.removeEventListener(EVENEMENT_ECOUTE_FOND, suivre);
    };
  }, [micro]);

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
          title="Mains libres : dites « Jarvis, … » ; la réponse est lue à voix haute, puis la suite se dit sans « Jarvis »"
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
      {sansEcran ? (
        <button
          type="button"
          className="segment-btn"
          disabled
          aria-label="Écran : indisponible en mode sans écran"
          title="Indisponible en mode sans écran : ce Core tourne sur un serveur sans écran"
        >
          Sans écran
        </button>
      ) : partage && (
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
