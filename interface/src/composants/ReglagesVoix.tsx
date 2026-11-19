import { useCallback, useEffect, useRef, useState } from "react";

import { lancerTelechargement } from "../api";
import { Enregistreur } from "../voix";
import {
  ajouterEmpreinte,
  type EtatDictee,
  type EtatProprietaire,
  type EtatTranscription,
  ecrireCorrections,
  lireCorrections,
  lireDictee,
  lireProprietaire,
  lireTranscription,
  NOMS_STYLES,
  prechaufferVoix,
  RACCOURCI_DICTEE,
  RACCOURCI_DICTEE_SECOURS,
  reglerDictee,
  reglerProprietaire,
  retirerEmpreinte,
  type StyleDictee,
} from "../voixAvancee";
import "../styles/voix-avancee.css";

const DUREE_EMPREINTE = 6000;
const DATE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function message(e: unknown, defaut: string): string {
  return e instanceof Error ? e.message : defaut;
}

function Ligne({ nom, ok, children }: { nom: string; ok?: boolean | undefined; children: React.ReactNode }) {
  return (
    <li className="reglage-ligne">
      <span className="point-etat" data-ok={ok} aria-hidden="true" />
      <span className="reglage-ligne-nom">{nom}</span>
      <span className="reglage-ligne-valeur">{children}</span>
    </li>
  );
}

/** Transcription : modèle, carte ou processeur, préchauffage, disjoncteur, fin de tour. */
export function EtatTranscriptionVoix() {
  const [etat, setEtat] = useState<EtatTranscription | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [occupe, setOccupe] = useState(false);
  const charger = useCallback(() => {
    lireTranscription()
      .then((e) => {
        setEtat(e);
        setErreur(null);
      })
      .catch((e: unknown) => {
        setErreur(message(e, "État de la transcription illisible."));
      });
  }, []);
  useEffect(charger, [charger]);

  const prechauffer = () => {
    setOccupe(true);
    prechaufferVoix()
      .then(charger)
      .catch((e: unknown) => {
        setErreur(message(e, "Préchauffage impossible."));
      })
      .finally(() => {
        setOccupe(false);
      });
  };

  if (!etat) return erreur ? <p className="securite-erreur">{erreur}</p> : <div className="squelette squelette--ligne" />;
  const { appareil, disjoncteur } = etat;
  return (
    <div className="voix-k3">
      <ul className="reglage-lignes">
        <Ligne nom="Modèle" ok={etat.telecharge}>
          Whisper « {etat.modele} » int8{etat.telecharge ? "" : " — non téléchargé"}
          {etat.conseille ? "" : " (small ou medium conseillés)"}
        </Ligne>
        <Ligne nom="Calcul" ok={appareil.famille !== "processeur" || !appareil.raison}>
          {appareil.libelle}
          {appareil.raison ? ` — ${appareil.raison}` : ""}
        </Ligne>
        <Ligne nom="Préchauffage" ok={etat.prechauffe}>
          {etat.prechauffe ? `prêt${etat.chargement_ms !== null ? ` (chargé en ${etat.chargement_ms} ms)` : ""}` : "pas encore : la première phrase attendra le chargement"}
        </Ligne>
        <Ligne nom="Disjoncteur" ok={!disjoncteur.ouvert}>
          {disjoncteur.ouvert ? `en pause encore ${Math.ceil(disjoncteur.reste_s ?? 0)} s après des échecs` : "fermé (tout va bien)"}
        </Ligne>
        <Ligne nom="Fin de tour" ok>
          {etat.fin_de_tour.modele ? `règle + petit modèle local ${etat.fin_de_tour.modele}` : "règle sur le texte (petit modèle : JARVIS2_MODELE_FIN_TOUR)"}
        </Ligne>
      </ul>
      <div className="voix-k3-actions">
        <button type="button" className="btn btn-mini" disabled={occupe || etat.prechauffe || !etat.telecharge} onClick={prechauffer}>
          {occupe ? "Préchauffage…" : "Préchauffer"}
        </button>
      </div>
      {erreur && <p className="securite-erreur">{erreur}</p>}
      <p className="sec-texte">
        Silence filtré par Silero avant Whisper, phrases toutes faites écartées (« Sous-titres réalisés par… »), texte anticipé dès la fin de
        la phrase. Mesure étape par étape : <code>jarvis2 docteur --latence</code>.
      </p>
    </div>
  );
}

/** Reconnaissance du propriétaire : désactivée par défaut, empreintes locales, fermée si indisponible. */
export function ReglageProprietaire() {
  const [etat, setEtat] = useState<EtatProprietaire | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [enregistre, setEnregistre] = useState(false);
  const minuterie = useRef<number | undefined>(undefined);

  const charger = useCallback(() => {
    lireProprietaire()
      .then((e) => {
        setEtat(e);
        setErreur(null);
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Réglage illisible."));
      });
  }, []);
  useEffect(charger, [charger]);
  const telechargement = etat?.modele.statut === "en_cours";
  useEffect(() => {
    if (!telechargement) return;
    const m = window.setInterval(charger, 1500);
    return () => {
      window.clearInterval(m);
    };
  }, [telechargement, charger]);
  useEffect(
    () => () => {
      window.clearTimeout(minuterie.current);
    },
    [],
  );

  const appliquer = (promesse: Promise<EtatProprietaire>) => {
    promesse
      .then((e) => {
        setEtat(e);
        setErreur(null);
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Réglage impossible."));
      });
  };

  const enregistrer = () => {
    const micro = new Enregistreur();
    micro
      .demarrer()
      .then(() => {
        setEnregistre(true);
        minuterie.current = window.setTimeout(() => {
          void micro.arreter().then((audio) => {
            setEnregistre(false);
            appliquer(ajouterEmpreinte(audio));
          });
        }, DUREE_EMPREINTE);
      })
      .catch(() => {
        setErreur("Micro refusé ou indisponible.");
      });
  };

  if (!etat) return erreur ? <p className="securite-erreur">{erreur}</p> : <div className="squelette squelette--ligne" />;
  const modelePret = etat.modele.statut === "pret";
  const plein = etat.empreintes.length >= etat.empreintes_max;
  return (
    <div className="voix-k3">
      <p className="sec-texte">
        Avant d'accepter une action 🟡 ou 🔴 demandée à voix haute, JARVIS vérifie que c'est votre voix. Les empreintes sont calculées et
        gardées sur ce PC (jamais l'audio, jamais envoyées). Activée mais indisponible, la reconnaissance <strong>refuse</strong> ces actions
        à la voix : faites-les à l'écran.
      </p>
      <label className="carte-co-case carte-co-case--ligne">
        <input
          type="checkbox"
          checked={etat.actif}
          onChange={(e) => {
            appliquer(reglerProprietaire({ actif: e.target.checked }));
          }}
        />
        <span>Reconnaître ma voix pour les actions 🟡🔴 dites à voix haute</span>
      </label>
      {etat.ferme && (
        <p className="voix-k3-alerte" role="alert">
          Fermée : {etat.raison}. Les actions 🟡🔴 demandées à la voix sont refusées.
        </p>
      )}
      <ul className="reglage-lignes">
        <Ligne nom="Modèle ECAPA-TDNN" ok={modelePret}>
          {modelePret
            ? "téléchargé (≈ 25 Mo, sur ce PC)"
            : etat.modele.statut === "en_cours"
              ? `téléchargement… ${etat.modele.total ? Math.round((etat.modele.octets * 100) / etat.modele.total) : 0} %`
              : etat.modele.statut === "echoue"
                ? `échec : ${etat.modele.raison ?? "inconnu"}`
                : "non téléchargé"}
        </Ligne>
        <Ligne nom="Empreintes" ok={etat.empreintes.length > 0}>
          {etat.empreintes.length} sur {etat.empreintes_max}
        </Ligne>
      </ul>
      <div className="voix-k3-actions">
        {!modelePret && (
          <button
            type="button"
            className="btn btn-mini"
            disabled={telechargement}
            onClick={() => {
              lancerTelechargement("proprietaire")
                .then(charger)
                .catch((e: unknown) => {
                  setErreur(message(e, "Téléchargement impossible."));
                });
            }}
          >
            Télécharger le modèle (≈ 25 Mo)
          </button>
        )}
        <button type="button" className="btn btn-mini" disabled={!modelePret || enregistre || plein} onClick={enregistrer}>
          {enregistre ? "Parlez normalement… (6 s)" : "Ajouter une empreinte"}
        </button>
      </div>
      {etat.empreintes.length > 0 && (
        <ul className="voix-k3-liste" aria-label="Empreintes de voix">
          {etat.empreintes.map((e) => (
            <li key={e.id}>
              <span>
                {DATE.format(new Date(e.cree_le))} · {e.parole_s.toFixed(1)} s de parole
              </span>
              <button
                type="button"
                className="btn btn-mini"
                onClick={() => {
                  appliquer(retirerEmpreinte(e.id));
                }}
              >
                Retirer
              </button>
            </li>
          ))}
        </ul>
      )}
      <label className="voix-k3-seuil">
        <span>
          Exigence : <output>{etat.seuil.toFixed(2)}</output>
        </span>
        <input
          type="range"
          min={0.3}
          max={0.8}
          step={0.05}
          value={etat.seuil}
          onChange={(e) => {
            setEtat({ ...etat, seuil: Number(e.target.value) });
          }}
          onPointerUp={(e) => {
            appliquer(reglerProprietaire({ seuil: Number((e.target as HTMLInputElement).value) }));
          }}
          onKeyUp={(e) => {
            appliquer(reglerProprietaire({ seuil: Number((e.target as HTMLInputElement).value) }));
          }}
        />
      </label>
      <p className="sec-texte">Plusieurs empreintes (pièce calme, bruit, matin, soir) rendent la reconnaissance plus sûre.</p>
      {erreur && <p className="securite-erreur">{erreur}</p>}
    </div>
  );
}

/** Dictée globale : raccourci maintenu, dictionnaire de corrections, mise en forme selon l'application. */
export function ReglageDictee() {
  const [etat, setEtat] = useState<EtatDictee | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [texte, setTexte] = useState("");
  const [programme, setProgramme] = useState("");
  const [style, setStyle] = useState<StyleDictee>("phrase");
  const [enregistre, setEnregistre] = useState(false);

  const recevoir = useCallback((e: EtatDictee) => {
    setEtat(e);
    setTexte(ecrireCorrections(e.corrections));
    setErreur(null);
  }, []);
  useEffect(() => {
    lireDictee()
      .then(recevoir)
      .catch((e: unknown) => {
        setErreur(message(e, "Réglage illisible."));
      });
  }, [recevoir]);

  const regler = (r: Parameters<typeof reglerDictee>[0]) => {
    reglerDictee(r)
      .then((e) => {
        recevoir(e);
        if (r.corrections) {
          setEnregistre(true);
          window.setTimeout(() => {
            setEnregistre(false);
          }, 1800);
        }
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Réglage impossible."));
      });
  };

  if (!etat) return erreur ? <p className="securite-erreur">{erreur}</p> : <div className="squelette squelette--ligne" />;
  const styles = Object.entries(etat.styles);
  return (
    <div className="voix-k3">
      <p className="sec-texte">
        Dans l'application de bureau, maintenez <kbd>{RACCOURCI_DICTEE}</kbd> (sinon <kbd>{RACCOURCI_DICTEE_SECOURS}</kbd>), parlez, relâchez : le texte,
        transcrit sur ce PC, est collé là où se trouve le curseur. Le presse-papiers est remis ensuite.
      </p>
      <label className="carte-co-case carte-co-case--ligne">
        <input
          type="checkbox"
          checked={etat.actif}
          onChange={(e) => {
            regler({ actif: e.target.checked });
          }}
        />
        <span>Activer la dictée globale</span>
      </label>
      {!etat.collage_possible && <p className="voix-k3-alerte">Le collage ne se fait que depuis le PC lui-même.</p>}
      <label className="champ voix-k3-champ">
        <span className="champ-etiquette">Corrections (une par ligne : entendu → écrit)</span>
        <textarea
          rows={4}
          spellCheck={false}
          placeholder="jarvice → JARVIS"
          value={texte}
          onChange={(e) => {
            setTexte(e.target.value);
          }}
        />
      </label>
      <div className="voix-k3-actions">
        <button
          type="button"
          className="btn btn-mini"
          onClick={() => {
            regler({ corrections: lireCorrections(texte) });
          }}
        >
          Enregistrer les corrections
        </button>
        {enregistre && <span className="voix-k3-ok">Enregistré</span>}
      </div>
      <p className="sec-texte">
        Mise en forme selon l'application : éditeurs de code et terminaux tels quels, messageries sans point final, le reste en phrases.
        Dites « virgule », « point d'interrogation », « à la ligne ».
      </p>
      {styles.length > 0 && (
        <ul className="voix-k3-liste" aria-label="Mise en forme par application">
          {styles.map(([p, s]) => (
            <li key={p}>
              <span className="voix-k3-mono">{p}</span>
              <span>{NOMS_STYLES[s]}</span>
              <button
                type="button"
                className="btn btn-mini"
                onClick={() => {
                  regler({ styles: Object.fromEntries(styles.filter(([autre]) => autre !== p)) });
                }}
              >
                Retirer
              </button>
            </li>
          ))}
        </ul>
      )}
      <form
        className="voix-k3-ajout"
        onSubmit={(e) => {
          e.preventDefault();
          const nom = programme.trim().toLowerCase();
          if (!nom) return;
          regler({ styles: { ...etat.styles, [nom.endsWith(".exe") || nom.includes(".") ? nom : `${nom}.exe`]: style } });
          setProgramme("");
        }}
      >
        <label className="champ">
          <span className="champ-etiquette">Application</span>
          <input
            value={programme}
            placeholder="notepad.exe"
            maxLength={100}
            onChange={(e) => {
              setProgramme(e.target.value);
            }}
          />
        </label>
        <label className="champ">
          <span className="champ-etiquette">Mise en forme</span>
          <select
            className="select"
            value={style}
            onChange={(e) => {
              setStyle(e.target.value as StyleDictee);
            }}
          >
            {etat.styles_possibles.map((s) => (
              <option key={s} value={s}>
                {NOMS_STYLES[s]}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="btn btn-mini" disabled={!programme.trim()}>
          Ajouter
        </button>
      </form>
      {erreur && <p className="securite-erreur">{erreur}</p>}
    </div>
  );
}
