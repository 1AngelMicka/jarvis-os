import { useCallback, useEffect, useId, useRef, useState } from "react";

import "../styles/bacs.css";

import {
  abandonnerAtelier,
  arreterAtelier,
  bacAtelier,
  cloturerAtelier,
  consigneAtelier,
  creerAtelier,
  demanderAction,
  detecterBacs,
  ErreurApi,
  evenementsAtelier,
  listerAteliers,
  modeleAtelier,
  pauseAtelier,
  relancerAtelier,
  repondreAttente,
  reprendreAtelier,
} from "../api";
import { etatBac, ligneEvenementBac, optionsBac, suffixeBac } from "../bacs";
import type { Atelier, AttenteOutil, BacASable, EvenementAtelier, ModeleAtelier, ReponseAction } from "../types";
import { Fenetre } from "./Palette";
import { VeilleClaude } from "./VeilleClaude";

const STATUTS: Record<Atelier["statut"], { texte: string; ton?: string }> = {
  pret: { texte: "Prêt", ton: "ok" },
  en_cours: { texte: "Au travail", ton: "attention" },
  arrete: { texte: "Arrêté" },
  fusionne: { texte: "Fusionné", ton: "ok" },
  abandonne: { texte: "Abandonné" },
  erreur: { texte: "Erreur", ton: "risque" },
};
const HEURE = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/** Texte d'une valeur du fil (chaîne telle quelle, objet en JSON). */
function txt(v: unknown): string {
  if (typeof v === "string") return v;
  return v === undefined || v === null ? "" : JSON.stringify(v);
}

function ligneEvenement(e: EvenementAtelier, bacs: readonly BacASable[]): string {
  const c = e.contenu;
  switch (e.type) {
    case "cree":
      return `Atelier créé sur la branche ${txt(c.branche)}${c.modele ? ` (modèle ${txt(c.modele)})` : ""}`;
    case "consigne":
      return `Consigne${c.reprise ? " (reprise)" : ""}${suffixeBac(c, bacs)} : ${txt(c.texte)}`;
    case "texte":
      return txt(c.texte);
    case "outil":
      return `Outil ${txt(c.nom)} ${txt(c.entree)}`;
    case "autorisation":
      return `${c.verdict === "allow" ? "Autorisé" : "Refusé"}${suffixeBac(c, bacs)} : ${txt(c.outil)} — ${txt(c.raison)}`;
    case "barriere":
      return `Barrière d'injection : ${txt(c.message)}`;
    case "attente":
      return `En attente de votre accord : ${txt(c.raison)}`;
    case "fin":
      return c.erreur ? `Terminé en erreur : ${txt(c.texte)}` : `Terminé : ${txt(c.texte)}`;
    case "erreur":
      return `Erreur : ${txt(c.message)}${c.journal ? ` — ${txt(c.journal)}` : ""}`;
    case "pause":
      return c.suspendu ? "En pause : Claude Code est suspendu" : "En pause : plus aucune autorisation jusqu'à la reprise";
    case "reprise":
      return "Reprise";
    case "arret":
      return "Arrêté";
    case "relance":
      return c.automatique ? `Relance automatique après un plantage (essai ${txt(c.essai)})` : "Relancé à la main";
    case "conflit":
      return `Conflit : « ${txt(c.fichier)} » est aussi modifié par l'atelier « ${txt(c.nom)} »`;
    case "modele":
      return `Modèle : ${c.modele ? txt(c.modele) : "réglage de Claude Code"}`;
    case "cloture":
      return `Clôturé${c.notes ? ` : ${txt(c.notes)}` : ""}`;
    case "session":
      return `Session Claude Code ouverte${c.modele ? ` (modèle ${txt(c.modele)})` : ""}`;
    default:
      return ligneEvenementBac(e.type, c, bacs) ?? e.type;
  }
}

function Attentes({ attentes, surRepondu }: { attentes: AttenteOutil[]; surRepondu: () => void }) {
  if (!attentes.length) return null;
  return (
    <ul className="cartes-co" aria-label="Autorisations en attente">
      {attentes.map((a) => (
        <li key={a.id} className="carte-co carte-attente">
          <div className="carte-co-tete">
            <h4 className="carte-co-nom">🟡 {a.outil}</h4>
          </div>
          <p className="carte-co-detail">{a.raison}</p>
          <div className="carte-co-actions">
            <button
              type="button"
              className="btn btn-discret btn-mini"
              onClick={() => {
                void repondreAttente(a.id, false).finally(surRepondu);
              }}
            >
              Refuser
            </button>
            <button
              type="button"
              className="btn btn-ambre btn-mini"
              onClick={() => {
                void repondreAttente(a.id, true).finally(surRepondu);
              }}
            >
              Autoriser
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}

function ChoixModele({
  id,
  valeur,
  modeles,
  surChoix,
  desactive = false,
}: {
  id: string;
  valeur: string;
  modeles: ModeleAtelier[];
  surChoix: (m: string) => void;
  desactive?: boolean;
}) {
  const connu = !valeur || modeles.some((m) => m.id === valeur);
  return (
    <>
      <label className="visuellement-cache" htmlFor={id}>
        Modèle de Claude Code
      </label>
      <select
        id={id}
        className="select"
        value={valeur}
        disabled={desactive}
        title="Modèle de Claude Code pour cet atelier"
        onChange={(e) => {
          surChoix(e.target.value);
        }}
      >
        <option value="">Modèle par défaut</option>
        {modeles.map((m) => (
          <option key={m.id} value={m.id}>
            {m.nom}
          </option>
        ))}
        {!connu && <option value={valeur}>{valeur}</option>}
      </select>
    </>
  );
}

/** Confirmation explicite (🟡) avant d'exécuter les commandes d'un atelier sans bac à sable. */
function ConfirmerSansBac({ surConfirmer, surAnnuler }: { surConfirmer: () => void; surAnnuler: () => void }) {
  const id = useId();
  const garder = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    // La fenêtre s'ouvre après ce rendu : le choix prudent reprend le focus
    const minuteur = window.setTimeout(() => garder.current?.focus(), 0);
    return () => {
      window.clearTimeout(minuteur);
    };
  }, []);
  return (
    <Fenetre etiquette="Confirmer : sans bac à sable" surFermer={surAnnuler} className="palette--sans-bac">
      <div className="palette-confirmation" aria-labelledby={`${id}-titre`} aria-describedby={`${id}-texte`}>
        <p className="palette-confirmation-titre" id={`${id}-titre`}>
          🟡 Exécuter les commandes sans bac à sable ?
        </p>
        <div className="palette-confirmation-texte" id={`${id}-texte`}>
          <p>
            Les commandes de Claude Code s'exécuteront <strong>directement sur votre PC</strong>, avec <strong>accès au réseau</strong>, sans
            l'isolement d'un bac à sable.
          </p>
          <p>Ce choix est journalisé dans le fil de l'atelier. Vous pourrez revenir à un bac à sable entre deux consignes.</p>
        </div>
        <div className="palette-confirmation-actions">
          <button type="button" className="btn" ref={garder} onClick={surAnnuler}>
            Garder le bac à sable
          </button>
          <button type="button" className="btn btn-ambre" onClick={surConfirmer}>
            Exécuter sans bac à sable
          </button>
        </div>
      </div>
    </Fenetre>
  );
}

/** Sélecteur « Bac à sable » ; « Sans bac à sable » passe par une confirmation explicite. */
function ChoixBac({
  id,
  valeur,
  bacs,
  surChoix,
  desactive = false,
  pourquoiDesactive,
}: {
  id: string;
  valeur: string;
  bacs: readonly BacASable[];
  surChoix: (choix: string, confirmer: boolean) => void;
  desactive?: boolean;
  pourquoiDesactive?: string;
}) {
  const [demande, setDemande] = useState(false);
  return (
    <>
      <label className="atelier-bac-choix" htmlFor={id}>
        <span>Bac à sable</span>
        <select
          id={id}
          className="select"
          value={valeur}
          disabled={desactive}
          title={desactive ? pourquoiDesactive : "Où s'exécutent les commandes de Claude Code"}
          onChange={(e) => {
            if (e.target.value === "aucun") setDemande(true);
            else surChoix(e.target.value, false);
          }}
        >
          {optionsBac(bacs, valeur).map((o) => (
            <option key={o.valeur} value={o.valeur}>
              {o.libelle}
            </option>
          ))}
        </select>
      </label>
      {demande && (
        <ConfirmerSansBac
          surAnnuler={() => {
            setDemande(false);
          }}
          surConfirmer={() => {
            setDemande(false);
            surChoix("aucun", true);
          }}
        />
      )}
    </>
  );
}

function Detail({
  a,
  modeles,
  bacs,
  surChangement,
  surAction,
}: {
  a: Atelier;
  modeles: ModeleAtelier[];
  /** Absent avec un Core antérieur au point 14 · B 9 */
  bacs: readonly BacASable[] | undefined;
  surChangement: () => void;
  surAction: (r: ReponseAction) => void;
}) {
  const [evenements, setEvenements] = useState<EvenementAtelier[]>([]);
  const [consigne, setConsigne] = useState("");
  const [cloture, setCloture] = useState<string | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const dernier = useRef(0);

  const charger = useCallback(() => {
    evenementsAtelier(a.id, dernier.current)
      .then((r) => {
        if (r.evenements.length) {
          dernier.current = r.evenements[r.evenements.length - 1]?.id ?? dernier.current;
          setEvenements((es) => [...es, ...r.evenements]);
        }
      })
      .catch(() => {
        /* relu au prochain tour */
      });
  }, [a.id]);
  useEffect(charger, [charger]);
  useEffect(() => {
    if (!a.actif) return;
    const minuterie = window.setInterval(charger, 1500);
    return () => {
      window.clearInterval(minuterie);
    };
  }, [a.actif, charger]);

  const termine = a.statut === "fusionne" || a.statut === "abandonne" || a.clos_le !== null;
  const clos = a.clos_le !== null;
  const agir = (appel: Promise<unknown>, siRefus?: (e: ErreurApi) => void) => {
    setErreur(null);
    appel
      .then(() => {
        surChangement();
        charger(); // le fil montre tout de suite la pause, le modèle, la clôture…
      })
      .catch((e: unknown) => {
        if (e instanceof ErreurApi && e.statut === 409 && siRefus) siRefus(e);
        else setErreur(e instanceof Error ? e.message : "Impossible.");
        charger(); // un refus de lancement est aussi journalisé dans le fil
      });
  };
  const bac = etatBac(a, bacs);
  const refusId = `bac-refus-${a.id}`;

  return (
    <div className="atelier-detail">
      <ol className="atelier-fil" aria-live="polite">
        {evenements.map((e) => (
          <li key={e.id} data-type={e.type}>
            <span className="atelier-heure">{HEURE.format(new Date(e.horodatage))}</span>
            <span>{ligneEvenement(e, bacs ?? [])}</span>
          </li>
        ))}
      </ol>
      {erreur && (
        <p className="carte-co-message" role="alert">
          {erreur}
        </p>
      )}
      {clos && a.notes && <p className="carte-co-detail">Notes de clôture : {a.notes}</p>}
      {!clos && cloture !== null && (
        <form
          className="mission-form"
          onSubmit={(ev) => {
            ev.preventDefault();
            agir(cloturerAtelier(a.id, cloture));
            setCloture(null);
          }}
        >
          <label htmlFor={`cloture-${a.id}`} className="sec-texte">
            Notes de clôture (ce qui a été fait, ce qui reste). Le travail non fusionné reste sur la branche {a.branche}.
          </label>
          <textarea
            id={`cloture-${a.id}`}
            rows={3}
            maxLength={10000}
            value={cloture}
            onChange={(ev) => {
              setCloture(ev.target.value);
            }}
          />
          <div className="carte-co-actions">
            <button
              type="button"
              className="btn btn-discret btn-mini"
              onClick={() => {
                setCloture(null);
              }}
            >
              Annuler
            </button>
            <button type="submit" className="btn btn-principal btn-mini">
              Clôturer
            </button>
          </div>
        </form>
      )}
      {!clos && termine && cloture === null && (
        <div className="carte-co-actions">
          <button
            type="button"
            className="btn btn-mini"
            onClick={() => {
              setCloture("");
            }}
          >
            Clôturer avec des notes
          </button>
        </div>
      )}
      {!termine && cloture === null && (
        <form
          className="mission-form"
          onSubmit={(ev) => {
            ev.preventDefault();
            const texte = consigne.trim();
            setConsigne("");
            agir(consigneAtelier(a.id, texte, Boolean(a.session)), (e) => {
              setConsigne(texte); // la consigne refusée n'est pas perdue
              setErreur(`Lancement refusé : ${e.message}`);
            });
          }}
        >
          {bac?.refuse && !a.actif && (
            <p className="atelier-bac-refus" id={refusId} role="status">
              Le prochain lancement sera refusé : {a.bac?.refus}. Démarrez un bac à sable puis « Détecter à nouveau » (section Bacs à sable),
              ou choisissez-en un autre ci-dessous.
            </p>
          )}
          <label className="visuellement-cache" htmlFor={`consigne-${a.id}`}>
            Consigne pour l'atelier {a.nom}
          </label>
          <textarea
            id={`consigne-${a.id}`}
            rows={2}
            value={consigne}
            placeholder={a.session ? "Consigne suivante (la session reprend)…" : "Que doit faire Claude Code dans cet atelier ?"}
            onChange={(ev) => {
              setConsigne(ev.target.value);
            }}
          />
          <div className="carte-co-actions">
            <ChoixModele
              id={`modele-${a.id}`}
              valeur={a.modele ?? ""}
              modeles={modeles}
              desactive={a.actif}
              surChoix={(m) => {
                agir(modeleAtelier(a.id, m || null));
              }}
            />
            {bacs && (
              <ChoixBac
                id={`bac-${a.id}`}
                valeur={a.bac_a_sable ?? "auto"}
                bacs={bacs}
                desactive={a.actif}
                pourquoiDesactive="Modifiable entre deux consignes, quand l'atelier ne travaille pas"
                surChoix={(choix, confirmer) => {
                  agir(bacAtelier(a.id, choix, confirmer));
                }}
              />
            )}
            <button
              type="submit"
              className="btn btn-principal btn-mini"
              disabled={a.actif || !consigne.trim() || Boolean(bac?.refuse)}
              aria-describedby={bac?.refuse && !a.actif ? refusId : undefined}
              title={bac?.refuse ? `Lancement refusé : ${a.bac?.refus ?? ""}` : undefined}
            >
              {a.session ? "Continuer" : "Lancer"}
            </button>
            {a.actif && (
              <button
                type="button"
                className="btn btn-mini"
                title={a.en_pause ? "Claude Code reprend là où il s'était arrêté" : "Claude Code est suspendu ; rien ne lui est autorisé avant la reprise"}
                onClick={() => {
                  agir(a.en_pause ? reprendreAtelier(a.id) : pauseAtelier(a.id));
                }}
              >
                {a.en_pause ? "Reprendre" : "Pause"}
              </button>
            )}
            {a.actif && (
              <button
                type="button"
                className="btn btn-ambre btn-mini"
                onClick={() => {
                  agir(arreterAtelier(a.id));
                }}
              >
                Arrêter
              </button>
            )}
            {!a.actif && (a.statut === "erreur" || a.statut === "arrete") && (
              <button
                type="button"
                className="btn btn-ambre btn-mini"
                title="La dernière consigne repart, dans la même session Claude Code"
                onClick={() => {
                  agir(relancerAtelier(a.id));
                }}
              >
                Relancer
              </button>
            )}
            {!a.actif && (
              <button
                type="button"
                className="btn btn-mini"
                title="Commit du travail puis fusion dans le projet, après votre accord (🟡)"
                onClick={() => {
                  demanderAction({ action: "atelier.fusionner", parametres: { atelier_id: a.id, nom: a.nom, projet: a.projet } })
                    .then(surAction)
                    .catch((e: unknown) => {
                      setErreur(e instanceof Error ? e.message : "Fusion impossible.");
                    });
                }}
              >
                Fusionner (🟡)
              </button>
            )}
            {!a.actif && (
              <button
                type="button"
                className="btn btn-discret btn-mini"
                title="Archive l'atelier avec vos notes ; le travail reste sur sa branche"
                onClick={() => {
                  setCloture("");
                }}
              >
                Clôturer
              </button>
            )}
            {!a.actif && (
              <button
                type="button"
                className="btn btn-discret btn-mini btn-danger"
                title="Retire le dossier de travail ; la branche reste"
                onClick={() => {
                  agir(abandonnerAtelier(a.id));
                }}
              >
                Abandonner
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  );
}

/** Ateliers Claude Code : une session par worktree git, autorisations en direct, fusion approuvée. */
export function VueAteliers({
  surChangement,
  surAction,
  initial,
}: {
  surChangement: (m?: string) => void;
  surAction: (r: ReponseAction) => void;
  /** Atelier à ouvrir à l'arrivée (clic dans le panneau Activité) */
  initial?: string | undefined;
}) {
  const [donnees, setDonnees] = useState<{
    projets: { id: string; nom: string }[];
    modeles: ModeleAtelier[];
    ateliers: Atelier[];
    attentes: AttenteOutil[];
    bacs?: BacASable[];
  } | null>(null);
  const [projet, setProjet] = useState("");
  const [nom, setNom] = useState("");
  const [modele, setModele] = useState("");
  const [bacCreation, setBacCreation] = useState<{ choix: string; confirmer: boolean }>({ choix: "auto", confirmer: false });
  const [detection, setDetection] = useState<{ enCours: boolean; message: string | null }>({ enCours: false, message: null });
  const [ouvert, setOuvert] = useState<string | null>(initial ?? null);
  useEffect(() => {
    if (initial) setOuvert(initial);
  }, [initial]);
  const [erreur, setErreur] = useState<string | null>(null);

  const charger = useCallback(() => {
    listerAteliers()
      .then((r) => {
        setDonnees(r);
        setProjet((p) => p || r.projets[0]?.id || "");
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Lecture impossible.");
      });
  }, []);
  useEffect(charger, [charger]);
  const actifs = donnees?.ateliers.some((a) => a.actif) ?? false;
  useEffect(() => {
    if (!actifs) return;
    const minuterie = window.setInterval(charger, 2000);
    return () => {
      window.clearInterval(minuterie);
    };
  }, [actifs, charger]);

  const detecter = () => {
    setDetection({ enCours: true, message: null });
    detecterBacs()
      .then((r) => {
        setDonnees((d) => (d ? { ...d, bacs: r.bacs } : d));
        const n = r.bacs.filter((b) => b.disponible).length;
        setDetection({ enCours: false, message: n ? `Détection faite : ${String(n)} disponible${n > 1 ? "s" : ""}.` : "Détection faite : aucun disponible." });
        charger(); // les refus des ateliers suivent la nouvelle détection
      })
      .catch((e: unknown) => {
        setDetection({ enCours: false, message: e instanceof Error ? e.message : "Détection impossible." });
      });
  };

  if (erreur) return <p className="securite-erreur">{erreur}</p>;
  if (!donnees) return <div className="squelette squelette--ligne" />;
  const bacs = donnees.bacs;
  const ouverts = donnees.ateliers.filter((a) => a.clos_le === null);
  const clos = donnees.ateliers.filter((a) => a.clos_le !== null);
  const carte = (a: Atelier) => {
    const s = STATUTS[a.statut];
    const bac = a.clos_le === null ? etatBac(a, bacs) : null;
    return (
      <li key={a.id} className="carte-co carte-atelier">
        <div className="carte-co-tete">
          <h4 className="carte-co-nom">{a.nom}</h4>
          <span className="badge-co">{a.projet}</span>
          {a.modele && <span className="badge-co">{a.modele}</span>}
          <span className="badge-co" data-ton={a.en_pause ? "attention" : s.ton}>
            {a.clos_le ? "Clôturé" : a.en_pause ? "En pause" : s.texte}
          </span>
          {a.conflits.length > 0 && (
            <span className="badge-co" data-ton="risque">
              Conflit
            </span>
          )}
        </div>
        <p className="carte-co-detail">
          <code>{a.branche}</code>
        </p>
        {bac && (
          <p className="atelier-bac" data-ton={bac.ton}>
            {bac.texte}
          </p>
        )}
        {a.conflits.length > 0 && (
          <ul className="atelier-conflits" aria-label={`Conflits de l'atelier ${a.nom}`}>
            {a.conflits.map((c) => (
              <li key={c.fichier}>
                <code>{c.fichier}</code> : aussi modifié par {c.ateliers.map((x) => `« ${x.nom} »`).join(", ")}
              </li>
            ))}
          </ul>
        )}
        <div className="carte-co-actions">
          <button
            type="button"
            className="btn btn-discret btn-mini"
            aria-expanded={ouvert === a.id}
            onClick={() => {
              setOuvert(ouvert === a.id ? null : a.id);
            }}
          >
            {ouvert === a.id ? "Fermer" : "Ouvrir"}
          </button>
        </div>
        {ouvert === a.id && <Detail a={a} modeles={donnees.modeles} bacs={bacs} surChangement={charger} surAction={surAction} />}
      </li>
    );
  };
  return (
    <div className="connecteurs">
      <section className="famille-co" aria-labelledby="ateliers-titre">
        <h3 className="sec-titre" id="ateliers-titre">
          Ateliers Claude Code
        </h3>
        <p className="sec-texte">
          Chaque atelier travaille dans son propre dossier (worktree git) et sa branche : votre projet n'est touché qu'à la fusion, après votre
          accord. Toute écriture hors de l'atelier est refusée ; les commandes attendent votre autorisation ici.
          {bacs && " Elles s'exécutent dans un bac à sable (conteneur sans réseau, Windows Sandbox…) : sans bac à sable disponible, l'atelier refuse de se lancer."}
        </p>
        {donnees.projets.length === 0 ? (
          <p className="sec-texte">
            Aucun projet ouvert aux ateliers : déclarez-les dans la configuration locale ([[ateliers.projets]] : id, nom, chemin d'un dépôt
            git).
          </p>
        ) : (
          <form
            className="carte-co-cle"
            onSubmit={(e) => {
              e.preventDefault();
              creerAtelier(projet, nom.trim(), modele || null, bacs ? bacCreation : undefined)
                .then((a) => {
                  setNom("");
                  setBacCreation({ choix: "auto", confirmer: false });
                  setOuvert(a.id);
                  surChangement(`Atelier « ${a.nom} » créé sur la branche ${a.branche}.`);
                  charger();
                })
                .catch((err: unknown) => {
                  setErreur(err instanceof Error ? err.message : "Création impossible.");
                });
            }}
          >
            <label className="visuellement-cache" htmlFor="atelier-projet">
              Projet
            </label>
            <select
              id="atelier-projet"
              className="select"
              value={projet}
              onChange={(e) => {
                setProjet(e.target.value);
              }}
            >
              {donnees.projets.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.nom}
                </option>
              ))}
            </select>
            <label className="visuellement-cache" htmlFor="atelier-nom">
              Nom de l'atelier
            </label>
            <input
              id="atelier-nom"
              value={nom}
              placeholder="Nom de l'atelier (ex. corriger la connexion)"
              onChange={(e) => {
                setNom(e.target.value);
              }}
            />
            <ChoixModele id="atelier-modele" valeur={modele} modeles={donnees.modeles} surChoix={setModele} />
            {bacs && (
              <ChoixBac
                id="atelier-bac"
                valeur={bacCreation.choix}
                bacs={bacs}
                surChoix={(choix, confirmer) => {
                  setBacCreation({ choix, confirmer });
                }}
              />
            )}
            <button type="submit" className="btn btn-mini" disabled={!nom.trim() || !projet}>
              Créer
            </button>
          </form>
        )}
        <Attentes attentes={donnees.attentes} surRepondu={charger} />
        {ouverts.length === 0 && <p className="sec-texte">Aucun atelier en cours : créez-en un pour confier un travail à Claude Code.</p>}
        <ul className="cartes-co">{ouverts.map(carte)}</ul>
        {clos.length > 0 && (
          <details className="ateliers-clos">
            <summary>Ateliers clôturés ({clos.length})</summary>
            <ul className="cartes-co">{clos.map(carte)}</ul>
          </details>
        )}
      </section>
      {bacs && (
        <section className="famille-co" aria-labelledby="bacs-titre">
          <h3 className="sec-titre" id="bacs-titre">
            Bacs à sable
          </h3>
          <p className="sec-texte">
            Détectés sur ce PC. JARVIS ne démarre aucun service : lancez Docker ou Podman vous-même, puis détectez à nouveau.
          </p>
          {bacs.length === 0 ? (
            <p className="sec-texte">Aucun bac à sable connu : installez Docker ou Podman (ou activez Windows Sandbox), puis détectez à nouveau.</p>
          ) : (
            <ul className="bacs-liste" aria-label="Bacs à sable détectés">
              {bacs.map((b) => (
                <li key={b.id}>
                  <span className="bac-nom">{b.nom}</span>
                  <span className="badge-co" data-ton={b.disponible ? "ok" : undefined}>
                    {b.disponible ? "Disponible" : "Indisponible"}
                  </span>
                  {b.raison && <p className="bac-raison">{b.raison}</p>}
                </li>
              ))}
            </ul>
          )}
          <div className="carte-co-actions">
            <button type="button" className="btn btn-mini" disabled={detection.enCours} aria-busy={detection.enCours} onClick={detecter}>
              {detection.enCours ? "Détection…" : "Détecter à nouveau"}
            </button>
            <span className="carte-co-message" role="status">
              {detection.message}
            </span>
          </div>
        </section>
      )}
      <section className="famille-co" aria-labelledby="veille-titre">
        <h3 className="sec-titre" id="veille-titre">
          Vos sessions Claude Code
        </h3>
        <VeilleClaude />
      </section>
    </div>
  );
}
