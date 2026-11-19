// Réglages du lot F : pilotage par JARVIS, commandes rapides, règles de protection, actions « toujours autorisées ».
// Tout est vérifié par le Core : ici, on ne fait que montrer et éditer.

import { useEffect, useId, useState } from "react";

import "../styles/pilotage.css";
import {
  ajouterRegle,
  creerCommandeRapide,
  lirePilotage,
  listerAutorisations,
  listerCommandesRapides,
  listerRegles,
  modifierCommandeRapide,
  reglerPilotage,
  retirerAutorisation,
  retirerRegle,
  supprimerCommandeRapide,
  testerMotif,
  verifierCommandeRapide,
} from "../api";
import { CHOIX_ANIMATIONS } from "../animations";
import { EMOJI_NIVEAU, EVENEMENT_PILOTAGE, MODES_PILOTAGE } from "../pilotage";
import { THEMES } from "../theme";
import type { AutorisationPermanente, CommandeRapide, CommandeRapideEdition, ConflitCommande, InfoPilotage, ModePilotage, RegleProtection } from "../types";

const DATE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function message(e: unknown, defaut: string): string {
  return e instanceof Error ? e.message : defaut;
}

// --- Mode de pilotage ---------------------------------------------------------------------------------------

export function ReglagePilotage({ surNotifier }: { surNotifier: (m: string) => void }) {
  const [mode, setMode] = useState<ModePilotage | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  useEffect(() => {
    lirePilotage()
      .then((p) => {
        setMode(p.mode);
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Pilotage illisible."));
      });
  }, []);
  const choisir = (m: ModePilotage) => {
    const avant = mode;
    setMode(m);
    reglerPilotage(m)
      .then(() => {
        window.dispatchEvent(new CustomEvent(EVENEMENT_PILOTAGE));
        surNotifier(`Pilotage par JARVIS : ${MODES_PILOTAGE.find((x) => x.id === m)?.nom ?? m}.`);
      })
      .catch((e: unknown) => {
        setMode(avant);
        setErreur(message(e, "Réglage impossible."));
      });
  };
  if (erreur) return <p className="sec-texte" role="alert">{erreur}</p>;
  if (!mode) return <div className="squelette squelette--ligne" aria-busy="true" />;
  return (
    <>
      <div className="segment" role="radiogroup" aria-label="Pilotage par JARVIS">
        {MODES_PILOTAGE.map((o) => (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={mode === o.id}
            className="segment-btn"
            onClick={() => {
              choisir(o.id);
            }}
          >
            {o.nom}
          </button>
        ))}
      </div>
      <p className="sec-texte">
        {mode === "oui"
          ? "Quand vous le lui demandez, JARVIS ouvre la vue ou l'élément tout seul."
          : mode === "demander"
            ? "JARVIS propose un bouton « Ouvrir » sous sa réponse ; rien ne bouge sans votre clic."
            : "JARVIS ne pilote pas l'interface : aucune action sous ses réponses."}{" "}
        Une mission, un atelier ou une action sensible restent <strong>toujours</strong> des propositions à valider d'un clic, quel que soit ce
        réglage : un texte lu par JARVIS (page, fichier, souvenir importé) ne peut rien lancer.
      </p>
    </>
  );
}

// --- Commandes rapides --------------------------------------------------------------------------------------

const VIDE: CommandeRapideEdition = { motif: "", cible: "interface", action: "naviguer", parametres: { vue: "agents" }, priorite: 0, phrase_test: "", actif: true };

function ParametresInterface({ edition, vues, surParametres }: { edition: CommandeRapideEdition; vues: Record<string, string>; surParametres: (p: Record<string, unknown>) => void }) {
  const id = useId();
  const p = edition.parametres;
  const valeur = (cle: string) => (typeof p[cle] === "string" ? p[cle] : "");
  if (edition.action === "naviguer") {
    return (
      <div className="rapide-ligne">
        <label className="champ">
          <span className="champ-etiquette">Vue à ouvrir</span>
          <select
            value={valeur("vue")}
            onChange={(e) => {
              surParametres({ vue: e.target.value });
            }}
          >
            {Object.entries(vues).map(([cle, nom]) => (
              <option key={cle} value={cle}>
                {nom}
              </option>
            ))}
          </select>
        </label>
        {valeur("vue") === "reglages" && (
          <label className="champ">
            <span className="champ-etiquette">Section (facultatif)</span>
            <input
              value={valeur("ancre")}
              placeholder="ex. couts, themes, regles"
              onChange={(e) => {
                surParametres({ vue: "reglages", ...(e.target.value ? { ancre: e.target.value } : {}) });
              }}
            />
          </label>
        )}
      </div>
    );
  }
  if (edition.action === "rechercher_memoire") {
    return (
      <label className="champ">
        <span className="champ-etiquette">Recherche</span>
        <input
          id={id}
          value={valeur("requete")}
          placeholder="{sujet} : le morceau capté par le motif"
          onChange={(e) => {
            surParametres({ requete: e.target.value });
          }}
        />
      </label>
    );
  }
  const cle = valeur("cle") || "theme";
  const options = cle === "theme" ? THEMES.map((t) => ({ id: t.id, nom: t.nom })) : CHOIX_ANIMATIONS.map((c) => ({ id: c.id, nom: c.nom }));
  return (
    <div className="rapide-ligne">
      <label className="champ">
        <span className="champ-etiquette">Réglage</span>
        <select
          value={cle}
          onChange={(e) => {
            surParametres({ cle: e.target.value, valeur: e.target.value === "theme" ? "jarvis" : "systeme" });
          }}
        >
          <option value="theme">Thème</option>
          <option value="animations">Animations</option>
        </select>
      </label>
      <label className="champ">
        <span className="champ-etiquette">Valeur</span>
        <select
          value={valeur("valeur")}
          onChange={(e) => {
            surParametres({ cle, valeur: e.target.value });
          }}
        >
          {options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.nom}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

function defautsAction(cible: "interface" | "core", action: string): Record<string, unknown> {
  if (cible === "core") return {};
  if (action === "naviguer") return { vue: "agents" };
  if (action === "rechercher_memoire") return { requete: "{sujet}" };
  return { cle: "theme", valeur: "jarvis" };
}

function Editeur({ info, initiale, surFini }: { info: InfoPilotage; initiale: CommandeRapide | null; surFini: (m?: string) => void }) {
  const [e, setE] = useState<CommandeRapideEdition>(initiale ? { motif: initiale.motif, cible: initiale.cible, action: initiale.action, parametres: initiale.parametres, priorite: initiale.priorite, phrase_test: initiale.phrase_test, actif: initiale.actif } : VIDE);
  const [json, setJson] = useState(() => JSON.stringify(initiale?.cible === "core" ? initiale.parametres : {}, null, 0));
  const [verif, setVerif] = useState<{ valide: boolean; texte: string; conflits: ConflitCommande[] } | null>(null);
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  // Vérification par le Core pendant la saisie : motif, phrase de test, action résolue, conflits
  const cle = JSON.stringify(e);
  useEffect(() => {
    if (!e.motif.trim() || !e.phrase_test.trim()) {
      setVerif(null);
      return;
    }
    const minuterie = window.setTimeout(() => {
      verifierCommandeRapide(e)
        .then((r) => {
          const autres = (r.conflits ?? []).filter((c) => c.id !== initiale?.id);
          setVerif(r.valide ? { valide: true, texte: `${EMOJI_NIVEAU[r.action?.niveau ?? "vert"] ?? ""} ${r.action?.libelle ?? ""}`, conflits: autres } : { valide: false, texte: r.erreur ?? "Commande invalide", conflits: [] });
        })
        .catch((x: unknown) => {
          setVerif({ valide: false, texte: message(x, "Vérification impossible."), conflits: [] });
        });
    }, 350);
    return () => {
      window.clearTimeout(minuterie);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `cle` résume toute la saisie
  }, [cle]);

  const choixAction = `${e.cible}:${e.action}`;
  const enregistrer = () => {
    setOccupe(true);
    setErreur(null);
    const appel = initiale ? modifierCommandeRapide(initiale.id, e) : creerCommandeRapide(e);
    appel
      .then(() => {
        surFini(initiale ? "Commande rapide modifiée." : "Commande rapide ajoutée.");
      })
      .catch((x: unknown) => {
        setErreur(message(x, "Enregistrement impossible."));
      })
      .finally(() => {
        setOccupe(false);
      });
  };

  return (
    <form
      className="carte-co rapide-editeur"
      onSubmit={(ev) => {
        ev.preventDefault();
        if (verif?.valide) enregistrer();
      }}
    >
      <label className="champ">
        <span className="champ-etiquette">Quand je dis…</span>
        <input
          value={e.motif}
          maxLength={200}
          placeholder="ex. ouvre * missions, ou : cherche {sujet} dans ta mémoire"
          onChange={(x) => {
            setE({ ...e, motif: x.target.value });
          }}
        />
      </label>
      <p className="carte-co-detail">« * » : n'importe quels mots · « {"{nom}"} » : un morceau réutilisable dans l'action · accents, majuscules et ponctuation ignorés</p>
      <label className="champ">
        <span className="champ-etiquette">…JARVIS fait</span>
        <select
          value={choixAction}
          onChange={(x) => {
            const [cible, action] = x.target.value.split(":") as ["interface" | "core", string];
            setE({ ...e, cible, action, parametres: defautsAction(cible, action) });
            setJson("{}");
          }}
        >
          <optgroup label="Interface (🟢, sans rien lancer)">
            <option value="interface:naviguer">Ouvrir une vue</option>
            <option value="interface:rechercher_memoire">Chercher dans la mémoire</option>
            <option value="interface:regler">Changer le thème ou les animations</option>
          </optgroup>
          <optgroup label="Actions déclarées (approbation selon le niveau)">
            {info.actions_declarees.map((a) => (
              <option key={a.nom} value={`core:${a.nom}`}>
                {EMOJI_NIVEAU[a.niveau]} {a.description}
              </option>
            ))}
          </optgroup>
        </select>
      </label>
      {e.cible === "interface" ? (
        <ParametresInterface
          edition={e}
          vues={info.vues}
          surParametres={(p) => {
            setE({ ...e, parametres: p });
          }}
        />
      ) : (
        <label className="champ">
          <span className="champ-etiquette">Paramètres (JSON ; {"{nom}"} pour un morceau capté)</span>
          <textarea
            className="rapide-json"
            rows={2}
            value={json}
            spellCheck={false}
            onChange={(x) => {
              setJson(x.target.value);
              try {
                const v: unknown = JSON.parse(x.target.value || "{}");
                if (v && typeof v === "object" && !Array.isArray(v)) setE({ ...e, parametres: v as Record<string, unknown> });
              } catch {
                /* saisie en cours : le Core vérifiera la dernière version lisible */
              }
            }}
          />
        </label>
      )}
      <div className="rapide-ligne">
        <label className="champ">
          <span className="champ-etiquette">Phrase de test</span>
          <input
            value={e.phrase_test}
            maxLength={200}
            placeholder="ex. ouvre les missions"
            onChange={(x) => {
              setE({ ...e, phrase_test: x.target.value });
            }}
          />
        </label>
        <label className="champ rapide-priorite">
          <span className="champ-etiquette">Priorité</span>
          <input
            type="number"
            min={-100}
            max={100}
            value={e.priorite}
            onChange={(x) => {
              setE({ ...e, priorite: Math.max(-100, Math.min(100, Number(x.target.value) || 0)) });
            }}
          />
        </label>
      </div>
      {verif && (
        <p className="rapide-verif" data-valide={verif.valide} role="status">
          {verif.valide ? `La phrase de test déclenche : ${verif.texte}` : verif.texte}
          {verif.valide && verif.conflits.length > 0 && (
            <span className="rapide-conflit">
              {" "}
              · aussi captée par {verif.conflits.map((c) => `« ${c.motif} » (priorité ${String(c.priorite)})`).join(", ")} : la priorité la plus haute l'emporte, puis le motif le plus précis
            </span>
          )}
        </p>
      )}
      {erreur && (
        <p className="demande-erreur" role="alert">
          {erreur}
        </p>
      )}
      <div className="carte-co-actions">
        <button
          type="button"
          className="btn btn-discret btn-mini"
          onClick={() => {
            surFini();
          }}
        >
          Annuler
        </button>
        <button type="submit" className="btn btn-mini" disabled={!verif?.valide || occupe}>
          {initiale ? "Enregistrer" : "Ajouter"}
        </button>
      </div>
    </form>
  );
}

export function CommandesRapides({ surNotifier }: { surNotifier: (m: string) => void }) {
  const [info, setInfo] = useState<InfoPilotage | null>(null);
  const [commandes, setCommandes] = useState<CommandeRapide[] | null>(null);
  const [edition, setEdition] = useState<CommandeRapide | "nouvelle" | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const charger = () => {
    Promise.all([lirePilotage(), listerCommandesRapides()])
      .then(([i, c]) => {
        setInfo(i);
        setCommandes(c.commandes);
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Commandes illisibles."));
      });
  };
  useEffect(charger, []);
  const fini = (m?: string) => {
    setEdition(null);
    if (m) surNotifier(m);
    charger();
  };
  const basculer = (c: CommandeRapide) => {
    const { motif, cible, action, parametres, priorite, phrase_test } = c;
    modifierCommandeRapide(c.id, { motif, cible, action, parametres, priorite, phrase_test, actif: !c.actif })
      .then(() => {
        charger();
      })
      .catch((e: unknown) => {
        surNotifier(message(e, "Modification impossible."));
      });
  };
  const supprimer = (c: CommandeRapide) => {
    supprimerCommandeRapide(c.id)
      .then(() => {
        fini(`Commande « ${c.motif} » supprimée.`);
      })
      .catch((e: unknown) => {
        surNotifier(message(e, "Suppression impossible."));
      });
  };

  if (erreur) return <p className="sec-texte" role="alert">{erreur}</p>;
  if (!info || !commandes) return <div className="squelette squelette--ligne" aria-busy="true" />;
  return (
    <div className="rapides">
      <p className="sec-texte">
        Reconnues avant l'IA, dans la saisie du Dialogue : réponse immédiate, aucun modèle appelé. Une commande ne donne aucun droit en plus : une
        action 🟡 attend votre accord, une action 🔴 votre clé d'accès. Jamais de commande système.
      </p>
      {commandes.length === 0 && edition === null && (
        <div className="vide vide--calme">
          <p className="vide-titre">Aucune commande rapide</p>
          <p>Ex. « ouvre * missions » → ouvrir les Missions ; « cherche {"{sujet}"} dans ta mémoire » → recherche dans la mémoire.</p>
        </div>
      )}
      {commandes.length > 0 && (
        <ul className="rapides-liste" aria-label="Commandes rapides">
          {commandes.map((c) =>
            edition !== "nouvelle" && edition?.id === c.id ? (
              <li key={c.id}>
                <Editeur info={info} initiale={c} surFini={fini} />
              </li>
            ) : (
              <li key={c.id} className="carte-co rapide" data-actif={c.actif}>
                <div className="carte-co-tete">
                  <p className="carte-co-nom">« {c.motif} »</p>
                  <span className="rapide-niveau" title={`Niveau : ${c.niveau}`}>
                    {EMOJI_NIVEAU[c.niveau] ?? "⚠"}
                  </span>
                </div>
                <p className="carte-co-detail">
                  → {c.cible === "interface" ? (c.action === "naviguer" ? `ouvrir ${info.vues[String(c.parametres.vue)] ?? String(c.parametres.vue)}` : c.action === "rechercher_memoire" ? "chercher dans la mémoire" : "changer un réglage") : (info.actions_declarees.find((a) => a.nom === c.action)?.description ?? c.action)}
                  {" · "}priorité {c.priorite} · test « {c.phrase_test} » · {c.utilisations ? `${String(c.utilisations)} utilisation${c.utilisations > 1 ? "s" : ""}` : "jamais utilisée"}
                </p>
                <div className="carte-co-actions">
                  <label className="carte-co-case carte-co-case--ligne">
                    <input
                      type="checkbox"
                      checked={c.actif}
                      onChange={() => {
                        basculer(c);
                      }}
                    />
                    Active
                  </label>
                  <button
                    type="button"
                    className="btn btn-discret btn-mini"
                    onClick={() => {
                      setEdition(c);
                    }}
                  >
                    Modifier
                  </button>
                  <button
                    type="button"
                    className="btn btn-discret btn-mini btn-danger"
                    onClick={() => {
                      supprimer(c);
                    }}
                  >
                    Supprimer
                  </button>
                </div>
              </li>
            ),
          )}
        </ul>
      )}
      {edition === "nouvelle" ? (
        <Editeur info={info} initiale={null} surFini={fini} />
      ) : (
        <button
          type="button"
          className="btn btn-mini"
          onClick={() => {
            setEdition("nouvelle");
          }}
        >
          Nouvelle commande rapide
        </button>
      )}
    </div>
  );
}

// --- Règles de protection -----------------------------------------------------------------------------------

export function ReglesProtection({ surChangement }: { surChangement: (m?: string) => void }) {
  const [regles, setRegles] = useState<RegleProtection[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [genre, setGenre] = useState<RegleProtection["genre"]>("interdire");
  const [motif, setMotif] = useState("");
  const [libelle, setLibelle] = useState("");
  const [essai, setEssai] = useState("");
  const [resultatEssai, setResultatEssai] = useState<string | null>(null);
  const charger = () => {
    listerRegles()
      .then((r) => {
        setRegles(r.regles);
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Règles illisibles."));
      });
  };
  useEffect(charger, []);
  useEffect(() => {
    if (!motif.trim() || !essai.trim()) {
      setResultatEssai(null);
      return;
    }
    const minuterie = window.setTimeout(() => {
      testerMotif(motif, essai, true)
        .then((r) => {
          setResultatEssai(!r.valide ? (r.erreur ?? "Motif invalide") : r.correspond ? `Cette action serait ${genre === "interdire" ? "refusée" : "soumise à votre accord"}.` : "Cette action ne serait pas concernée.");
        })
        .catch(() => {
          setResultatEssai(null);
        });
    }, 300);
    return () => {
      window.clearTimeout(minuterie);
    };
  }, [motif, essai, genre]);

  const ajouter = () => {
    ajouterRegle({ genre, motif, libelle })
      .then(() => {
        setMotif("");
        setLibelle("");
        setEssai("");
        surChangement("Règle de protection ajoutée.");
        charger();
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Ajout impossible."));
      });
  };
  const retirer = (r: RegleProtection) => {
    retirerRegle(r.id)
      .then(() => {
        surChangement("Retrait demandé : approuvez-le dans Demandes (🟡).");
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Retrait impossible."));
      });
  };

  return (
    <div className="regles">
      <p className="sec-texte">
        Appliquées par le Core à chaque action, même approuvée ou « toujours autorisée » ; données aussi à JARVIS pour qu'il les respecte. Le motif
        est cherché dans le nom, le résumé et les paramètres de l'action (« * » : n'importe quels mots). Ajouter est libre ; retirer passe par votre
        accord.
      </p>
      {erreur && (
        <p className="demande-erreur" role="alert">
          {erreur}
        </p>
      )}
      {regles === null ? (
        <div className="squelette squelette--ligne" aria-busy="true" />
      ) : regles.length === 0 ? (
        <p className="sec-texte">Aucune règle pour l'instant.</p>
      ) : (
        <ul className="regles-liste" aria-label="Règles de protection">
          {regles.map((r) => (
            <li key={r.id} className="carte-co regle" data-genre={r.genre}>
              <div className="carte-co-tete">
                <p className="carte-co-nom">
                  {r.genre === "interdire" ? "Ne jamais" : "Demander avant"} : {r.libelle}
                </p>
                {r.origine === "jarvis" && <span className="carte-co-badge">proposée par JARVIS</span>}
              </div>
              <p className="carte-co-detail">
                motif « {r.motif} » · {DATE.format(new Date(r.cree_le))}
              </p>
              <div className="carte-co-actions">
                <button
                  type="button"
                  className="btn btn-discret btn-mini"
                  onClick={() => {
                    retirer(r);
                  }}
                >
                  Retirer (🟡)
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <form
        className="carte-co regle-nouvelle"
        onSubmit={(e) => {
          e.preventDefault();
          if (motif.trim().length >= 2) ajouter();
        }}
      >
        <div className="segment" role="radiogroup" aria-label="Genre de règle">
          {(
            [
              ["interdire", "Ne jamais"],
              ["demander", "Demander avant"],
            ] as const
          ).map(([id, nom]) => (
            <button
              key={id}
              type="button"
              role="radio"
              aria-checked={genre === id}
              className="segment-btn"
              onClick={() => {
                setGenre(id);
              }}
            >
              {nom}
            </button>
          ))}
        </div>
        <div className="rapide-ligne">
          <label className="champ">
            <span className="champ-etiquette">Motif</span>
            <input
              value={motif}
              maxLength={200}
              placeholder="ex. projet client, ou : supprimer * chantier"
              onChange={(e) => {
                setMotif(e.target.value);
              }}
            />
          </label>
          <label className="champ">
            <span className="champ-etiquette">Règle en clair (facultatif)</span>
            <input
              value={libelle}
              maxLength={200}
              placeholder="ex. ne touche jamais au projet client"
              onChange={(e) => {
                setLibelle(e.target.value);
              }}
            />
          </label>
        </div>
        <label className="champ">
          <span className="champ-etiquette">Essayer sur une action</span>
          <input
            value={essai}
            maxLength={300}
            placeholder="ex. Archiver la conversation « Projet client »"
            onChange={(e) => {
              setEssai(e.target.value);
            }}
          />
        </label>
        {resultatEssai && (
          <p className="rapide-verif" role="status">
            {resultatEssai}
          </p>
        )}
        <div className="carte-co-actions">
          <button type="submit" className="btn btn-mini" disabled={motif.trim().length < 2}>
            Ajouter la règle
          </button>
        </div>
      </form>
    </div>
  );
}

// --- « Toujours autoriser » ---------------------------------------------------------------------------------

export function AutorisationsPermanentes({ surNotifier }: { surNotifier: (m: string) => void }) {
  const [liste, setListe] = useState<AutorisationPermanente[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const charger = () => {
    listerAutorisations()
      .then((r) => {
        setListe(r.autorisations);
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Autorisations illisibles."));
      });
  };
  useEffect(charger, []);
  const retirer = (a: AutorisationPermanente) => {
    retirerAutorisation(a.action)
      .then(() => {
        surNotifier(`« ${a.action} » redemandera votre accord.`);
        charger();
      })
      .catch((e: unknown) => {
        surNotifier(message(e, "Retrait impossible."));
      });
  };
  if (erreur) return <p className="sec-texte" role="alert">{erreur}</p>;
  if (!liste) return <div className="squelette squelette--ligne" aria-busy="true" />;
  return (
    <>
      <p className="sec-texte">
        Cochez « Toujours autoriser » en approuvant une action 🟡 pour ne plus l'approuver à chaque fois. Jamais pour une action 🔴 (clé d'accès à
        chaque fois, même à distance), ni pour un clic à l'écran, dans un navigateur ou un outil externe. Une règle « demander avant » passe avant.
      </p>
      {liste.length === 0 ? (
        <p className="sec-texte">Aucune action n'est toujours autorisée.</p>
      ) : (
        <ul className="regles-liste" aria-label="Actions toujours autorisées">
          {liste.map((a) => (
            <li key={a.action} className="carte-co">
              <div className="carte-co-tete">
                <p className="carte-co-nom">🟡 {a.description}</p>
              </div>
              <p className="carte-co-detail">
                {a.action} · depuis le {DATE.format(new Date(a.cree_le))} · {a.utilisations ? `${String(a.utilisations)} fois sans demande` : "pas encore utilisée"}
              </p>
              <div className="carte-co-actions">
                <button
                  type="button"
                  className="btn btn-discret btn-mini"
                  onClick={() => {
                    retirer(a);
                  }}
                >
                  Retirer
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
