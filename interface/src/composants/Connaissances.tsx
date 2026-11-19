import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { lancerMission } from "../api";
import {
  creerDomaine,
  extraireDomaine,
  lireDomaine,
  arbreCarte,
  lireMotsCles,
  listerDomaines,
  modifierDomaine,
  reviserDomaine,
} from "../connaissances";
import type { DetailDomaine, EntreeJournalDomaine, Noeud, NouveauDomaine, ResumeDomaine, SourceCitee } from "../connaissances";
import { enLigne, TexteRiche } from "../texte";
import "../styles/connaissances.css";

const DATE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const ONGLETS = [
  { id: "carte", nom: "Carte" },
  { id: "fiches", nom: "Fiches" },
  { id: "questions", nom: "Questions" },
  { id: "journal", nom: "Journal" },
] as const;
type Onglet = (typeof ONGLETS)[number]["id"];
const TYPES_JOURNAL: Record<EntreeJournalDomaine["type"], { texte: string; ton?: string }> = {
  creation: { texte: "création" },
  modification: { texte: "modification" },
  extraction: { texte: "extraction", ton: "ok" },
  report: { texte: "reportée", ton: "attention" },
  revue: { texte: "révision", ton: "ok" },
  erreur: { texte: "erreur", ton: "risque" },
};

function message(e: unknown, defaut: string): string {
  return e instanceof Error ? e.message : defaut;
}

/** Niveau 0 à 10 : dix segments, lisible sans la couleur (valeur écrite à côté). */
function Jauge({ niveau, grande = false }: { niveau: number; grande?: boolean }) {
  return (
    <span className="jauge" data-grande={grande || undefined} role="img" aria-label={`Niveau ${String(niveau)} sur 10`}>
      <span className="jauge-segments" aria-hidden="true">
        {Array.from({ length: 10 }, (_, i) => (
          <span key={i} className="jauge-segment" data-plein={i < niveau || undefined} />
        ))}
      </span>
      <span className="jauge-valeur" aria-hidden="true">
        {niveau}/10
      </span>
    </span>
  );
}

function Branches({ noeuds, profondeur = 0 }: { noeuds: Noeud[]; profondeur?: number }): ReactNode {
  return (
    <ul className="carte-branches" data-profondeur={Math.min(profondeur, 3)}>
      {noeuds.map((n, i) => (
        <li key={i} className="carte-noeud">
          <span className="carte-libelle">{enLigne(n.texte, `c${String(profondeur)}-${String(i)}`)}</span>
          {n.enfants.length > 0 && <Branches noeuds={n.enfants} profondeur={profondeur + 1} />}
        </li>
      ))}
    </ul>
  );
}

function Carte({ source }: { source: string }) {
  if (!source.trim()) {
    return <p className="sec-texte">Pas encore de carte : lancez une mission de recherche sur ce domaine, puis « Extraire ».</p>;
  }
  const { arbre, reste } = arbreCarte(source);
  return (
    <div className="carte-concepts">
      {reste && (
        <div className="carte-texte">
          <TexteRiche source={reste} />
        </div>
      )}
      {arbre.length > 0 && <Branches noeuds={arbre} />}
    </div>
  );
}

function Sources({ sources }: { sources: SourceCitee[] }) {
  const sures = sources.filter((s) => /^https?:\/\//.test(s.url));
  if (!sures.length) return null;
  return (
    <ul className="savoir-sources" aria-label="Sources">
      {sures.map((s) => (
        <li key={s.url}>
          <a href={s.url} target="_blank" rel="noopener noreferrer">
            {s.titre || s.url}
          </a>
        </li>
      ))}
    </ul>
  );
}

function FormulaireDomaine({
  initial,
  surValider,
  surAnnuler,
  libelle,
}: {
  initial?: NouveauDomaine;
  surValider: (d: NouveauDomaine) => Promise<void>;
  surAnnuler: () => void;
  libelle: string;
}) {
  const [nom, setNom] = useState(initial?.nom ?? "");
  const [motsCles, setMotsCles] = useState(initial?.mots_cles.join(", ") ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [prive, setPrive] = useState(initial?.prive ?? false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);
  const id = initial ? "domaine-modif" : "domaine-nouveau";
  return (
    <form
      className="savoir-form"
      onSubmit={(e) => {
        e.preventDefault();
        setErreur(null);
        setEnvoi(true);
        surValider({ nom: nom.trim(), description: description.trim(), mots_cles: lireMotsCles(motsCles), prive })
          .catch((err: unknown) => {
            setErreur(message(err, "Enregistrement impossible."));
          })
          .finally(() => {
            setEnvoi(false);
          });
      }}
    >
      <label className="savoir-champ" htmlFor={`${id}-nom`}>
        <span>Nom du domaine</span>
        <input
          id={`${id}-nom`}
          value={nom}
          maxLength={80}
          placeholder="ex. Potager"
          autoComplete="off"
          onChange={(e) => {
            setNom(e.target.value);
          }}
        />
      </label>
      <label className="savoir-champ" htmlFor={`${id}-mots`}>
        <span>Mots-clés</span>
        <input
          id={`${id}-mots`}
          value={motsCles}
          placeholder="tomate, semis, compost"
          autoComplete="off"
          onChange={(e) => {
            setMotsCles(e.target.value);
          }}
        />
        <small>Une mission ou un message qui les nomme relève du domaine.</small>
      </label>
      <label className="savoir-champ" htmlFor={`${id}-desc`}>
        <span>Description (facultatif)</span>
        <textarea
          id={`${id}-desc`}
          rows={2}
          value={description}
          maxLength={1000}
          onChange={(e) => {
            setDescription(e.target.value);
          }}
        />
      </label>
      <label className="carte-co-case">
        <input
          type="checkbox"
          checked={prive}
          onChange={(e) => {
            setPrive(e.target.checked);
          }}
        />
        <span>
          Domaine privé : traité par une IA locale seulement, jamais envoyé à une IA externe, et sans bases scientifiques publiques.
        </span>
      </label>
      {erreur && (
        <p className="securite-erreur" role="alert">
          {erreur}
        </p>
      )}
      <div className="carte-co-actions">
        <button type="submit" className="btn btn-principal btn-mini" disabled={!nom.trim() || envoi}>
          {libelle}
        </button>
        <button type="button" className="btn btn-discret btn-mini" onClick={surAnnuler}>
          Annuler
        </button>
      </div>
    </form>
  );
}

function DerniereRevision({ entree, domaine, surLancee }: { entree: EntreeJournalDomaine; domaine: DetailDomaine; surLancee: (m: string) => void }) {
  const [lancees, setLancees] = useState<string[]>([]);
  const [erreur, setErreur] = useState<string | null>(null);
  const { lacunes = [], missions = [], questions = [] } = entree.contenu;
  const maitrisees = questions.filter((q) => q.maitrise).length;
  return (
    <section className="savoir-revue" aria-labelledby="savoir-revue-titre">
      <div className="savoir-revue-tete">
        <h4 className="savoir-sous-titre" id="savoir-revue-titre">
          Dernière révision
        </h4>
        <time className="carte-co-detail" dateTime={entree.horodatage}>
          {DATE.format(new Date(entree.horodatage))}
        </time>
      </div>
      {questions.length > 0 && (
        <p className="sec-texte">
          {maitrisees} question{maitrisees > 1 ? "s" : ""} de contrôle maîtrisée{maitrisees > 1 ? "s" : ""} sur {questions.length}.
        </p>
      )}
      {lacunes.length > 0 && (
        <ul className="savoir-lacunes" aria-label="Lacunes">
          {lacunes.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      )}
      {missions.length > 0 && (
        <>
          <p className="sec-texte">Missions suggérées : rien n'est lancé sans vous.</p>
          <ul className="savoir-suggestions">
            {missions.map((m) => (
              <li key={m}>
                <span>{m}</span>
                <button
                  type="button"
                  className="btn btn-mini"
                  disabled={lancees.includes(m)}
                  onClick={() => {
                    setErreur(null);
                    lancerMission("recherche", m, { domaine_id: domaine.id })
                      .then(() => {
                        setLancees((l) => [...l, m]);
                        surLancee("Recherche lancée : le domaine s'enrichira à la fin.");
                      })
                      .catch((e: unknown) => {
                        setErreur(message(e, "Lancement impossible."));
                      });
                  }}
                >
                  {lancees.includes(m) ? "Lancée" : "Lancer la recherche"}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      {erreur && (
        <p className="securite-erreur" role="alert">
          {erreur}
        </p>
      )}
    </section>
  );
}

function Detail({
  id,
  surRetour,
  surChangement,
  surListe,
}: {
  id: string;
  surRetour: () => void;
  surChangement: (m?: string) => void;
  surListe: () => void;
}) {
  const [d, setD] = useState<DetailDomaine | null>(null);
  const [onglet, setOnglet] = useState<Onglet>("carte");
  const [edition, setEdition] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [attente, setAttente] = useState<"revision" | "extraction" | null>(null);

  const charger = useCallback(() => {
    lireDomaine(id)
      .then((r) => {
        setD(r);
        setErreur(null);
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Domaine illisible."));
      });
  }, [id]);
  useEffect(() => {
    setD(null);
    setEdition(false);
    setAttente(null);
    charger();
  }, [charger]);

  // Pendant une extraction ou une révision : relecture régulière jusqu'à la nouvelle entrée du journal
  const dernierJournal = d?.journal[0]?.id;
  useEffect(() => {
    if (!attente && !d?.en_cours) return;
    const depart = dernierJournal;
    const minuterie = window.setInterval(() => {
      lireDomaine(id)
        .then((r) => {
          setD(r);
          const nouvelle = r.journal[0];
          if (!r.en_cours && nouvelle && nouvelle.id !== depart && (attente !== "revision" || nouvelle.type === "revue" || nouvelle.type === "erreur")) {
            setAttente(null);
            surListe();
          }
        })
        .catch(() => {
          /* nouvel essai au prochain battement */
        });
    }, 2500);
    const limite = window.setTimeout(() => {
      setAttente(null);
    }, 300_000);
    return () => {
      window.clearInterval(minuterie);
      window.clearTimeout(limite);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- seule l'entrée du journal au départ compte
  }, [attente, d?.en_cours, id]);

  if (erreur && !d) {
    return (
      <div className="savoir-detail-corps">
        <p className="securite-erreur" role="alert">
          {erreur}
        </p>
        <button type="button" className="btn btn-mini" onClick={charger}>
          Réessayer
        </button>
      </div>
    );
  }
  if (!d) {
    return (
      <div className="savoir-detail-corps">
        <div className="squelette squelette--ligne" />
        <div className="squelette squelette--ligne" />
      </div>
    );
  }
  const revue = d.journal.find((j) => j.type === "revue");
  const enAttente = d.extractions.filter((e) => e.statut !== "faite").length;
  const occupe = attente !== null || d.en_cours;
  const nombres: Record<Onglet, number | null> = { carte: null, fiches: d.fiches.length, questions: d.questions.length, journal: null };

  return (
    <div className="savoir-detail-corps">
      <button type="button" className="btn btn-discret btn-mini savoir-retour" onClick={surRetour}>
        ← Domaines
      </button>
      <header className="savoir-entete">
        <div className="savoir-entete-titre">
          <h3 className="savoir-nom">{d.nom}</h3>
          {d.prive && (
            <span className="badge-co" data-ton="attention" title="IA locale seulement">
              privé
            </span>
          )}
          {enAttente > 0 && (
            <span className="badge-co" data-ton="attention" title="Missions pas encore intégrées">
              {enAttente} en attente
            </span>
          )}
        </div>
        {d.description && <p className="sec-texte">{d.description}</p>}
        {d.mots_cles.length > 0 && (
          <ul className="savoir-mots" aria-label="Mots-clés">
            {d.mots_cles.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        )}
        <div className="savoir-niveau">
          <Jauge niveau={d.niveau} grande />
          <p className="carte-co-detail">
            {d.extrait_le ? `extrait le ${DATE.format(new Date(d.extrait_le))}` : "rien d'extrait pour l'instant"}
            {d.revu_le && ` · révisé le ${DATE.format(new Date(d.revu_le))}`}
          </p>
        </div>
        <div className="carte-co-actions savoir-actions">
          <button
            type="button"
            className="btn btn-principal btn-mini"
            disabled={occupe}
            title="Questions de contrôle, score, lacunes et missions suggérées"
            onClick={() => {
              setErreur(null);
              reviserDomaine(d.id)
                .then(() => {
                  setAttente("revision");
                  surChangement(`Révision de « ${d.nom} » lancée.`);
                })
                .catch((e: unknown) => {
                  setErreur(message(e, "Révision impossible."));
                });
            }}
          >
            {attente === "revision" ? "Révision…" : "Réviser"}
          </button>
          <button
            type="button"
            className="btn btn-mini"
            disabled={occupe}
            title="Verse dans le domaine les missions de recherche qui en relèvent"
            onClick={() => {
              setErreur(null);
              extraireDomaine(d.id)
                .then((r) => {
                  setAttente("extraction");
                  surChangement(r.rattachees ? `${String(r.rattachees)} mission(s) rattachée(s) : extraction en cours.` : "Extraction lancée.");
                })
                .catch((e: unknown) => {
                  setErreur(message(e, "Extraction impossible."));
                });
            }}
          >
            {attente === "extraction" || d.en_cours ? "Extraction…" : "Extraire"}
          </button>
          <button
            type="button"
            className="btn btn-discret btn-mini"
            aria-expanded={edition}
            onClick={() => {
              setEdition((e) => !e);
            }}
          >
            Modifier
          </button>
        </div>
        {erreur && (
          <p className="securite-erreur" role="alert">
            {erreur}
          </p>
        )}
      </header>

      {edition && (
        <FormulaireDomaine
          initial={{ nom: d.nom, description: d.description, mots_cles: d.mots_cles, prive: d.prive }}
          libelle="Enregistrer"
          surAnnuler={() => {
            setEdition(false);
          }}
          surValider={async (v) => {
            setD({ ...d, ...(await modifierDomaine(d.id, v)) });
            setEdition(false);
            surListe();
            surChangement("Domaine modifié.");
          }}
        />
      )}

      {revue && <DerniereRevision entree={revue} domaine={d} surLancee={surChangement} />}

      <div className="segment savoir-onglets" role="tablist" aria-label="Contenu du domaine">
        {ONGLETS.map((o) => (
          <button
            key={o.id}
            type="button"
            role="tab"
            id={`savoir-onglet-${o.id}`}
            aria-selected={onglet === o.id}
            aria-controls="savoir-panneau"
            className="segment-btn"
            data-actif={onglet === o.id || undefined}
            onClick={() => {
              setOnglet(o.id);
            }}
          >
            {o.nom}
            {nombres[o.id] !== null && <span className="puce-nombre">{nombres[o.id]}</span>}
          </button>
        ))}
      </div>

      <div className="savoir-panneau" role="tabpanel" id="savoir-panneau" aria-labelledby={`savoir-onglet-${onglet}`}>
        {onglet === "carte" && <Carte source={d.carte} />}
        {onglet === "fiches" &&
          (d.fiches.length === 0 ? (
            <p className="sec-texte">Aucune fiche : elles naissent des missions de recherche du domaine.</p>
          ) : (
            <ul className="savoir-fiches">
              {d.fiches.map((f) => (
                <li key={f.id}>
                  <details className="savoir-fiche">
                    <summary>{f.concept}</summary>
                    <div className="souvenir-texte">
                      <TexteRiche source={f.contenu} />
                    </div>
                    <Sources sources={f.sources} />
                  </details>
                </li>
              ))}
            </ul>
          ))}
        {onglet === "questions" &&
          (d.questions.length === 0 ? (
            <p className="sec-texte">Aucune question de contrôle pour l'instant.</p>
          ) : (
            <>
              <p className="sec-texte">Testez-vous : ouvrez une question pour voir la réponse attendue.</p>
              <ol className="savoir-questions">
                {d.questions.map((q) => (
                  <li key={q.id}>
                    <details className="savoir-fiche">
                      <summary>{q.question}</summary>
                      <p className="savoir-reponse">{enLigne(q.reponse, q.id)}</p>
                      <Sources sources={q.sources} />
                    </details>
                  </li>
                ))}
              </ol>
            </>
          ))}
        {onglet === "journal" && (
          <ol className="savoir-journal">
            {d.journal.map((j) => {
              const t = TYPES_JOURNAL[j.type];
              return (
                <li key={j.id}>
                  <span className="badge-co" data-ton={t.ton}>
                    {t.texte}
                  </span>
                  <span className="savoir-journal-texte">{j.resume}</span>
                  <time className="carte-co-detail" dateTime={j.horodatage}>
                    {DATE.format(new Date(j.horodatage))}
                  </time>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </div>
  );
}

/** Vue Connaissances : domaines (liste) et, à côté (bureau) ou à la place (téléphone), le domaine choisi. */
export function VueConnaissances({ surChangement }: { surChangement: (m?: string) => void }) {
  const [domaines, setDomaines] = useState<ResumeDomaine[] | null>(null);
  const [scientifique, setScientifique] = useState(false);
  const [choisi, setChoisi] = useState<string | null>(null);
  const [creation, setCreation] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const charger = useCallback(() => {
    listerDomaines()
      .then((r) => {
        setDomaines(r.domaines);
        setScientifique(r.scientifique);
        setErreur(null);
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Connaissances illisibles."));
      });
  }, []);
  useEffect(charger, [charger]);

  return (
    <div className="savoir" data-detail={choisi ? "" : undefined}>
      <aside className="savoir-liste" aria-labelledby="savoir-domaines">
        <div className="savoir-liste-tete">
          <h3 className="sec-titre" id="savoir-domaines">
            Domaines
          </h3>
          {!creation && (
            <button
              type="button"
              className="btn btn-mini"
              onClick={() => {
                setCreation(true);
              }}
            >
              Nouveau domaine
            </button>
          )}
        </div>
        <p className="sec-texte">
          Chaque mission de recherche qui relève d'un domaine l'enrichit : carte, fiches, questions de contrôle et niveau.
          {scientifique ? " Sources : web et bases scientifiques (OpenAlex, arXiv, PubMed, Europe PMC)." : ""}
        </p>
        {creation && (
          <FormulaireDomaine
            libelle="Créer"
            surAnnuler={() => {
              setCreation(false);
            }}
            surValider={async (v) => {
              const r = await creerDomaine(v);
              setCreation(false);
              setChoisi(r.id);
              charger();
              surChangement(`Domaine « ${v.nom} » créé.`);
            }}
          />
        )}
        {erreur && (
          <p className="securite-erreur" role="alert">
            {erreur}
          </p>
        )}
        {!domaines ? (
          <div className="squelette squelette--ligne" />
        ) : domaines.length === 0 ? (
          !creation && <p className="sec-texte">Aucun domaine : créez-en un (ex. « Potager », mots-clés « tomate, semis »).</p>
        ) : (
          <ul className="savoir-domaines">
            {domaines.map((d) => (
              <li key={d.id}>
                <button
                  type="button"
                  className="savoir-domaine"
                  aria-current={choisi === d.id || undefined}
                  onClick={() => {
                    setChoisi(d.id);
                  }}
                >
                  <span className="savoir-domaine-tete">
                    <span className="savoir-domaine-nom">{d.nom}</span>
                    {d.prive && <span className="badge-co" data-ton="attention">privé</span>}
                    {(d.en_cours || d.en_attente > 0) && (
                      <span className="badge-co" data-ton="attention">
                        {d.en_cours ? "extraction…" : `${String(d.en_attente)} en attente`}
                      </span>
                    )}
                  </span>
                  <Jauge niveau={d.niveau} />
                  <span className="carte-co-detail">
                    {d.nb_fiches} fiche{d.nb_fiches > 1 ? "s" : ""} · {d.nb_questions} question{d.nb_questions > 1 ? "s" : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>
      <section className="savoir-detail" aria-label="Domaine choisi">
        {choisi ? (
          <Detail
            id={choisi}
            surRetour={() => {
              setChoisi(null);
            }}
            surChangement={surChangement}
            surListe={charger}
          />
        ) : (
          <p className="sec-texte savoir-vide">Choisissez un domaine pour voir sa carte, ses fiches et ses questions de contrôle.</p>
        )}
      </section>
    </div>
  );
}

/** Sous une réponse du dialogue : domaine évoqué, son niveau, et « Réviser » (lancé seulement sur un clic). */
export function DomainesEvoques({ domaines }: { domaines: { id: string; nom: string; niveau: number }[] }) {
  const [lances, setLances] = useState<string[]>([]);
  const [erreur, setErreur] = useState<string | null>(null);
  return (
    <>
      {domaines.map((d) => (
        <span key={d.id} className="msg-meta msg-domaine">
          {d.nom} · {d.niveau}/10
          <button
            type="button"
            className="lien-btn msg-domaine-btn"
            disabled={lances.includes(d.id)}
            title="Questions de contrôle, score, lacunes : le rapport arrive dans Agents et Savoir"
            onClick={() => {
              setErreur(null);
              reviserDomaine(d.id)
                .then(() => {
                  setLances((l) => [...l, d.id]);
                })
                .catch((e: unknown) => {
                  setErreur(message(e, "Révision impossible."));
                });
            }}
          >
            {lances.includes(d.id) ? "révision lancée" : "réviser"}
          </button>
        </span>
      ))}
      {erreur && (
        <span className="msg-meta msg-meta--ambre" role="alert">
          {erreur}
        </span>
      )}
    </>
  );
}
