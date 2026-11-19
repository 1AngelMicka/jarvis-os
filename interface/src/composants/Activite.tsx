import { type FormEvent, useEffect, useState } from "react";

import { creerChantier, demanderAction, listerChantiers, modifierChantier, rouvrirChantier, terminerChantier } from "../api";
import type { Activite, Chantier, EtapeChantier, ReponseAction, StatutChantier } from "../types";

const STATUT_CHANTIER: Record<StatutChantier, { texte: string; ton?: "ok" | "attention" | "risque" }> = {
  propose: { texte: "Proposé" },
  a_faire: { texte: "À faire" },
  en_cours: { texte: "En cours", ton: "attention" },
  en_attente_utilisateur: { texte: "À vous", ton: "attention" },
  bloque: { texte: "Bloqué", ton: "risque" },
  termine: { texte: "Fait", ton: "ok" },
  abandonne: { texte: "Abandonné" },
};
const STATUT_MISSION: Record<string, { texte: string; ton?: "ok" | "attention" | "risque" }> = {
  en_file: { texte: "En file", ton: "attention" },
  en_cours: { texte: "En cours", ton: "attention" },
  terminee: { texte: "Terminée", ton: "ok" },
  echec: { texte: "Échec", ton: "risque" },
  annulee: { texte: "Annulée" },
};
const TYPE_MISSION: Record<string, string> = { recherche: "Recherche", brainstorm: "Brainstorm", revue: "Revue", projet: "Projet" };
const STATUT_ATELIER: Record<string, string> = { pret: "Prêt", en_cours: "Au travail", arrete: "En pause", erreur: "Erreur" };
const DATE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export type CibleActivite = { vue: "agents"; type: "mission" | "creation"; id: string } | { vue: "ateliers"; id: string };

interface Props {
  activite: Activite | null;
  erreur: string | null;
  /** Relire l'activité tout de suite (après une action, ou en direct pendant qu'un travail tourne) */
  surRafraichir: () => void;
  surOuvrir: (cible: CibleActivite) => void;
  surAction: (r: ReponseAction) => void;
  surNotifier: (message: string) => void;
}

function Progression({ valeur, libelle }: { valeur: number; libelle: string }) {
  return (
    <div className="progression" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={valeur} aria-label={libelle}>
      <span style={{ width: `${String(valeur)}%` }} />
    </div>
  );
}

function DetailChantier({ c, surFait, surNotifier }: { c: Chantier; surFait: () => void; surNotifier: (m: string) => void }) {
  const [etapes, setEtapes] = useState<EtapeChantier[]>(c.etapes);
  const [nouvelle, setNouvelle] = useState("");
  const [occupe, setOccupe] = useState(false);
  useEffect(() => {
    setEtapes(c.etapes);
  }, [c.etapes]);

  const enregistrer = (liste: EtapeChantier[]) => {
    setEtapes(liste); // affichage immédiat, le Core recalcule la progression
    setOccupe(true);
    modifierChantier(c.id, { etapes: liste })
      .then(surFait)
      .catch((e: unknown) => {
        setEtapes(c.etapes);
        surNotifier(e instanceof Error ? e.message : "Modification impossible.");
      })
      .finally(() => {
        setOccupe(false);
      });
  };

  const ajouter = (e: FormEvent) => {
    e.preventDefault();
    const titre = nouvelle.trim();
    if (!titre) return;
    setNouvelle("");
    enregistrer([...etapes, { titre, fait: false }]);
  };

  return (
    <div className="chantier-detail" id={`chantier-${c.id}`}>
      {c.description && <p className="chantier-description">{c.description}</p>}
      {c.motif && <p className="chantier-description">{c.motif}</p>}
      {etapes.length > 0 && (
        <ul className="chantier-etapes" aria-label="Étapes">
          {etapes.map((e, i) => (
            <li key={`${String(i)}-${e.titre}`}>
              <label className="chantier-etape" data-fait={e.fait || undefined}>
                <input
                  type="checkbox"
                  checked={e.fait}
                  disabled={occupe}
                  onChange={() => {
                    enregistrer(etapes.map((x, j) => (j === i ? { ...x, fait: !x.fait } : x)));
                  }}
                />
                <span>{e.titre}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
      <form className="chantier-ajout" onSubmit={ajouter}>
        <input
          type="text"
          value={nouvelle}
          maxLength={300}
          placeholder="Ajouter une étape"
          aria-label={`Nouvelle étape pour « ${c.titre} »`}
          onChange={(e) => {
            setNouvelle(e.target.value);
          }}
        />
        <button type="submit" className="btn btn-discret btn-mini" disabled={!nouvelle.trim() || occupe}>
          Ajouter
        </button>
      </form>
    </div>
  );
}

/** Activité : ce qui tourne en ce moment (chantiers, missions, ateliers, créations récentes), rafraîchi en direct. */
export function PanneauActivite({ activite, erreur, surRafraichir, surOuvrir, surAction, surNotifier }: Props) {
  const [ouvert, setOuvert] = useState<string | null>(null);
  const [titre, setTitre] = useState("");
  const [clos, setClos] = useState<Chantier[] | null>(null);
  const [voirClos, setVoirClos] = useState(false);

  // En direct : toutes les 5 s pendant qu'une mission ou un atelier travaille (sinon la surveillance de 15 s suffit)
  const travail = (activite?.en_cours ?? 0) > 0;
  useEffect(() => {
    if (!travail) return;
    const minuterie = window.setInterval(surRafraichir, 5000);
    return () => {
      window.clearInterval(minuterie);
    };
  }, [travail, surRafraichir]);
  useEffect(surRafraichir, [surRafraichir]); // à l'ouverture de l'onglet : données fraîches

  const chargerClos = () => {
    listerChantiers("tous")
      .then((r) => {
        setClos(r.chantiers.filter((c) => c.statut === "termine" || c.statut === "abandonne").slice(0, 20));
      })
      .catch((e: unknown) => {
        surNotifier(e instanceof Error ? e.message : "Lecture impossible.");
      });
  };

  const apres = (message?: string) => {
    if (message) surNotifier(message);
    surRafraichir();
    if (voirClos) chargerClos();
  };

  const creer = (e: FormEvent) => {
    e.preventDefault();
    const t = titre.trim();
    if (!t) return;
    creerChantier(t)
      .then((r) => {
        setTitre("");
        setOuvert(r.chantier.id);
        apres(r.cree ? "Chantier ajouté." : `Déjà suivi : « ${r.chantier.titre} ».`);
      })
      .catch((err: unknown) => {
        surNotifier(err instanceof Error ? err.message : "Création impossible.");
      });
  };

  const terminer = (c: Chantier) => {
    terminerChantier(c.id)
      .then((r) => {
        setOuvert(null);
        apres(
          r.doublons_abandonnes
            ? `C'est fait. ${String(r.doublons_abandonnes)} doublon${r.doublons_abandonnes > 1 ? "s" : ""} fermé${r.doublons_abandonnes > 1 ? "s" : ""}.`
            : "C'est fait.",
        );
      })
      .catch((err: unknown) => {
        surNotifier(err instanceof Error ? err.message : "Impossible.");
      });
  };

  const abandonner = (c: Chantier) => {
    demanderAction({ action: "chantier.abandonner", parametres: { chantier_id: c.id, titre: c.titre } })
      .then(surAction)
      .catch((err: unknown) => {
        surNotifier(err instanceof Error ? err.message : "Action impossible.");
      });
  };

  const rouvrir = (c: Chantier) => {
    rouvrirChantier(c.id)
      .then(() => {
        apres("Chantier rouvert.");
      })
      .catch((err: unknown) => {
        surNotifier(err instanceof Error ? err.message : "Impossible.");
      });
  };

  if (!activite) {
    return erreur ? (
      <p className="hist-etat" role="alert">
        {erreur}
      </p>
    ) : (
      <div className="activite" aria-busy="true">
        <div className="squelette squelette--ligne" />
        <div className="squelette squelette--ligne" />
      </div>
    );
  }

  const { chantiers, missions, ateliers, creations } = activite;
  return (
    <div className="activite">
      <p className="activite-direct" aria-live="polite">
        <span className="point-etat" data-ok={travail || undefined} data-direct={travail || undefined} aria-hidden="true" />
        {travail ? `${String(activite.en_cours)} travail${activite.en_cours > 1 ? "x" : ""} en cours` : "Rien ne tourne en ce moment"}
      </p>

      <section className="activite-section" aria-labelledby="activite-chantiers">
        <h3 className="hist-groupe-titre activite-titre" id="activite-chantiers">
          Chantiers <span className="activite-nombre">{chantiers.length}</span>
        </h3>
        <form className="chantier-ajout" onSubmit={creer}>
          <input
            type="text"
            value={titre}
            maxLength={300}
            placeholder="Nouveau chantier"
            aria-label="Titre du nouveau chantier"
            onChange={(e) => {
              setTitre(e.target.value);
            }}
          />
          <button type="submit" className="btn btn-mini" disabled={!titre.trim()}>
            Suivre
          </button>
        </form>
        {chantiers.length === 0 ? (
          <p className="hist-etat">Aucun chantier ouvert. Donnez un titre ci-dessus : JARVIS suit la progression et évite les doublons.</p>
        ) : (
          <ul className="activite-liste">
            {chantiers.map((c) => {
              const s = STATUT_CHANTIER[c.statut];
              const faites = c.etapes.filter((e) => e.fait).length;
              const deplie = ouvert === c.id;
              return (
                <li key={c.id} className="activite-item" data-ouvert={deplie || undefined}>
                  <button
                    type="button"
                    className="activite-tete"
                    aria-expanded={deplie}
                    aria-controls={`chantier-${c.id}`}
                    onClick={() => {
                      setOuvert(deplie ? null : c.id);
                    }}
                  >
                    <span className="activite-ligne">
                      <span className="activite-nom">{c.titre}</span>
                      <span className="badge-co" data-ton={s.ton}>
                        {s.texte}
                      </span>
                    </span>
                    <Progression valeur={c.progression} libelle={`Progression de « ${c.titre} »`} />
                    <span className="activite-meta">
                      {String(c.progression)} %{c.etapes.length > 0 && ` · ${String(faites)}/${String(c.etapes.length)} étapes`}
                      {c.etape_courante && ` · ${c.etape_courante}`}
                    </span>
                  </button>
                  {deplie && (
                    <>
                      <DetailChantier c={c} surFait={surRafraichir} surNotifier={surNotifier} />
                      <div className="activite-actions">
                        <button
                          type="button"
                          className="btn btn-principal btn-mini"
                          onClick={() => {
                            terminer(c);
                          }}
                        >
                          C'est fait
                        </button>
                        <button
                          type="button"
                          className="btn btn-discret btn-mini"
                          title="Abandonner (🟡, demande votre accord ; réversible)"
                          onClick={() => {
                            abandonner(c);
                          }}
                        >
                          Abandonner
                        </button>
                      </div>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        <button
          type="button"
          className="lien-btn activite-clos"
          aria-expanded={voirClos}
          onClick={() => {
            if (!voirClos) chargerClos();
            setVoirClos(!voirClos);
          }}
        >
          {voirClos ? "Masquer les chantiers clos" : "Chantiers clos"}
        </button>
        {voirClos &&
          (!clos ? (
            <div className="squelette squelette--ligne" />
          ) : clos.length === 0 ? (
            <p className="hist-etat">Aucun chantier clos.</p>
          ) : (
            <ul className="activite-liste">
              {clos.map((c) => (
                <li key={c.id} className="activite-item activite-item--clos">
                  <span className="activite-ligne">
                    <span className="activite-nom">{c.titre}</span>
                    <span className="badge-co" data-ton={STATUT_CHANTIER[c.statut].ton}>
                      {STATUT_CHANTIER[c.statut].texte}
                    </span>
                  </span>
                  <span className="activite-meta">
                    {c.termine_le ? DATE.format(new Date(c.termine_le)) : ""}
                    {c.motif && ` · ${c.motif}`}
                  </span>
                  <button
                    type="button"
                    className="btn btn-discret btn-mini activite-rouvrir"
                    onClick={() => {
                      rouvrir(c);
                    }}
                  >
                    Rouvrir
                  </button>
                </li>
              ))}
            </ul>
          ))}
      </section>

      <section className="activite-section" aria-labelledby="activite-missions">
        <h3 className="hist-groupe-titre activite-titre" id="activite-missions">
          Missions <span className="activite-nombre">{missions.length}</span>
        </h3>
        {missions.length === 0 ? (
          <p className="hist-etat">Aucune mission aujourd'hui. Lancez-en une depuis la vue Agents.</p>
        ) : (
          <ul className="activite-liste">
            {missions.map((m) => {
              const s = STATUT_MISSION[m.statut] ?? { texte: m.statut };
              const tourne = m.statut === "en_cours" || m.statut === "en_file";
              return (
                <li key={m.id} className="activite-item">
                  <button
                    type="button"
                    className="activite-tete"
                    onClick={() => {
                      surOuvrir({ vue: "agents", type: "mission", id: m.id });
                    }}
                  >
                    <span className="activite-ligne">
                      <span className="activite-nom">{m.objectif}</span>
                      <span className="badge-co" data-ton={s.ton}>
                        {s.texte}
                      </span>
                    </span>
                    {tourne && <Progression valeur={m.progression} libelle={`Progression de la mission « ${m.objectif} »`} />}
                    <span className="activite-meta">
                      {TYPE_MISSION[m.type] ?? m.type} · {DATE.format(new Date(m.termine_le ?? m.cree_le))}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="activite-section" aria-labelledby="activite-ateliers">
        <h3 className="hist-groupe-titre activite-titre" id="activite-ateliers">
          Ateliers <span className="activite-nombre">{ateliers.length}</span>
          {activite.attentes_ateliers > 0 && (
            <span className="pastille pastille--ambre" title="Autorisations en attente">
              {activite.attentes_ateliers}
            </span>
          )}
        </h3>
        {ateliers.length === 0 ? (
          <p className="hist-etat">Aucun atelier ouvert.</p>
        ) : (
          <ul className="activite-liste">
            {ateliers.map((a) => (
              <li key={a.id} className="activite-item">
                <button
                  type="button"
                  className="activite-tete"
                  onClick={() => {
                    surOuvrir({ vue: "ateliers", id: a.id });
                  }}
                >
                  <span className="activite-ligne">
                    <span className="point-etat" data-ok={a.actif || undefined} data-direct={a.actif || undefined} aria-hidden="true" />
                    <span className="activite-nom">{a.nom}</span>
                    <span className="badge-co" data-ton={a.actif ? "attention" : a.statut === "erreur" ? "risque" : undefined}>
                      {a.actif ? "Au travail" : (STATUT_ATELIER[a.statut] ?? a.statut)}
                    </span>
                  </span>
                  <span className="activite-meta">{a.projet}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="activite-section" aria-labelledby="activite-creations">
        <h3 className="hist-groupe-titre activite-titre" id="activite-creations">
          Créations récentes
        </h3>
        {creations.length === 0 ? (
          <p className="hist-etat">Aucune création pour l'instant.</p>
        ) : (
          <ul className="activite-liste">
            {creations.map((x) => (
              <li key={x.id} className="activite-item">
                <button
                  type="button"
                  className="activite-tete"
                  onClick={() => {
                    surOuvrir({ vue: "agents", type: "creation", id: x.id });
                  }}
                >
                  <span className="activite-ligne">
                    <span className="activite-nom">{x.titre}</span>
                    <span className="badge-co">v{x.version_courante}</span>
                  </span>
                  <span className="activite-meta">{DATE.format(new Date(x.maj_le))}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
