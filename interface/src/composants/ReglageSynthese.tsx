import { useEffect, useState } from "react";

import {
  appliquerReglagesSynthese,
  enregistrerCleElevenLabs,
  type EtatSynthese,
  lireSynthese,
  type MoteurSynthese,
  reglerSynthese,
  supprimerCleElevenLabs,
  telechargerVoixPiper,
} from "../synthese";
import type { LecteurVocal } from "../voix";

import "../styles/synthese.css";

const MOTEURS: readonly { id: MoteurSynthese; nom: string }[] = [
  { id: "navigateur", nom: "Appareil" },
  { id: "piper", nom: "Piper" },
  { id: "elevenlabs", nom: "ElevenLabs" },
];
const COUPURE = [
  { id: "oui", nom: "Oui" },
  { id: "non", nom: "Non" },
] as const;

function Choix<T extends string>({ libelle, options, valeur, surChoix, desactive }: { libelle: string; options: readonly { id: T; nom: string }[]; valeur: T; surChoix: (v: T) => void; desactive?: boolean }) {
  return (
    <div className="segment" role="radiogroup" aria-label={libelle}>
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          role="radio"
          aria-checked={valeur === o.id}
          className="segment-btn"
          disabled={desactive}
          onClick={() => {
            surChoix(o.id);
          }}
        >
          {o.nom}
        </button>
      ))}
    </div>
  );
}

function mo(octets: number): string {
  return `${String(Math.round(octets / 1_000_000))} Mo`;
}

/** Voix de synthèse au choix (lot K2) : appareil, Piper (local, voix téléchargée sur accord), ElevenLabs (clé du
 *  coffre) ; coupure quand on parle par-dessus. La clé n'est jamais renvoyée par le Core : seulement son aperçu. */
export function ReglageSynthese({ lecteur, surNotifier }: { lecteur: LecteurVocal; surNotifier: (m: string) => void }) {
  const [etat, setEtat] = useState<EtatSynthese | null>(null);
  const [erreur, setErreur] = useState("");
  const [cle, setCle] = useState("");
  const [occupe, setOccupe] = useState(false);

  const recevoir = (e: EtatSynthese) => {
    setEtat(e);
    appliquerReglagesSynthese(e.reglages);
  };

  useEffect(() => {
    lireSynthese()
      .then(recevoir)
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "État de la synthèse illisible.");
      });
  }, []);

  // Téléchargement de la voix Piper en cours : état relu toutes les 2 s
  const telechargement = etat?.piper.telechargement.statut;
  useEffect(() => {
    if (telechargement !== "en_cours") return;
    const minuterie = window.setInterval(() => {
      lireSynthese()
        .then(recevoir)
        .catch(() => {
          /* nouvel essai au prochain tour */
        });
    }, 2000);
    return () => {
      window.clearInterval(minuterie);
    };
  }, [telechargement]);

  const agir = (action: () => Promise<EtatSynthese>, message?: string) => {
    setOccupe(true);
    action()
      .then((e) => {
        recevoir(e);
        if (message) surNotifier(message);
      })
      .catch((e: unknown) => {
        surNotifier(e instanceof Error ? e.message : "Impossible pour l'instant.");
      })
      .finally(() => {
        setOccupe(false);
      });
  };

  if (erreur) return <p className="sec-texte" data-etat="alerte">{erreur}</p>;
  if (!etat) return <p className="sec-texte">Lecture des voix…</p>;

  const { reglages, piper, elevenlabs } = etat;
  const voixPiper = piper.voix.find((v) => v.id === reglages.voix_piper);
  const dl = piper.telechargement;

  return (
    <div className="reglage-synthese">
      <Choix
        libelle="Voix de synthèse"
        options={MOTEURS}
        valeur={reglages.moteur}
        desactive={occupe}
        surChoix={(m) => {
          agir(() => reglerSynthese({ moteur: m }));
        }}
      />

      {reglages.moteur === "navigateur" && <p className="sec-texte">Voix installée sur cet appareil : locale, rien ne part en ligne.</p>}

      {reglages.moteur === "piper" && (
        <div className="reglage-synthese-bloc">
          <p className="sec-texte">
            Voix neuronale sur ce PC, dans un programme séparé. Les phrases sont préparées en parallèle et lues dans l'ordre ; si Piper manque, la
            voix de l'appareil prend le relais.
          </p>
          <label className="reglage-synthese-champ">
            <span>Voix française</span>
            <select
              className="select"
              value={reglages.voix_piper}
              disabled={occupe}
              onChange={(e) => {
                agir(() => reglerSynthese({ voix_piper: e.target.value }));
              }}
            >
              {piper.voix.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.nom}
                  {v.prete ? " · sur le PC" : ""}
                </option>
              ))}
            </select>
          </label>
          <ul className="reglage-lignes">
            <li className="reglage-ligne">
              <span className="point-etat" data-ok={piper.programme} aria-hidden="true" />
              <span className="reglage-ligne-nom">Programme Piper</span>
              <span className="reglage-ligne-valeur">
                {piper.programme ? (
                  "trouvé"
                ) : (
                  <>
                    introuvable : installez-le vous-même (par exemple <code>pipx install piper-tts</code>) ou indiquez son chemin dans{" "}
                    <code>JARVIS2_PIPER</code>
                  </>
                )}
              </span>
            </li>
            <li className="reglage-ligne">
              <span className="point-etat" data-ok={voixPiper?.prete} aria-hidden="true" />
              <span className="reglage-ligne-nom">Voix</span>
              <span className="reglage-ligne-valeur">
                {voixPiper?.prete
                  ? "téléchargée"
                  : dl.statut === "en_cours"
                    ? `téléchargement… ${dl.total ? `${String(Math.min(100, Math.round((dl.octets * 100) / dl.total)))} %` : mo(dl.octets)}`
                    : dl.statut === "echoue"
                      ? `échec : ${dl.raison ?? "raison inconnue"}`
                      : `à télécharger (${mo(voixPiper?.taille ?? 0)}, Hugging Face)`}
              </span>
            </li>
          </ul>
          {!voixPiper?.prete && dl.statut !== "en_cours" && (
            <button
              type="button"
              className="btn btn-mini"
              disabled={occupe}
              onClick={() => {
                agir(telechargerVoixPiper, "Téléchargement de la voix lancé.");
              }}
            >
              {dl.statut === "echoue" ? "Réessayer le téléchargement" : `Télécharger la voix (${mo(voixPiper?.taille ?? 0)})`}
            </button>
          )}
        </div>
      )}

      {reglages.moteur === "elevenlabs" && (
        <div className="reglage-synthese-bloc">
          <p className="sec-texte" data-etat="attention">
            Voix en ligne : chaque phrase lue part chez ElevenLabs avec votre clé, secrets et données personnelles masqués. Une phrase sur un sujet
            ou des souvenirs privés est lue par la voix de l'appareil.
          </p>
          <form
            className="carte-co-cle"
            onSubmit={(e) => {
              e.preventDefault();
              const valeur = cle.trim();
              setCle("");
              agir(() => enregistrerCleElevenLabs(valeur), "Clé ElevenLabs enregistrée dans le coffre.");
            }}
          >
            <label className="visuellement-cache" htmlFor="cle-elevenlabs">
              Clé d'API ElevenLabs
            </label>
            <input
              id="cle-elevenlabs"
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={cle}
              placeholder={elevenlabs.cle ? `Enregistrée (${elevenlabs.apercu ?? "••••"})` : "Coller la clé ElevenLabs"}
              onChange={(e) => {
                setCle(e.target.value);
              }}
            />
            <button type="submit" className="btn btn-mini" disabled={occupe || cle.trim().length < 8}>
              Enregistrer
            </button>
            {elevenlabs.cle && (
              <button
                type="button"
                className="btn btn-discret btn-mini"
                disabled={occupe}
                onClick={() => {
                  agir(supprimerCleElevenLabs, "Clé supprimée du coffre.");
                }}
              >
                Supprimer
              </button>
            )}
          </form>
          <label className="reglage-synthese-champ">
            <span>Identifiant de la voix</span>
            <input
              type="text"
              spellCheck={false}
              autoComplete="off"
              defaultValue={reglages.voix_elevenlabs}
              maxLength={40}
              onBlur={(e) => {
                const v = e.target.value.trim();
                if (v && v !== reglages.voix_elevenlabs) agir(() => reglerSynthese({ voix_elevenlabs: v }), "Voix ElevenLabs choisie.");
              }}
            />
          </label>
        </div>
      )}

      <div className="reglage-synthese-bloc">
        <span className="reglage-synthese-libelle">Couper JARVIS quand je parle par-dessus (mains libres)</span>
        <Choix
          libelle="Couper quand je parle par-dessus"
          options={COUPURE}
          valeur={reglages.coupure ? "oui" : "non"}
          desactive={occupe}
          surChoix={(v) => {
            agir(() => reglerSynthese({ coupure: v === "oui" }));
          }}
        />
        <p className="sec-texte">
          {etat.annulation_echo ? "Annulation d'écho du PC disponible. " : ""}Le micro est comparé à ce que JARVIS dit (annulation d'écho du navigateur, ou
          niveaux sonores ; un casque est reconnu) : dire « stop » arrête la phrase, « silence » coupe la voix.
        </p>
      </div>

      <button
        type="button"
        className="btn btn-discret btn-mini"
        onClick={() => {
          lecteur.arreter();
          lecteur.lire("Bonjour, je suis JARVIS. Voici ma voix.");
        }}
      >
        Essayer la voix
      </button>
    </div>
  );
}
