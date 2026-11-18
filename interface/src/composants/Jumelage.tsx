import { useEffect, useState } from "react";

import { echangerCode, etatAuth, premierAppareil } from "../api";
import { ecrireJeton } from "../auth";
import { Reacteur } from "./Reacteur";

function codeDansAdresse(): string | null {
  const m = /[#&]jumeler=([A-Za-z0-9_-]{10,})/.exec(window.location.hash);
  return m?.[1] ?? null;
}

function nomParDefaut(): string {
  const ua = navigator.userAgent;
  if (/iPhone|iPad/.test(ua)) return "iPhone";
  if (/Android/.test(ua)) return "Téléphone Android";
  if (/Windows/.test(ua)) return "PC Windows";
  if (/Mac/.test(ua)) return "Mac";
  return "Navigateur";
}

/** Écran affiché tant que cet appareil n'est pas autorisé : premier appareil, code de jumelage, ou consignes. */
export function EcranJumelage({ surAutorise }: { surAutorise: () => void }) {
  const [premier, setPremier] = useState<boolean | null>(null);
  const [code, setCode] = useState(codeDansAdresse() ?? "");
  const [nom, setNom] = useState(nomParDefaut());
  const [erreur, setErreur] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(false);

  useEffect(() => {
    // Lien de jumelage ouvert alors que la page l'était déjà : seule l'ancre change
    const surAncre = () => {
      const lu = codeDansAdresse();
      if (lu) setCode(lu);
    };
    window.addEventListener("hashchange", surAncre);
    return () => {
      window.removeEventListener("hashchange", surAncre);
    };
  }, []);

  useEffect(() => {
    etatAuth()
      .then((e) => {
        setPremier(e.premier_possible);
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Core injoignable.");
      });
  }, []);

  const valider = (appel: () => Promise<{ jeton: string }>) => {
    setEnCours(true);
    setErreur(null);
    appel()
      .then((r) => {
        ecrireJeton(r.jeton);
        if (window.location.hash.includes("jumeler=")) history.replaceState(null, "", window.location.pathname);
        surAutorise();
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Jumelage impossible.");
      })
      .finally(() => {
        setEnCours(false);
      });
  };

  return (
    <div className="jumelage">
      <div className="fond" aria-hidden="true">
        <div className="fond-grille" />
      </div>
      <section className="panneau jumelage-carte" aria-labelledby="jumelage-titre">
        <header className="panneau-tete">
          <h1 className="panneau-titre" id="jumelage-titre">
            Associer cet appareil
          </h1>
        </header>
        <div className="jumelage-corps">
          <Reacteur etat="repos" />
          <p className="jumelage-texte">
            JARVIS ne répond qu'aux appareils que vous avez autorisés. Chaque appareil reçoit son propre accès,
            révocable à tout moment.
          </p>
          <label className="champ">
            <span className="champ-etiquette">Nom de cet appareil</span>
            <input
              type="text"
              value={nom}
              maxLength={80}
              onChange={(e) => {
                setNom(e.target.value);
              }}
            />
          </label>
          {premier ? (
            <button
              type="button"
              className="btn btn-principal"
              disabled={enCours || !nom.trim()}
              onClick={() => {
                valider(() => premierAppareil(nom.trim()));
              }}
            >
              Associer ce PC (premier appareil)
            </button>
          ) : (
            <>
              <label className="champ">
                <span className="champ-etiquette">Code de jumelage</span>
                <input
                  type="text"
                  value={code}
                  autoComplete="one-time-code"
                  spellCheck={false}
                  placeholder="Collez le code ou scannez le QR"
                  onChange={(e) => {
                    setCode(e.target.value.trim());
                  }}
                />
              </label>
              <button
                type="button"
                className="btn btn-principal"
                disabled={enCours || code.length < 10 || !nom.trim()}
                onClick={() => {
                  valider(() => echangerCode(code, nom.trim()));
                }}
              >
                Associer
              </button>
              <p className="jumelage-aide">
                Sur un appareil déjà associé : <b>Sécurité › Associer un appareil</b> affiche un QR valable 5 minutes.
                Sur le PC, la commande <code>jarvis2 jumeler</code> donne aussi un lien.
              </p>
            </>
          )}
          {erreur && (
            <p className="jumelage-erreur" role="alert">
              {erreur}
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
