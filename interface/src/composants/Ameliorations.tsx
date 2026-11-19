import { useCallback, useEffect, useState } from "react";

import {
  EVENEMENT_DEMANDE_DECIDEE,
  apercuAmelioration,
  demanderMiseEnService,
  demanderRetourArriere,
  listerAmeliorations,
  ouvrirAtelierAmelioration,
  proposerAmelioration,
  rejeterAmelioration,
  testerAmelioration,
} from "../api";
import "../styles/ameliorations.css";
import type { Amelioration, ApercuAmelioration, EssaiTests, ProjetAmelioration, ReponseAction, StatutAmelioration } from "../types";

const STATUTS: Record<StatutAmelioration, { texte: string; ton?: string }> = {
  proposee: { texte: "Suggérée" },
  en_atelier: { texte: "En atelier", ton: "attention" },
  en_service: { texte: "En service", ton: "ok" },
  retiree: { texte: "Retirée" },
  rejetee: { texte: "Écartée" },
};
const DATE = new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short" });
const ETATS_FICHIER = { ajoute: "ajouté", modifie: "modifié", supprime: "supprimé" } as const;

function message(e: unknown, defaut: string): string {
  return e instanceof Error ? e.message : defaut;
}

function court(commit: string | null): string {
  return commit ? commit.slice(0, 10) : "—";
}

/** Résultat d'un essai des tests (réussi, échec, durée, sortie dépliable). */
function Essai({ essai, titre }: { essai: Partial<EssaiTests>; titre: string }) {
  if (essai.reussi === undefined) return null;
  return (
    <div className="amelio-essai" data-ton={essai.reussi ? "ok" : "risque"}>
      <p className="carte-co-detail">
        {titre} : <strong>{essai.reussi ? "réussis" : "en échec"}</strong>
        {essai.code !== null && essai.code !== undefined && ` (code ${String(essai.code)})`}
        {essai.duree !== undefined && ` en ${String(essai.duree)} s`}
        {essai.le && ` — ${DATE.format(new Date(essai.le))}`}
      </p>
      {essai.contenu_change && (
        <p className="carte-co-detail">
          Les tests ont modifié le dossier de l'atelier : cet essai ne vaut pas pour le contenu vu. Faites ignorer par git les fichiers
          qu'ils écrivent (.gitignore), puis relancez-les.
        </p>
      )}
      {essai.sortie && (
        <details className="amelio-details">
          <summary>Sortie des tests</summary>
          <pre className="amelio-pre">{essai.sortie}</pre>
        </details>
      )}
    </div>
  );
}

function Apercu({
  a,
  surChangement,
  surAction,
}: {
  a: Amelioration;
  surChangement: () => void;
  surAction: (r: ReponseAction) => void;
}) {
  const [vue, setVue] = useState<ApercuAmelioration | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  // Tests lancés d'ici : l'aperçu est relu jusqu'à l'arrivée d'un nouvel essai (horodatage différent)
  const [essaiAttendu, setEssaiAttendu] = useState<string | null>(null);

  const charger = useCallback(() => {
    apercuAmelioration(a.id)
      .then((v) => {
        setVue(v);
        setErreur(null);
        setEssaiAttendu((attendu) => (attendu !== null && (v.tests.le ?? "") !== attendu ? null : attendu));
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Aperçu impossible."));
      });
  }, [a.id]);
  // Relu quand les tests se terminent (la liste se rafraîchit pendant qu'ils tournent)
  useEffect(charger, [charger, a.tests_en_cours]);
  const travaille = (vue?.atelier_actif ?? false) || a.tests_en_cours || essaiAttendu !== null;
  useEffect(() => {
    if (!travaille) return;
    const minuterie = window.setInterval(charger, 1500);
    return () => {
      window.clearInterval(minuterie);
    };
  }, [travaille, charger]);

  if (erreur && !vue) return <p className="carte-co-message">{erreur}</p>;
  if (!vue) return <div className="squelette squelette--ligne" />;
  const ajouts = vue.fichiers.reduce((n, f) => n + (f.ajouts ?? 0), 0);
  const retraits = vue.fichiers.reduce((n, f) => n + (f.retraits ?? 0), 0);
  const testsOk = !vue.commande_tests || (vue.tests_a_jour && vue.tests.reussi === true);
  const pret = !vue.atelier_actif && vue.fichiers.length > 0 && testsOk && !a.tests_en_cours;
  const raison = vue.atelier_actif
    ? "L'atelier travaille encore."
    : vue.fichiers.length === 0
      ? "L'atelier n'a encore rien changé."
      : !testsOk
        ? "Les tests doivent réussir sur ce contenu exact."
        : null;

  return (
    <div className="amelio-apercu">
      <p className="carte-co-detail">
        Branche <code>{vue.branche}</code>
        {vue.atelier_actif && " — Claude Code travaille…"}
      </p>
      {vue.fichiers.length === 0 ? (
        <p className="sec-texte">Aucun changement pour l'instant.</p>
      ) : (
        <>
          <p className="carte-co-detail">
            {vue.fichiers.length} fichier(s), <span className="amelio-plus">+{ajouts}</span> <span className="amelio-moins">−{retraits}</span>
          </p>
          <ul className="amelio-fichiers" aria-label="Fichiers changés">
            {vue.fichiers.map((f) => (
              <li key={f.chemin}>
                <code>{f.chemin}</code>
                <span className="amelio-etat">{ETATS_FICHIER[f.etat]}</span>
                {f.ajouts === null ? (
                  <span className="amelio-etat">binaire</span>
                ) : (
                  <span className="amelio-compte">
                    <span className="amelio-plus">+{f.ajouts}</span> <span className="amelio-moins">−{f.retraits}</span>
                  </span>
                )}
              </li>
            ))}
          </ul>
          <details className="amelio-details">
            <summary>Différences{vue.diff_tronque ? " (tronquées)" : ""}</summary>
            <pre className="amelio-pre amelio-diff">
              {vue.diff.split("\n").map((ligne, i) => (
                <span
                  key={i}
                  data-ligne={ligne.startsWith("+") && !ligne.startsWith("+++") ? "plus" : ligne.startsWith("-") && !ligne.startsWith("---") ? "moins" : undefined}
                >
                  {ligne}
                  {"\n"}
                </span>
              ))}
            </pre>
          </details>
        </>
      )}
      {vue.commande_tests ? (
        <>
          <p className="carte-co-detail">
            Tests du projet : <code>{vue.commande_tests}</code>
            {a.tests_en_cours
              ? " — en cours…"
              : vue.tests.reussi !== undefined && !vue.tests_a_jour && !vue.tests.contenu_change
                ? " — le contenu a changé depuis le dernier essai"
                : ""}
          </p>
          <Essai essai={vue.tests} titre="Dernier essai" />
        </>
      ) : (
        <p className="carte-co-detail">Aucune commande de tests configurée pour ce projet ([[ateliers.projets]] tests).</p>
      )}
      {erreur && <p className="carte-co-message">{erreur}</p>}
      <div className="carte-co-actions">
        <button type="button" className="btn btn-discret btn-mini" onClick={charger}>
          Relire
        </button>
        {vue.commande_tests && (
          <button
            type="button"
            className="btn btn-mini"
            disabled={a.tests_en_cours || essaiAttendu !== null || vue.atelier_actif || vue.fichiers.length === 0}
            onClick={() => {
              setErreur(null);
              testerAmelioration(a.id)
                .then(() => {
                  setEssaiAttendu(vue.tests.le ?? "");
                  surChangement();
                })
                .catch((e: unknown) => {
                  setErreur(message(e, "Tests impossibles."));
                });
            }}
          >
            {a.tests_en_cours || essaiAttendu !== null ? "Tests en cours…" : "Lancer les tests"}
          </button>
        )}
        <button
          type="button"
          className="btn btn-ambre btn-mini"
          disabled={!pret}
          title={raison ?? "Fusion locale dans le projet après votre accord (🟡) ; jamais de push"}
          onClick={() => {
            setErreur(null);
            demanderMiseEnService(a.id)
              .then((r) => {
                surAction(r);
                surChangement();
              })
              .catch((e: unknown) => {
                setErreur(message(e, "Demande impossible."));
              });
          }}
        >
          Mettre en service (🟡)
        </button>
      </div>
      {raison && <p className="sec-texte">{raison}</p>}
    </div>
  );
}

function Carte({
  a,
  projets,
  surChangement,
  surAction,
  surOuvrirAtelier,
}: {
  a: Amelioration;
  projets: ProjetAmelioration[];
  surChangement: (m?: string) => void;
  surAction: (r: ReponseAction) => void;
  surOuvrirAtelier: (id: string) => void;
}) {
  const [apercu, setApercu] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const s = STATUTS[a.statut];
  const agir = (appel: Promise<unknown>, ok?: string) => {
    setErreur(null);
    appel
      .then(() => {
        surChangement(ok);
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Impossible."));
      });
  };
  const nomProjet = projets.find((p) => p.id === a.projet)?.nom ?? a.projet;
  return (
    <li className="carte-co carte-amelio">
      <div className="carte-co-tete">
        <h4 className="carte-co-nom">{a.titre}</h4>
        <span className="badge-co">{nomProjet}</span>
        <span className="badge-co" data-origine={a.origine}>
          {a.origine === "jarvis" ? "Suggérée par JARVIS" : "Votre idée"}
        </span>
        <span className="badge-co" data-ton={s.ton}>
          {s.texte}
        </span>
      </div>
      <p className="carte-co-detail">Pourquoi : {a.raison}</p>
      {a.description && <p className="carte-co-detail amelio-description">{a.description}</p>}
      {a.statut === "en_service" && (
        <p className="carte-co-detail">
          En service depuis {a.en_service_le ? DATE.format(new Date(a.en_service_le)) : "—"} : commit d'avant <code>{court(a.commit_avant)}</code>,
          fusion <code>{court(a.commit_service)}</code>
        </p>
      )}
      {a.statut === "retiree" && (
        <>
          <p className="carte-co-detail">
            Retirée le {a.retiree_le ? DATE.format(new Date(a.retiree_le)) : "—"} : retour au commit d'avant <code>{court(a.commit_avant)}</code>{" "}
            par <code>{court(a.commit_retour)}</code> (historique gardé)
          </p>
          {a.tests_en_cours ? (
            <p className="carte-co-detail">Tests du projet après le retour arrière : en cours…</p>
          ) : (
            a.tests.retour && <Essai essai={a.tests.retour} titre="Tests du projet après le retour arrière" />
          )}
        </>
      )}
      {erreur && <p className="carte-co-message">{erreur}</p>}
      <div className="carte-co-actions">
        {a.statut === "proposee" && (
          <button
            type="button"
            className="btn btn-principal btn-mini"
            title="Ouvre un atelier sur sa propre branche et confie la tâche à Claude Code"
            onClick={() => {
              agir(ouvrirAtelierAmelioration(a.id, true), `Atelier ouvert pour « ${a.titre} ».`);
              setApercu(true);
            }}
          >
            Réaliser dans un atelier
          </button>
        )}
        {a.statut === "proposee" && (
          <button
            type="button"
            className="btn btn-discret btn-mini"
            title="Ouvre l'atelier sur sa propre branche sans rien lancer : vous donnez la consigne vous-même dans Ateliers"
            onClick={() => {
              agir(ouvrirAtelierAmelioration(a.id, false), `Atelier ouvert pour « ${a.titre} » (rien n'est lancé).`);
              setApercu(true);
            }}
          >
            Ouvrir sans lancer
          </button>
        )}
        {a.statut === "en_atelier" && (
          <button
            type="button"
            className="btn btn-mini"
            aria-expanded={apercu}
            onClick={() => {
              setApercu(!apercu);
            }}
          >
            {apercu ? "Fermer l'aperçu" : "Aperçu"}
          </button>
        )}
        {a.atelier_id && a.statut === "en_atelier" && (
          <button
            type="button"
            className="btn btn-discret btn-mini"
            onClick={() => {
              if (a.atelier_id) surOuvrirAtelier(a.atelier_id);
            }}
          >
            Voir l'atelier
          </button>
        )}
        {a.statut === "en_service" && (
          <button
            type="button"
            className="btn btn-ambre btn-mini"
            title="Revient au commit d'avant (git revert : rien n'est effacé), après votre accord (🟡), puis relance les tests"
            onClick={() => {
              setErreur(null);
              demanderRetourArriere(a.id)
                .then((r) => {
                  surAction(r);
                  surChangement();
                })
                .catch((e: unknown) => {
                  setErreur(message(e, "Demande impossible."));
                });
            }}
          >
            Revenir en arrière (🟡)
          </button>
        )}
        {(a.statut === "proposee" || a.statut === "en_atelier") && (
          <button
            type="button"
            className="btn btn-discret btn-mini"
            title={a.atelier_id ? "Écarte l'idée ; le dossier de l'atelier est retiré, sa branche reste" : "Écarte l'idée"}
            onClick={() => {
              agir(rejeterAmelioration(a.id), `« ${a.titre} » écartée.`);
            }}
          >
            Écarter
          </button>
        )}
      </div>
      {apercu && a.statut === "en_atelier" && (
        <Apercu
          a={a}
          surChangement={() => {
            surChangement();
          }}
          surAction={surAction}
        />
      )}
    </li>
  );
}

/** Amélioration continue : suggestions (de JARVIS ou de vous), réalisées en atelier, aperçu testé, mise en service et retour
 * arrière approuvés (🟡). */
export function VueAmeliorations({
  surChangement,
  surAction,
  surOuvrirAtelier,
}: {
  surChangement: (m?: string) => void;
  surAction: (r: ReponseAction) => void;
  surOuvrirAtelier: (id: string) => void;
}) {
  const [donnees, setDonnees] = useState<{ disponible: boolean; projets: ProjetAmelioration[]; ameliorations: Amelioration[] } | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [projet, setProjet] = useState("");
  const [titre, setTitre] = useState("");
  const [raison, setRaison] = useState("");
  const [description, setDescription] = useState("");

  const charger = useCallback(() => {
    listerAmeliorations()
      .then((r) => {
        setDonnees(r);
        setProjet((p) => p || r.projets[0]?.id || "");
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Lecture impossible."));
      });
  }, []);
  useEffect(charger, [charger]);
  // Mise en service ou retour arrière approuvés depuis la file des demandes : relire
  useEffect(() => {
    window.addEventListener(EVENEMENT_DEMANDE_DECIDEE, charger);
    return () => {
      window.removeEventListener(EVENEMENT_DEMANDE_DECIDEE, charger);
    };
  }, [charger]);
  const enCours = donnees?.ameliorations.some((a) => a.tests_en_cours) ?? false;
  useEffect(() => {
    if (!enCours) return;
    const minuterie = window.setInterval(charger, 2000);
    return () => {
      window.clearInterval(minuterie);
    };
  }, [enCours, charger]);

  if (erreur && !donnees) return <p className="securite-erreur">{erreur}</p>;
  if (!donnees) return <div className="squelette squelette--ligne" />;
  const changer = (m?: string) => {
    charger();
    if (m) surChangement(m);
  };
  const ouvertes = donnees.ameliorations.filter((a) => a.statut === "proposee" || a.statut === "en_atelier");
  const enService = donnees.ameliorations.filter((a) => a.statut === "en_service");
  const passees = donnees.ameliorations.filter((a) => a.statut === "retiree" || a.statut === "rejetee");
  const carte = (a: Amelioration) => (
    <Carte key={a.id} a={a} projets={donnees.projets} surChangement={changer} surAction={surAction} surOuvrirAtelier={surOuvrirAtelier} />
  );

  return (
    <div className="connecteurs">
      <section className="famille-co" aria-labelledby="amelio-titre">
        <h3 className="sec-titre" id="amelio-titre">
          Amélioration continue
        </h3>
        <p className="sec-texte">
          Une idée, de JARVIS ou de vous, est réalisée dans un atelier sur sa propre branche. Vous voyez les différences et le résultat des
          tests avant de la mettre en service (fusion locale, jamais envoyée ailleurs) ; un retour arrière revient au commit d'avant. Ces deux
          étapes attendent votre accord (🟡).
        </p>
        {!donnees.disponible || donnees.projets.length === 0 ? (
          <p className="sec-texte">
            Aucun projet ouvert aux ateliers : déclarez-les dans la configuration locale ([[ateliers.projets]] : id, nom, chemin, et
            facultativement tests et dossier_tests).
          </p>
        ) : (
          <form
            className="amelio-form"
            onSubmit={(e) => {
              e.preventDefault();
              setErreur(null);
              proposerAmelioration({ projet, titre: titre.trim(), raison: raison.trim(), description: description.trim(), origine: "utilisateur" })
                .then((a) => {
                  setTitre("");
                  setRaison("");
                  setDescription("");
                  changer(`Suggestion « ${a.titre} » ajoutée.`);
                })
                .catch((err: unknown) => {
                  setErreur(message(err, "Ajout impossible."));
                });
            }}
          >
            <div className="amelio-ligne">
              <label className="visuellement-cache" htmlFor="amelio-projet">
                Projet
              </label>
              <select
                id="amelio-projet"
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
              <label className="visuellement-cache" htmlFor="amelio-titre-champ">
                Amélioration
              </label>
              <input
                id="amelio-titre-champ"
                value={titre}
                maxLength={200}
                placeholder="Amélioration (ex. accélérer le démarrage)"
                onChange={(e) => {
                  setTitre(e.target.value);
                }}
              />
            </div>
            <label className="visuellement-cache" htmlFor="amelio-raison">
              Raison
            </label>
            <input
              id="amelio-raison"
              value={raison}
              maxLength={2000}
              placeholder="Pourquoi (obligatoire)"
              onChange={(e) => {
                setRaison(e.target.value);
              }}
            />
            <label className="visuellement-cache" htmlFor="amelio-description">
              Détails pour Claude Code
            </label>
            <textarea
              id="amelio-description"
              rows={2}
              maxLength={10000}
              value={description}
              placeholder="Détails pour Claude Code (facultatif)"
              onChange={(e) => {
                setDescription(e.target.value);
              }}
            />
            <div className="carte-co-actions">
              <button type="submit" className="btn btn-mini" disabled={!titre.trim() || !raison.trim() || !projet}>
                Proposer
              </button>
            </div>
          </form>
        )}
        {erreur && <p className="carte-co-message">{erreur}</p>}
        {ouvertes.length === 0 && <p className="sec-texte">Aucune amélioration en attente.</p>}
        <ul className="cartes-co">{ouvertes.map(carte)}</ul>
      </section>
      {enService.length > 0 && (
        <section className="famille-co" aria-labelledby="amelio-service">
          <h3 className="sec-titre" id="amelio-service">
            En service
          </h3>
          <ul className="cartes-co">{enService.map(carte)}</ul>
        </section>
      )}
      {passees.length > 0 && (
        <details className="ateliers-clos">
          <summary>Retirées ou écartées ({passees.length})</summary>
          <ul className="cartes-co">{passees.map(carte)}</ul>
        </details>
      )}
    </div>
  );
}
