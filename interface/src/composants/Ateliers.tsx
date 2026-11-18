import { useCallback, useEffect, useRef, useState } from "react";

import {
  abandonnerAtelier,
  arreterAtelier,
  consigneAtelier,
  creerAtelier,
  demanderAction,
  evenementsAtelier,
  listerAteliers,
  repondreAttente,
} from "../api";
import type { Atelier, AttenteOutil, EvenementAtelier, ReponseAction } from "../types";

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

function ligneEvenement(e: EvenementAtelier): string {
  const c = e.contenu;
  switch (e.type) {
    case "consigne":
      return `Consigne${c.reprise ? " (reprise)" : ""} : ${txt(c.texte)}`;
    case "texte":
      return txt(c.texte);
    case "outil":
      return `Outil ${txt(c.nom)} ${txt(c.entree)}`;
    case "autorisation":
      return `${c.verdict === "allow" ? "Autorisé" : "Refusé"} : ${txt(c.outil)} — ${txt(c.raison)}`;
    case "attente":
      return `En attente de votre accord : ${txt(c.raison)}`;
    case "fin":
      return c.erreur ? `Terminé en erreur : ${txt(c.texte)}` : `Terminé : ${txt(c.texte)}`;
    case "erreur":
      return `Erreur : ${txt(c.message)}`;
    default:
      return e.type;
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

function Detail({ a, surChangement, surAction }: { a: Atelier; surChangement: () => void; surAction: (r: ReponseAction) => void }) {
  const [evenements, setEvenements] = useState<EvenementAtelier[]>([]);
  const [consigne, setConsigne] = useState("");
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

  const termine = a.statut === "fusionne" || a.statut === "abandonne";
  const agir = (appel: Promise<unknown>) => {
    setErreur(null);
    appel.then(surChangement).catch((e: unknown) => {
      setErreur(e instanceof Error ? e.message : "Impossible.");
    });
  };

  return (
    <div className="atelier-detail">
      <ol className="atelier-fil" aria-live="polite">
        {evenements.map((e) => (
          <li key={e.id} data-type={e.type}>
            <span className="atelier-heure">{HEURE.format(new Date(e.horodatage))}</span>
            <span>{ligneEvenement(e)}</span>
          </li>
        ))}
      </ol>
      {erreur && <p className="carte-co-message">{erreur}</p>}
      {!termine && (
        <form
          className="mission-form"
          onSubmit={(ev) => {
            ev.preventDefault();
            const texte = consigne.trim();
            setConsigne("");
            agir(consigneAtelier(a.id, texte, Boolean(a.session)));
          }}
        >
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
            <button type="submit" className="btn btn-principal btn-mini" disabled={a.actif || !consigne.trim()}>
              {a.session ? "Continuer" : "Lancer"}
            </button>
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
export function VueAteliers({ surChangement, surAction }: { surChangement: (m?: string) => void; surAction: (r: ReponseAction) => void }) {
  const [donnees, setDonnees] = useState<{ projets: { id: string; nom: string }[]; ateliers: Atelier[]; attentes: AttenteOutil[] } | null>(null);
  const [projet, setProjet] = useState("");
  const [nom, setNom] = useState("");
  const [ouvert, setOuvert] = useState<string | null>(null);
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

  if (erreur) return <p className="securite-erreur">{erreur}</p>;
  if (!donnees) return <div className="squelette squelette--ligne" />;
  return (
    <div className="connecteurs">
      <section className="famille-co" aria-labelledby="ateliers-titre">
        <h3 className="sec-titre" id="ateliers-titre">
          Ateliers Claude Code
        </h3>
        <p className="sec-texte">
          Chaque atelier travaille dans son propre dossier (worktree git) et sa branche : votre projet n'est touché qu'à la fusion, après votre
          accord. Toute écriture hors de l'atelier est refusée ; les commandes attendent votre autorisation ici.
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
              creerAtelier(projet, nom.trim())
                .then((a) => {
                  setNom("");
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
            <button type="submit" className="btn btn-mini" disabled={!nom.trim() || !projet}>
              Créer
            </button>
          </form>
        )}
        <Attentes attentes={donnees.attentes} surRepondu={charger} />
        <ul className="cartes-co">
          {donnees.ateliers.map((a) => {
            const s = STATUTS[a.statut];
            return (
              <li key={a.id} className="carte-co carte-atelier">
                <div className="carte-co-tete">
                  <h4 className="carte-co-nom">{a.nom}</h4>
                  <span className="badge-co">{a.projet}</span>
                  <span className="badge-co" data-ton={s.ton}>
                    {s.texte}
                  </span>
                </div>
                <p className="carte-co-detail">
                  <code>{a.branche}</code>
                </p>
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
                {ouvert === a.id && <Detail a={a} surChangement={charger} surAction={surAction} />}
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}
