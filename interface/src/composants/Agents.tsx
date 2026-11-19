import { useCallback, useEffect, useState } from "react";

import { activerOutilMcp, demanderAction, lancerMission, lancerRecette, listerMissions, listerOutilsMcp, listerRecettes } from "../api";
import { TexteRiche } from "../texte";
import type { Mission, OutilMcp, Recette, ReponseAction, ServeurMcp } from "../types";
import { SectionCreations } from "./Creations";

const DATE = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const TYPES: { id: Mission["type"]; nom: string; aide: string }[] = [
  { id: "recherche", nom: "Recherche", aide: "Cherche sur le web (SearXNG), puis un rapport qui cite ses sources." },
  { id: "brainstorm", nom: "Brainstorm", aide: "Dix idées, les trois meilleures et une première étape." },
  { id: "revue", nom: "Revue", aide: "Points forts, risques, questions ouvertes, recommandations." },
];
const STATUTS: Record<Mission["statut"], { texte: string; ton?: string }> = {
  en_file: { texte: "En file" },
  en_cours: { texte: "En cours", ton: "attention" },
  terminee: { texte: "Terminée", ton: "ok" },
  echec: { texte: "Échec", ton: "risque" },
  annulee: { texte: "Annulée" },
};
const EXECUTION: Record<string, { texte: string; ton?: string }> = {
  ok: { texte: "OK", ton: "ok" },
  erreur: { texte: "Erreur", ton: "risque" },
  ignoree: { texte: "Ignorée" },
  en_cours: { texte: "En cours", ton: "attention" },
};

function Missions({ surChangement }: { surChangement: (m?: string) => void }) {
  const [liste, setListe] = useState<Mission[] | null>(null);
  const [web, setWeb] = useState(false);
  const [type, setType] = useState<Mission["type"]>("recherche");
  const [objectif, setObjectif] = useState("");
  const [ouverte, setOuverte] = useState<string | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  const charger = useCallback(() => {
    listerMissions()
      .then((r) => {
        setListe(r.missions);
        setWeb(r.recherche_web);
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Lecture impossible.");
      });
  }, []);
  useEffect(charger, [charger]);
  const actives = liste?.some((m) => m.statut === "en_cours" || m.statut === "en_file") ?? false;
  useEffect(() => {
    if (!actives) return;
    const minuterie = window.setInterval(charger, 2500);
    return () => {
      window.clearInterval(minuterie);
    };
  }, [actives, charger]);

  return (
    <section className="famille-co" aria-labelledby="agents-missions">
      <h3 className="sec-titre" id="agents-missions">
        Missions
      </h3>
      <p className="sec-texte">
        Une mission travaille en tâche de fond et range son rapport dans la mémoire. Un sujet privé est confié à une IA locale.
        {type === "recherche" && !web && " Recherche web non configurée ([recherche] searxng) : le rapport dira qu'il n'est pas sourcé."}
      </p>
      <form
        className="mission-form"
        onSubmit={(e) => {
          e.preventDefault();
          setErreur(null);
          lancerMission(type, objectif.trim())
            .then(() => {
              setObjectif("");
              surChangement("Mission lancée.");
              charger();
            })
            .catch((err: unknown) => {
              setErreur(err instanceof Error ? err.message : "Lancement impossible.");
            });
        }}
      >
        <div className="segment" role="radiogroup" aria-label="Type de mission">
          {TYPES.map((t) => (
            <button
              key={t.id}
              type="button"
              role="radio"
              aria-checked={type === t.id}
              className="segment-btn"
              title={t.aide}
              onClick={() => {
                setType(t.id);
              }}
            >
              {t.nom}
            </button>
          ))}
        </div>
        <label className="visuellement-cache" htmlFor="mission-objectif">
          Objectif de la mission
        </label>
        <textarea
          id="mission-objectif"
          rows={2}
          value={objectif}
          placeholder={type === "recherche" ? "Que faut-il chercher ? (ex. réussir des tomates anciennes)" : "Sur quoi porter la mission ?"}
          onChange={(e) => {
            setObjectif(e.target.value);
          }}
        />
        <button type="submit" className="btn btn-principal btn-mini" disabled={objectif.trim().length < 3}>
          Lancer
        </button>
      </form>
      {erreur && (
        <p className="securite-erreur" role="alert">
          {erreur}
        </p>
      )}
      {!liste ? (
        <div className="squelette squelette--ligne" />
      ) : liste.length === 0 ? (
        <p className="sec-texte">Aucune mission pour l'instant.</p>
      ) : (
        <ul className="cartes-co">
          {liste.map((m) => {
            const s = STATUTS[m.statut];
            return (
              <li key={m.id} className="carte-co">
                <div className="carte-co-tete">
                  <h4 className="carte-co-nom">{m.objectif}</h4>
                  <span className="badge-co">{TYPES.find((t) => t.id === m.type)?.nom}</span>
                  <span className="badge-co" data-ton={s.ton}>
                    {s.texte}
                  </span>
                </div>
                {(m.statut === "en_cours" || m.statut === "en_file") && (
                  <div className="progression" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={m.progression} aria-label="Progression">
                    <span style={{ width: `${String(m.progression)}%` }} />
                  </div>
                )}
                <p className="carte-co-detail">
                  {DATE.format(new Date(m.cree_le))}
                  {m.etapes.length > 0 && ` · ${m.etapes[m.etapes.length - 1]?.nom ?? ""}`}
                  {m.resultat && ` · ${String(m.resultat.sources.length)} source${m.resultat.sources.length > 1 ? "s" : ""}`}
                </p>
                {m.erreur && <p className="carte-co-message">{m.erreur}</p>}
                {m.resultat && (
                  <div className="carte-co-actions">
                    <button
                      type="button"
                      className="btn btn-discret btn-mini"
                      aria-expanded={ouverte === m.id}
                      onClick={() => {
                        setOuverte(ouverte === m.id ? null : m.id);
                      }}
                    >
                      {ouverte === m.id ? "Masquer le rapport" : "Lire le rapport"}
                    </button>
                  </div>
                )}
                {ouverte === m.id && m.resultat && (
                  <div className="rapport md">
                    <TexteRiche source={m.resultat.rapport} />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function Recettes({ surChangement, surOuvrir }: { surChangement: (m?: string) => void; surOuvrir: (id: string) => void }) {
  const [donnees, setDonnees] = useState<{ dossier: string | null; recettes: Recette[]; erreurs: string[] } | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const charger = useCallback(() => {
    listerRecettes()
      .then(setDonnees)
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Lecture impossible.");
      });
  }, []);
  useEffect(charger, [charger]);

  return (
    <section className="famille-co" aria-labelledby="agents-recettes">
      <h3 className="sec-titre" id="agents-recettes">
        Recettes planifiées
      </h3>
      <p className="sec-texte">
        Une recette est un fichier YAML (nom, planification cron, consigne, livraison). JARVIS la lance à l'heure dite, jamais pendant
        l'arrêt d'urgence. Dossier des recettes :
      </p>
      <code className="verif-commande verif-commande--bloc">{donnees?.dossier ?? "recettes/"}</code>
      {erreur && <p className="securite-erreur">{erreur}</p>}
      {donnees?.erreurs.map((e) => (
        <p key={e} className="carte-co-message">
          {e}
        </p>
      ))}
      {!donnees ? (
        <div className="squelette squelette--ligne" />
      ) : donnees.recettes.length === 0 ? (
        <p className="sec-texte">Aucune recette : déposez un fichier .yaml dans ce dossier (voir config.exemple.toml).</p>
      ) : (
        <ul className="cartes-co">
          {donnees.recettes.map((r) => {
            const d = r.derniere;
            const etat = d ? (EXECUTION[d.statut] ?? { texte: d.statut }) : null;
            return (
              <li key={r.id} className="carte-co" data-statut={r.active ? undefined : "desactive"}>
                <div className="carte-co-tete">
                  <h4 className="carte-co-nom">{r.nom}</h4>
                  <span className="badge-co">{r.livraison === "memoire" ? "→ mémoire" : "→ conversation"}</span>
                  {etat && (
                    <span className="badge-co" data-ton={etat.ton}>
                      {etat.texte}
                    </span>
                  )}
                </div>
                <p className="carte-co-detail">
                  <code>{r.planification}</code>
                  {r.prochaine ? ` · prochaine : ${DATE.format(new Date(r.prochaine))}` : " · désactivée"}
                  {d && ` · dernière : ${DATE.format(new Date(d.debut))}`}
                </p>
                {d?.erreur && <p className="carte-co-message">{d.erreur}</p>}
                <div className="carte-co-actions">
                  <button
                    type="button"
                    className="btn btn-mini"
                    disabled={r.en_cours}
                    onClick={() => {
                      lancerRecette(r.id)
                        .then(() => {
                          surChangement(`Recette « ${r.nom} » lancée.`);
                          window.setTimeout(charger, 1500);
                        })
                        .catch((e: unknown) => {
                          setErreur(e instanceof Error ? e.message : "Lancement impossible.");
                        });
                    }}
                  >
                    {r.en_cours ? "En cours…" : "Lancer maintenant"}
                  </button>
                  {d?.conversation_id && (
                    <button
                      type="button"
                      className="btn btn-discret btn-mini"
                      onClick={() => {
                        if (d.conversation_id) surOuvrir(d.conversation_id);
                      }}
                    >
                      Voir le résultat
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function OutilMcpCarte({ serveur, o, surAction, surRecharger }: { serveur: string; o: OutilMcp; surAction: (r: ReponseAction) => void; surRecharger: () => void }) {
  const [args, setArgs] = useState("{}");
  const [message, setMessage] = useState<string | null>(null);
  return (
    <li className="carte-co" data-statut={o.actif ? "disponible" : "desactive"}>
      <div className="carte-co-tete">
        <h4 className="carte-co-nom">
          {serveur}/{o.nom}
        </h4>
        <label className="carte-co-case carte-co-case--ligne">
          <input
            type="checkbox"
            checked={o.actif}
            onChange={(e) => {
              activerOutilMcp(serveur, o.nom, e.target.checked)
                .then(surRecharger)
                .catch((err: unknown) => {
                  setMessage(err instanceof Error ? err.message : "Échec.");
                });
            }}
          />
          Activé
        </label>
      </div>
      {o.description && <p className="carte-co-detail">{o.description}</p>}
      {o.actif && (
        <form
          className="carte-co-cle"
          onSubmit={(e) => {
            e.preventDefault();
            let arguments_: unknown;
            try {
              arguments_ = JSON.parse(args);
            } catch {
              setMessage("Arguments : JSON invalide.");
              return;
            }
            demanderAction({ action: "mcp.appeler", parametres: { serveur, outil: o.nom, arguments: arguments_ } })
              .then(surAction)
              .catch((err: unknown) => {
                setMessage(err instanceof Error ? err.message : "Appel impossible.");
              });
          }}
        >
          <label className="visuellement-cache" htmlFor={`args-${serveur}-${o.nom}`}>
            Arguments JSON de {o.nom}
          </label>
          <input
            id={`args-${serveur}-${o.nom}`}
            spellCheck={false}
            value={args}
            onChange={(e) => {
              setArgs(e.target.value);
            }}
          />
          <button type="submit" className="btn btn-mini">
            Appeler (🟡)
          </button>
        </form>
      )}
      {message && <p className="carte-co-message">{message}</p>}
    </li>
  );
}

function OutilsMcp({ surAction }: { surAction: (r: ReponseAction) => void }) {
  const [serveurs, setServeurs] = useState<ServeurMcp[] | null>(null);
  const charger = useCallback(() => {
    listerOutilsMcp()
      .then((r) => {
        setServeurs(r.serveurs);
      })
      .catch(() => {
        setServeurs([]);
      });
  }, []);
  useEffect(charger, [charger]);
  return (
    <section className="famille-co" aria-labelledby="agents-mcp">
      <h3 className="sec-titre" id="agents-mcp">
        Outils MCP
      </h3>
      <p className="sec-texte">
        Serveurs déclarés dans la configuration locale ([[mcp.serveurs]]). Chaque outil est inactif jusqu'à ce que vous l'activiez, et
        chaque appel attend votre accord (🟡). Le résultat est une donnée, jamais un ordre.
      </p>
      {!serveurs ? (
        <div className="squelette squelette--ligne" />
      ) : serveurs.length === 0 ? (
        <p className="sec-texte">Aucun serveur MCP déclaré.</p>
      ) : (
        serveurs.map((s) => (
          <div key={s.serveur} className="mcp-serveur">
            {!s.disponible && <p className="carte-co-message">{s.serveur} : {s.erreur}</p>}
            <ul className="cartes-co">
              {s.outils.map((o) => (
                <OutilMcpCarte key={o.nom} serveur={s.serveur} o={o} surAction={surAction} surRecharger={charger} />
              ))}
            </ul>
          </div>
        ))
      )}
    </section>
  );
}

interface Props {
  surChangement: (message?: string) => void;
  surOuvrirConversation: (id: string) => void;
  surAction: (r: ReponseAction) => void;
}

/** Agents : missions de fond, recettes planifiées, outils MCP sous approbation. */
export function VueAgents({ surChangement, surOuvrirConversation, surAction }: Props) {
  return (
    <div className="connecteurs">
      <Missions surChangement={surChangement} />
      <Recettes surChangement={surChangement} surOuvrir={surOuvrirConversation} />
      <SectionCreations surChangement={surChangement} />
      <OutilsMcp surAction={surAction} />
    </div>
  );
}
