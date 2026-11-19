import { useCallback, useEffect, useRef, useState } from "react";

import "../styles/matin.css";

import { changerReglagesMatin, chercherLieux, lireMatin, lireReglagesMatin, marquerMatinVu } from "../api";
import type { CarteMatin as Carte, LieuTrouve, ModeMatin, ReglagesMatin as Reglages } from "../types";
import type { LecteurVocal } from "../voix";

const MODES: { id: ModeMatin; nom: string }[] = [
  { id: "parle", nom: "Parlé" },
  { id: "texte", nom: "Texte seul" },
  { id: "desactive", nom: "Désactivé" },
];
const STATUTS: Record<string, string> = { ok: "lancée", en_cours: "en cours", erreur: "en échec", ignoree: "ignorée" };

function message(e: unknown, defaut: string): string {
  return e instanceof Error ? e.message : defaut;
}

/** Réglages de l'accueil : mode, « Rejouer l'accueil », lieu de « la maison » (privé : affiché ici seulement). */
function ReglagesMatin({ surRejouer, surNotifier }: { surRejouer: () => void; surNotifier: (m: string) => void }) {
  const [reglages, setReglages] = useState<Reglages | null>(null);
  const [recherche, setRecherche] = useState("");
  const [lieux, setLieux] = useState<LieuTrouve[] | null>(null);
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  useEffect(() => {
    lireReglagesMatin()
      .then(setReglages)
      .catch((e: unknown) => {
        setErreur(message(e, "Réglages illisibles."));
      });
  }, []);

  const changer = (r: Parameters<typeof changerReglagesMatin>[0], confirmation?: string) => {
    setOccupe(true);
    setErreur(null);
    changerReglagesMatin(r)
      .then((n) => {
        setReglages(n);
        setLieux(null);
        if (confirmation) surNotifier(confirmation);
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Réglage impossible."));
      })
      .finally(() => {
        setOccupe(false);
      });
  };

  const chercher = (e: React.FormEvent) => {
    e.preventDefault();
    if (recherche.trim().length < 2) return;
    setOccupe(true);
    setErreur(null);
    chercherLieux(recherche.trim())
      .then((r) => {
        setLieux(r.lieux);
      })
      .catch((err: unknown) => {
        setErreur(message(err, "Recherche impossible."));
      })
      .finally(() => {
        setOccupe(false);
      });
  };

  const positionAppareil = () => {
    if (!("geolocation" in navigator)) {
      setErreur("Cet appareil ne donne pas sa position.");
      return;
    }
    setOccupe(true);
    navigator.geolocation.getCurrentPosition(
      (p) => {
        const arrondi = (v: number) => Math.round(v * 100) / 100; // ~1 km : assez pour la météo
        changer(
          { localisation: { latitude: arrondi(p.coords.latitude), longitude: arrondi(p.coords.longitude), nom: "Position de l'appareil", source: "appareil" } },
          "Maison : position de l'appareil",
        );
      },
      () => {
        setOccupe(false);
        setErreur("Position refusée ou indisponible.");
      },
      { maximumAge: 600_000, timeout: 10_000 },
    );
  };

  if (!reglages) return erreur ? <p className="securite-erreur">{erreur}</p> : <div className="squelette squelette--ligne" aria-busy="true" />;
  const loc = reglages.localisation;
  return (
    <div className="matin-reglages">
      <div className="matin-ligne">
        <div className="segment" role="radiogroup" aria-label="Accueil du matin">
          {MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              role="radio"
              aria-checked={reglages.mode === m.id}
              className="segment-btn"
              disabled={occupe}
              onClick={() => {
                changer({ mode: m.id });
              }}
            >
              {m.nom}
            </button>
          ))}
        </div>
        <button type="button" className="btn btn-discret btn-mini" onClick={surRejouer}>
          Rejouer l'accueil
        </button>
      </div>
      <p className="sec-texte">
        Maison : {loc ? (loc.nom ?? "lieu choisi") : "non choisie"}
        {loc?.source === "configuration" && " (configuration locale)"}. Ce lieu reste privé : il n'est jamais lu à voix haute.
      </p>
      <form className="matin-ligne" onSubmit={chercher}>
        <label className="champ matin-champ">
          <span className="champ-etiquette">Ville</span>
          <input
            value={recherche}
            maxLength={100}
            autoComplete="off"
            onChange={(e) => {
              setRecherche(e.target.value);
            }}
          />
        </label>
        <button type="submit" className="btn btn-mini" disabled={occupe || recherche.trim().length < 2}>
          Chercher
        </button>
        <button type="button" className="btn btn-discret btn-mini" disabled={occupe} onClick={positionAppareil}>
          Position de l'appareil
        </button>
        {loc && loc.source !== "configuration" && (
          <button
            type="button"
            className="btn btn-discret btn-mini"
            disabled={occupe}
            onClick={() => {
              changer({ effacer_localisation: true }, "Lieu effacé");
            }}
          >
            Effacer
          </button>
        )}
      </form>
      {lieux && (
        <ul className="matin-lieux" aria-label="Lieux trouvés">
          {lieux.length === 0 && <li className="sec-texte">Aucun lieu trouvé.</li>}
          {lieux.map((l) => (
            <li key={`${String(l.latitude)},${String(l.longitude)}`}>
              <button
                type="button"
                className="btn btn-discret btn-mini"
                disabled={occupe}
                onClick={() => {
                  const nom = [l.nom, l.region, l.pays].filter(Boolean).join(", ");
                  changer({ localisation: { latitude: l.latitude, longitude: l.longitude, nom, source: "geocodage" } }, "Maison choisie");
                }}
              >
                {[l.nom, l.region, l.pays].filter(Boolean).join(", ")}
              </button>
            </li>
          ))}
        </ul>
      )}
      {erreur && <p className="securite-erreur">{erreur}</p>}
    </div>
  );
}

let rejouerTraite = 0;

interface Props {
  lecteur: LecteurVocal;
  urgence: boolean;
  /** Incrémenté pour rejouer l'accueil (panneau État) ; 0 au démarrage. */
  rejouer: number;
  surNotifier: (m: string) => void;
}

/** Accueil du matin : au premier lancement du jour sur cet appareil, carte + lecture à voix haute si la voix est
 * active (mode « Parlé »). Jamais pendant l'arrêt d'urgence. */
export function AccueilMatin({ lecteur, urgence, rejouer, surNotifier }: Props) {
  const [carte, setCarte] = useState<Extract<Carte, { afficher: true }> | null>(null);
  const [reglages, setReglages] = useState(false);
  const titre = useRef<HTMLHeadingElement>(null);

  const charger = useCallback(
    (forcer: boolean) => {
      lireMatin(forcer)
        .then((c) => {
          if (!c.afficher) {
            if (forcer && c.raison === "urgence") surNotifier("Pas d'accueil pendant l'arrêt d'urgence");
            return;
          }
          setCarte(c);
          if (!forcer) void marquerMatinVu().catch(() => undefined);
          if (c.mode === "parle" && (lecteur.actif || forcer)) lecteur.lire(c.texte_parle);
        })
        .catch(() => {
          /* Core injoignable : l'écran du dialogue le signale déjà */
        });
    },
    [lecteur, surNotifier],
  );

  useEffect(() => {
    if (urgence) return;
    // Un changement de vue remonte ce composant : on ne rejoue que sur une NOUVELLE demande
    const forcer = rejouer > rejouerTraite;
    rejouerTraite = rejouer;
    charger(forcer);
  }, [rejouer, urgence, charger]);

  useEffect(() => {
    if (urgence) {
      setCarte(null);
      lecteur.arreter();
    }
  }, [urgence, lecteur]);

  useEffect(() => {
    if (carte && rejouer > 0) titre.current?.focus();
  }, [carte, rejouer]);

  if (!carte) return null;
  const fermer = () => {
    lecteur.arreter();
    setCarte(null);
    setReglages(false);
  };
  return (
    <section className="matin-carte" aria-labelledby="matin-titre">
      <header className="matin-tete">
        <h3 className="matin-titre" id="matin-titre" tabIndex={-1} ref={titre}>
          {carte.salutation}
        </h3>
        <span className="matin-date">
          {carte.date} · {carte.heure}
        </span>
      </header>
      <p className="matin-meteo">
        {carte.meteo ? (
          <>
            <span className="matin-etiquette">À la maison</span> {carte.meteo.texte}
          </>
        ) : (
          <span className="sec-texte">{carte.lieu_connu ? "Météo indisponible pour l'instant." : "Choisissez « la maison » dans les réglages pour la météo."}</span>
        )}
      </p>
      {carte.recettes.length > 0 && (
        <ul className="matin-recettes" aria-label="Recettes de ce matin">
          {carte.recettes.map((r) => (
            <li key={r.id} className="matin-recette" data-statut={r.statut}>
              {r.nom} <span className="matin-statut">{STATUTS[r.statut] ?? r.statut}</span>
            </li>
          ))}
        </ul>
      )}
      {carte.attention.length > 0 && (
        <ul className="matin-attention" aria-label="Points d'attention">
          {carte.attention.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
      )}
      <div className="matin-actions">
        {carte.mode === "parle" && lecteur.disponible && (
          <button
            type="button"
            className="btn btn-discret btn-mini"
            onClick={() => {
              lecteur.arreter();
              lecteur.lire(carte.texte_parle);
            }}
          >
            Écouter
          </button>
        )}
        <button
          type="button"
          className="btn btn-discret btn-mini"
          aria-expanded={reglages}
          onClick={() => {
            setReglages((r) => !r);
          }}
        >
          Réglages
        </button>
        <button type="button" className="btn btn-principal btn-mini" onClick={fermer}>
          Fermer
        </button>
      </div>
      {reglages && (
        <ReglagesMatin
          surNotifier={surNotifier}
          surRejouer={() => {
            charger(true);
          }}
        />
      )}
    </section>
  );
}
