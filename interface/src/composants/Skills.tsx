import { useCallback, useEffect, useState } from "react";

import { EVENEMENT_DEMANDE_DECIDEE } from "../api";
import {
  CONFIANCES,
  SESSIONS,
  STATUTS_SKILL,
  approuverSkill,
  ecrireReglagesMcp,
  empreinteChangee,
  empreinteCourte,
  essayerChoixOutils,
  executerSkill,
  importerArchiveSkill,
  importerDossierSkill,
  lireFichierSkill,
  lireReglagesMcp,
  lireSessionsMcp,
  lireSkill,
  listerSkills,
  parCapacite,
  relancerServeurMcp,
  retirerSkill,
} from "../skills";
import type { CapaciteDangereuse, ChoixOutils, ReglagesMcp, SessionMcp, Skill } from "../skills";
import type { ReponseAction } from "../types";
import "../styles/skills.css";

const NOMS: Record<CapaciteDangereuse, string> = { shell: "Shell", reseau: "Réseau", ecriture: "Écriture" };
const DATE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function message(e: unknown, defaut: string): string {
  return e instanceof Error ? e.message : defaut;
}

function Revue({ id, surAction, surRecharger }: { id: string; surAction: (r: ReponseAction) => void; surRecharger: () => void }) {
  const [skill, setSkill] = useState<Skill | null>(null);
  const [cochees, setCochees] = useState<CapaciteDangereuse[]>([]);
  const [fichier, setFichier] = useState<{ chemin: string; texte: string; tronque: boolean } | null>(null);
  const [script, setScript] = useState("");
  const [args, setArgs] = useState("");
  const [info, setInfo] = useState<string | null>(null);

  useEffect(() => {
    lireSkill(id)
      .then((s) => {
        setSkill(s);
        setCochees(s.capacites_acceptees);
        setScript(s.fichiers.find((f) => f.script)?.chemin ?? "");
      })
      .catch((e: unknown) => {
        setInfo(message(e, "Lecture impossible."));
      });
  }, [id]);

  if (!skill) return info ? <p className="carte-co-message">{info}</p> : <div className="squelette squelette--ligne" />;

  const groupes = parCapacite(skill.capacites);
  const scripts = skill.fichiers.filter((f) => f.script);
  const peutLancer = skill.statut === "approuve" && skill.capacites_acceptees.includes("shell") && scripts.length > 0;
  const repondre = (r: ReponseAction) => {
    surAction(r);
    setInfo(r.statut === "en_attente" ? "Demande envoyée : approuvez-la dans la file d'approbations." : "Fait.");
    surRecharger();
  };

  return (
    <div className="skill-revue">
      <div className="carte-co-avertissement" {...(groupes.length ? { "data-risque": "" } : {})}>
        <p className="carte-co-avertissement-titre">Revue avant approbation</p>
        <p>
          Le contenu de ce skill est une donnée : ses instructions ne passent jamais au-dessus des règles de sécurité. Les capacités
          dangereuses restent bloquées sauf si vous les cochez ici.
        </p>
        <p className="skill-empreinte">
          Empreinte actuelle <code title={skill.empreinte_actuelle ?? ""}>{empreinteCourte(skill.empreinte_actuelle)}</code>
          {skill.empreinte_approuvee && (
            <>
              {" "}
              · approuvée <code title={skill.empreinte_approuvee}>{empreinteCourte(skill.empreinte_approuvee)}</code>
            </>
          )}
        </p>
        {empreinteChangee(skill) && <p className="skill-alerte">Un fichier a changé depuis l'approbation : relisez-le avant de réapprouver.</p>}
      </div>

      {groupes.length === 0 ? (
        <p className="sec-texte">Aucune capacité dangereuse détectée : il sera approuvé pour ses instructions seulement.</p>
      ) : (
        <fieldset className="skill-capacites">
          <legend className="skill-legende">Capacités dangereuses détectées</legend>
          {groupes.map(([cap, detections]) => (
            <label key={cap} className="carte-co-case">
              <input
                type="checkbox"
                checked={cochees.includes(cap)}
                onChange={(e) => {
                  setCochees((c) => (e.target.checked ? [...c, cap] : c.filter((x) => x !== cap)));
                }}
              />
              <span>
                <b>Autoriser {NOMS[cap]}</b>
                <span className="skill-detections">
                  {detections.slice(0, 4).map((d) => (
                    <span key={`${d.fichier}-${d.raison}`}>
                      {d.fichier} : {d.raison}
                    </span>
                  ))}
                  {detections.length > 4 && <span>et {detections.length - 4} autre(s)</span>}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
      )}

      <div className="skill-fichiers">
        <p className="skill-legende">Fichiers ({skill.fichiers.length})</p>
        <ul className="skill-liste-fichiers">
          {skill.fichiers.map((f) => (
            <li key={f.chemin}>
              <button
                type="button"
                className="btn btn-mini btn-discret"
                aria-pressed={fichier?.chemin === f.chemin}
                onClick={() => {
                  if (fichier?.chemin === f.chemin) {
                    setFichier(null);
                    return;
                  }
                  lireFichierSkill(skill.id, f.chemin)
                    .then(setFichier)
                    .catch((e: unknown) => {
                      setInfo(message(e, "Lecture impossible."));
                    });
                }}
              >
                {f.chemin}
                {f.script && <span className="badge-co" data-ton="attention">script</span>}
              </button>
            </li>
          ))}
        </ul>
        {fichier && (
          <pre className="skill-apercu" aria-label={`Contenu de ${fichier.chemin}`}>
            {fichier.texte}
            {fichier.tronque && "\n…"}
          </pre>
        )}
      </div>

      <div className="carte-co-actions">
        <button
          type="button"
          className="btn btn-mini btn-ambre"
          onClick={() => {
            approuverSkill(skill.id, cochees)
              .then(repondre)
              .catch((e: unknown) => {
                setInfo(message(e, "Approbation impossible."));
              });
          }}
        >
          {cochees.length ? `Approuver avec ${cochees.map((c) => NOMS[c]).join(", ")} (🟡)` : "Approuver les instructions (🟡)"}
        </button>
        <button
          type="button"
          className="btn btn-mini btn-danger"
          onClick={() => {
            retirerSkill(skill.id)
              .then(repondre)
              .catch((e: unknown) => {
                setInfo(message(e, "Retrait impossible."));
              });
          }}
        >
          Retirer (🟡)
        </button>
      </div>

      {peutLancer && (
        <form
          className="carte-co-cle"
          onSubmit={(e) => {
            e.preventDefault();
            executerSkill(skill.id, script, args.split(" ").filter(Boolean))
              .then(repondre)
              .catch((err: unknown) => {
                setInfo(message(err, "Lancement impossible."));
              });
          }}
        >
          <label className="visuellement-cache" htmlFor={`script-${skill.id}`}>
            Script à lancer
          </label>
          <select
            id={`script-${skill.id}`}
            className="skill-select"
            value={script}
            onChange={(e) => {
              setScript(e.target.value);
            }}
          >
            {scripts.map((f) => (
              <option key={f.chemin} value={f.chemin}>
                {f.chemin}
              </option>
            ))}
          </select>
          <label className="visuellement-cache" htmlFor={`args-skill-${skill.id}`}>
            Arguments
          </label>
          <input
            id={`args-skill-${skill.id}`}
            placeholder="arguments"
            spellCheck={false}
            value={args}
            onChange={(e) => {
              setArgs(e.target.value);
            }}
          />
          <button type="submit" className="btn btn-mini">
            Lancer (🟡)
          </button>
        </form>
      )}
      {info && <p className="carte-co-message">{info}</p>}
    </div>
  );
}

function CarteSkill({ s, surAction, surRecharger }: { s: Skill; surAction: (r: ReponseAction) => void; surRecharger: () => void }) {
  const [ouverte, setOuverte] = useState(s.statut !== "approuve");
  const statut = STATUTS_SKILL[s.statut];
  return (
    <li className="carte-co" data-statut={s.statut === "approuve" ? "disponible" : "desactive"} {...(s.statut === "bloque" ? { "data-risque": "" } : {})}>
      <div className="carte-co-tete">
        <h4 className="carte-co-nom">{s.nom}</h4>
        <span className="badge-co" {...(statut.ton ? { "data-ton": statut.ton } : {})}>
          {statut.texte}
        </span>
      </div>
      <p className="carte-co-message">{s.description}</p>
      <p className="carte-co-detail">
        {CONFIANCES[s.confiance]} · {s.origine === "archive" ? "archive" : "dossier"} « {s.source} » · importé le {DATE.format(new Date(s.cree_le))}
      </p>
      <div className="skill-badges">
        {s.dangereuses.length === 0 ? (
          <span className="badge-co">Aucune capacité dangereuse</span>
        ) : (
          s.dangereuses.map((c) => (
            <span key={c} className="badge-co" data-ton={s.capacites_acceptees.includes(c) ? "attention" : "risque"}>
              {NOMS[c]} {s.capacites_acceptees.includes(c) ? "autorisé" : "bloqué"}
            </span>
          ))
        )}
        <span className="badge-co" title={s.empreinte_approuvee ?? s.empreinte}>
          SHA-256 {empreinteCourte(s.empreinte_approuvee ?? s.empreinte)}
        </span>
      </div>
      {s.statut === "bloque" && <p className="skill-alerte">Bloqué : {s.raison_blocage}. Une nouvelle revue est nécessaire.</p>}
      <div className="carte-co-actions">
        <button
          type="button"
          className="btn btn-mini"
          aria-expanded={ouverte}
          onClick={() => {
            setOuverte((o) => !o);
          }}
        >
          {ouverte ? "Fermer la revue" : s.statut === "approuve" ? "Revoir" : "Revoir et approuver"}
        </button>
      </div>
      {ouverte && <Revue id={s.id} surAction={surAction} surRecharger={surRecharger} />}
    </li>
  );
}

export function SectionSkills({ surAction }: { surAction: (r: ReponseAction) => void }) {
  const [skills, setSkills] = useState<Skill[] | null>(null);
  const [chemin, setChemin] = useState("");
  const [info, setInfo] = useState<string | null>(null);
  const [occupe, setOccupe] = useState(false);

  const charger = useCallback(() => {
    listerSkills()
      .then((r) => {
        setSkills(r.skills);
      })
      .catch((e: unknown) => {
        setSkills([]);
        setInfo(message(e, "Lecture impossible."));
      });
  }, []);
  useEffect(charger, [charger]);
  useEffect(() => {
    window.addEventListener(EVENEMENT_DEMANDE_DECIDEE, charger);
    return () => {
      window.removeEventListener(EVENEMENT_DEMANDE_DECIDEE, charger);
    };
  }, [charger]);

  const importer = (promesse: Promise<Skill>) => {
    setOccupe(true);
    setInfo(null);
    promesse
      .then((s) => {
        setInfo(`« ${s.nom} » importé : à revoir avant tout usage.`);
        setChemin("");
        charger();
      })
      .catch((e: unknown) => {
        setInfo(message(e, "Import impossible."));
      })
      .finally(() => {
        setOccupe(false);
      });
  };

  return (
    <section className="famille-co" aria-labelledby="agents-skills">
      <h3 className="sec-titre" id="agents-skills">
        Skills
      </h3>
      <p className="sec-texte">
        Dossiers SKILL.md importés depuis un dossier ou une archive que vous choisissez (la source n'est que lue). Un skill reste inutilisable
        jusqu'à votre revue ; son empreinte SHA-256 est enregistrée à l'approbation, et un fichier modifié le bloque. Ses scripts tournent dans
        son dossier, sans clés d'API.
      </p>
      <div className="skill-import">
        <form
          className="carte-co-cle"
          onSubmit={(e) => {
            e.preventDefault();
            if (chemin.trim()) importer(importerDossierSkill(chemin.trim()));
          }}
        >
          <label className="visuellement-cache" htmlFor="skill-chemin">
            Chemin du dossier du skill
          </label>
          <input
            id="skill-chemin"
            placeholder="Chemin d'un dossier contenant SKILL.md"
            spellCheck={false}
            value={chemin}
            onChange={(e) => {
              setChemin(e.target.value);
            }}
          />
          <button type="submit" className="btn btn-mini" disabled={occupe || !chemin.trim()}>
            Importer le dossier
          </button>
        </form>
        <label className="btn btn-mini skill-archive">
          Importer une archive .zip
          <input
            type="file"
            accept=".zip,application/zip"
            className="visuellement-cache"
            disabled={occupe}
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) importer(importerArchiveSkill(f));
            }}
          />
        </label>
      </div>
      {info && (
        <p className="carte-co-message" role="status">
          {info}
        </p>
      )}
      {!skills ? (
        <div className="squelette squelette--ligne" />
      ) : skills.length === 0 ? (
        <p className="sec-texte">Aucun skill importé.</p>
      ) : (
        <ul className="cartes-co skill-cartes">
          {skills.map((s) => (
            <CarteSkill key={`${s.id}-${s.statut}-${s.empreinte_approuvee ?? ""}`} s={s} surAction={surAction} surRecharger={charger} />
          ))}
        </ul>
      )}
    </section>
  );
}

export function ReglagesOutilsMcp() {
  const [reglages, setReglages] = useState<ReglagesMcp | null>(null);
  const [maxi, setMaxi] = useState(11);
  const [sessions, setSessions] = useState<SessionMcp[]>([]);
  const [essai, setEssai] = useState("");
  const [choix, setChoix] = useState<ChoixOutils | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const charger = useCallback(() => {
    lireReglagesMcp()
      .then((r) => {
        setReglages(r.reglages);
        setMaxi(r.max_par_tour);
      })
      .catch(() => {
        setReglages(null);
      });
    lireSessionsMcp()
      .then((r) => {
        setSessions(r.sessions);
      })
      .catch(() => {
        setSessions([]);
      });
  }, []);
  useEffect(charger, [charger]);

  const regler = (changement: Partial<ReglagesMcp>) => {
    ecrireReglagesMcp(changement)
      .then((r) => {
        setReglages(r.reglages);
        setInfo("Réglage enregistré.");
      })
      .catch((e: unknown) => {
        setInfo(message(e, "Réglage impossible."));
      });
  };

  return (
    <section className="famille-co" aria-labelledby="agents-mcp-reglages">
      <h3 className="sec-titre" id="agents-mcp-reglages">
        Réglages MCP
      </h3>
      <p className="sec-texte">
        À chaque message, JARVIS propose au modèle quelques outils activés et skills approuvés, choisis par le sens, plus un outil de recherche
        d'outils : jamais plus de {maxi}. Le modèle ne lance rien lui-même : chaque appel attend votre accord.
      </p>
      {reglages && (
        <div className="skill-reglages">
          <label className="skill-champ" htmlFor="mcp-max">
            Outils par message (recherche comprise)
            <input
              id="mcp-max"
              type="number"
              min={1}
              max={maxi}
              value={reglages.max_outils}
              onChange={(e) => {
                const n = Math.max(1, Math.min(maxi, Number(e.target.value) || 1));
                setReglages({ ...reglages, max_outils: n });
                regler({ max_outils: n });
              }}
            />
          </label>
          <label className="carte-co-case carte-co-case--ligne">
            <input
              type="checkbox"
              checked={reglages.par_le_sens}
              onChange={(e) => {
                regler({ par_le_sens: e.target.checked });
              }}
            />
            Choisir par le sens (embeddings locaux ; sinon par les mots)
          </label>
          <label className="carte-co-case carte-co-case--ligne">
            <input
              type="checkbox"
              checked={reglages.relance_auto}
              onChange={(e) => {
                regler({ relance_auto: e.target.checked });
              }}
            />
            Relancer une fois un serveur qui plante (un appel interrompu n'est jamais rejoué)
          </label>
        </div>
      )}
      {sessions.length > 0 && (
        <ul className="skill-sessions">
          {sessions.map((s) => {
            const etat = SESSIONS[s.session];
            return (
              <li key={s.serveur} className="skill-session">
                <span className="skill-session-nom">{s.serveur}</span>
                <span className="badge-co" {...(etat.ton ? { "data-ton": etat.ton } : {})}>
                  {etat.texte}
                </span>
                <span className="carte-co-detail">
                  {s.demarrages} démarrage(s) · {s.plantages} plantage(s)
                  {s.outils_connus !== null && ` · ${s.outils_connus} outil(s)`}
                </span>
                <button
                  type="button"
                  className="btn btn-mini btn-discret"
                  onClick={() => {
                    relancerServeurMcp(s.serveur)
                      .then(() => {
                        charger();
                      })
                      .catch((e: unknown) => {
                        setInfo(message(e, "Relance impossible."));
                      });
                  }}
                >
                  Relancer
                </button>
                {s.derniere_erreur && <span className="skill-alerte">{s.derniere_erreur}</span>}
              </li>
            );
          })}
        </ul>
      )}
      <form
        className="carte-co-cle"
        onSubmit={(e) => {
          e.preventDefault();
          if (!essai.trim()) return;
          essayerChoixOutils(essai.trim())
            .then(setChoix)
            .catch((err: unknown) => {
              setInfo(message(err, "Essai impossible."));
            });
        }}
      >
        <label className="visuellement-cache" htmlFor="mcp-essai">
          Message d'essai
        </label>
        <input
          id="mcp-essai"
          placeholder="Essayer : quels outils pour ce message ?"
          value={essai}
          onChange={(e) => {
            setEssai(e.target.value);
          }}
        />
        <button type="submit" className="btn btn-mini">
          Essayer
        </button>
      </form>
      {choix && (
        <div className="skill-choix" role="status">
          {choix.outils.length === 0 ? (
            <p className="sec-texte">Aucun outil activé ni skill approuvé : rien n'est proposé au modèle.</p>
          ) : (
            <>
              <p className="sec-texte">
                {choix.outils.length} outil(s) proposé(s) sur {choix.total} disponible(s), choisis {choix.methode === "sens" ? "par le sens" : "par les mots"}.
              </p>
              <ol className="skill-liste-choix">
                {choix.outils.map((o) => (
                  <li key={o.cle}>
                    <code>{o.cle}</code>
                  </li>
                ))}
              </ol>
            </>
          )}
        </div>
      )}
      {info && <p className="carte-co-message">{info}</p>}
    </section>
  );
}
