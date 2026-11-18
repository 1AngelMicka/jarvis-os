import { useCallback, useEffect, useRef, useState } from "react";

import { arreterUrgence, conseiller, demanderAction, dialoguer, ErreurApi, leverUrgence, lireAccueil, lireConversation, lireEtat } from "./api";
import { EVENEMENT_NON_AUTORISE, lireJeton } from "./auth";
import { VueAccueil } from "./composants/Accueil";
import { VueAgents } from "./composants/Agents";
import { VueConnecteurs } from "./composants/Connecteurs";
import { ListeDemandes } from "./composants/Demandes";
import { Console, Fil, type MessageAffiche } from "./composants/Dialogue";
import { ListeConversations } from "./composants/Historique";
import { EcranJumelage } from "./composants/Jumelage";
import { Panneau } from "./composants/Panneau";
import { type EtatNoyau, Reacteur } from "./composants/Reacteur";
import { PanneauSecurite } from "./composants/Securite";
import { SelecteurTheme } from "./composants/SelecteurTheme";
import { ecrirePreferences, lirePreferences } from "./preferences";
import type { AvisExpert, Etat, EvenementDialogue, InfoMoteur, MessageStocke, ReponseAction, ResumeConversation } from "./types";

let compteur = 0;
const nouvelleCle = () => `m${String(++compteur)}`;

function depuisStocke(m: MessageStocke): MessageAffiche {
  return { cle: `s${String(m.id)}`, role: m.role, texte: m.contenu, meta: m.meta };
}

function modeleParDefaut(moteur: InfoMoteur | undefined, prefere?: string): string {
  if (!moteur) return "";
  if (prefere && moteur.modeles.some((m) => m.id === prefere)) return prefere;
  return (moteur.modeles.find((m) => m.defaut) ?? moteur.modeles[0])?.id ?? "";
}

/** Porte d'entrée : écran de jumelage tant que cet appareil n'a pas de jeton valable. */
export function App() {
  const [autorise, setAutorise] = useState(() => Boolean(lireJeton()) && !window.location.hash.includes("jumeler="));
  useEffect(() => {
    const surRefus = () => {
      setAutorise(false);
    };
    window.addEventListener(EVENEMENT_NON_AUTORISE, surRefus);
    return () => {
      window.removeEventListener(EVENEMENT_NON_AUTORISE, surRefus);
    };
  }, []);
  return autorise ? (
    <Hud />
  ) : (
    <EcranJumelage
      surAutorise={() => {
        setAutorise(true);
      }}
    />
  );
}

type Onglet = "conversations" | "demandes" | "securite";

function Hud() {
  const [etat, setEtat] = useState<Etat | null>(null);
  const [erreurEtat, setErreurEtat] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ResumeConversation[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [messages, setMessages] = useState<MessageAffiche[]>([]);
  const [chargement, setChargement] = useState(false);
  const [moteur, setMoteur] = useState("");
  const [modeles, setModeles] = useState<Record<string, string>>({});
  const [effort, setEffort] = useState("");
  const [enCours, setEnCours] = useState(false);
  const [premierMorceau, setPremierMorceau] = useState(false);
  const [alerte, setAlerte] = useState(false);
  const [lateralOuvert, setLateralOuvert] = useState(false);
  const [onglet, setOnglet] = useState<Onglet>("conversations");
  const [vue, setVue] = useState<"dialogue" | "connecteurs" | "accueil" | "agents">("dialogue");
  const [conseil, setConseil] = useState(false);
  const [avisEnCours, setAvisEnCours] = useState<{ attendus: number; recus: number } | null>(null);
  const [annonce, setAnnonce] = useState("");
  const [notif, setNotif] = useState<string | null>(null);
  const controleur = useRef<AbortController | null>(null);
  const minuterieNotif = useRef<number | undefined>(undefined);

  const notifier = useCallback((message: string) => {
    setNotif(message);
    setAnnonce(message);
    window.clearTimeout(minuterieNotif.current);
    minuterieNotif.current = window.setTimeout(() => {
      setNotif(null);
    }, 4200);
  }, []);

  const charger = useCallback((initial = true) => {
    setErreurEtat(null);
    lireEtat()
      .then((e) => {
        setEtat(e);
        setConversations(e.conversations);
        if (!initial) return;
        const prefs = lirePreferences();
        // « auto » : le routeur choisit ; un choix mémorisé n'est repris que s'il existe encore
        setMoteur(prefs.moteur && e.moteurs.some((m) => m.id === prefs.moteur) ? prefs.moteur : "auto");
        setModeles(Object.fromEntries(e.moteurs.map((m) => [m.id, modeleParDefaut(m, prefs.modeles?.[m.id])])));
        const claude = e.moteurs.find((m) => m.efforts.length);
        setEffort(prefs.effort && claude?.efforts.includes(prefs.effort) ? prefs.effort : (claude?.effort_defaut ?? ""));
      })
      .catch((err: unknown) => {
        setErreurEtat(err instanceof Error ? err.message : "Core injoignable.");
      });
  }, []);

  useEffect(() => {
    charger();
    // Premier lancement : l'assistant s'ouvre tant qu'il n'a pas été terminé
    lireAccueil()
      .then((a) => {
        if (!a.termine) setVue("accueil");
      })
      .catch(() => {
        /* Core injoignable : l'écran d'erreur du dialogue le dit déjà */
      });
  }, [charger]);

  const rafraichir = useCallback(
    (message?: string) => {
      if (message) notifier(message);
      charger(false);
    },
    [charger, notifier],
  );

  useEffect(() => {
    if (moteur) ecrirePreferences({ moteur, modeles, effort });
  }, [moteur, modeles, effort]);

  // Arrêt d'urgence : toute l'interface passe en rouge (les jetons de couleur sont redéfinis)
  const urgence = etat?.urgence.actif ?? false;
  useEffect(() => {
    document.documentElement.classList.toggle("en-urgence", urgence);
  }, [urgence]);

  useEffect(() => {
    if (!lateralOuvert) return;
    document.querySelector<HTMLElement>(".colonne-droite .onglet[aria-selected='true']")?.focus();
    const surTouche = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setLateralOuvert(false);
        document.querySelector<HTMLElement>(".btn-historique")?.focus();
      }
    };
    window.addEventListener("keydown", surTouche);
    return () => {
      window.removeEventListener("keydown", surTouche);
    };
  }, [lateralOuvert]);

  const ouvrir = useCallback((id: string) => {
    controleur.current?.abort();
    setActive(id);
    setLateralOuvert(false);
    setChargement(true);
    lireConversation(id)
      .then((d) => {
        setMessages(d.messages.map(depuisStocke));
        // Choix imposé pour cette conversation (sinon le routeur)
        const impose = d.conversation.connecteur;
        setMoteur(impose ?? "auto");
        if (impose && d.conversation.modele) setModeles((ms) => ({ ...ms, [impose]: d.conversation.modele ?? "" }));
      })
      .catch((err: unknown) => {
        setMessages([{ cle: nouvelleCle(), role: "erreur", texte: err instanceof Error ? err.message : "Lecture impossible." }]);
      })
      .finally(() => {
        setChargement(false);
      });
  }, []);

  const nouvelle = () => {
    controleur.current?.abort();
    setActive(null);
    setMessages([]);
    setLateralOuvert(false);
    document.getElementById("saisie-message")?.focus();
  };

  const signalerAlerte = () => {
    setAlerte(true);
    window.setTimeout(() => {
      setAlerte(false);
    }, 2400);
  };

  const montrerDemandes = () => {
    setOnglet("demandes");
    setLateralOuvert(true);
  };

  const suiteAction = (r: ReponseAction, ok: string) => {
    if (r.statut === "en_attente") {
      rafraichir(r.demande.niveau === "rouge" ? "Action 🔴 : approuvez-la avec votre clé d'accès." : "Action 🟡 en attente de votre accord.");
      montrerDemandes();
    } else rafraichir(ok);
  };

  const agirSurConversation = (action: "conversation.archiver" | "conversation.supprimer") => {
    if (!active) return;
    const titre = conversations.find((c) => c.id === active)?.titre;
    demanderAction({ action, parametres: { conversation_id: active, titre } })
      .then((r) => {
        suiteAction(r, "Fait.");
      })
      .catch((e: unknown) => {
        notifier(e instanceof Error ? e.message : "Action impossible.");
      });
  };

  const declencherUrgence = () => {
    controleur.current?.abort();
    arreterUrgence()
      .then((r) => {
        rafraichir(`Arrêt d'urgence : ${String(r.reponses_interrompues)} réponse(s) interrompue(s).`);
      })
      .catch((e: unknown) => {
        notifier(e instanceof Error ? e.message : "Arrêt impossible.");
      });
  };

  const demanderLevee = () => {
    leverUrgence()
      .then((r) => {
        suiteAction(r, "Arrêt d'urgence levé.");
      })
      .catch((e: unknown) => {
        notifier(e instanceof Error ? e.message : "Impossible.");
      });
  };

  const envoyer = (texte: string) => {
    const cleJarvis = nouvelleCle();
    setMessages((ms) => [...ms, { cle: nouvelleCle(), role: "utilisateur", texte }]);
    setEnCours(true);
    setPremierMorceau(false);
    setAnnonce("");
    const ctrl = new AbortController();
    controleur.current = ctrl;
    const moteurInfo = etat?.moteurs.find((m) => m.id === moteur);

    const avis: AvisExpert[] = [];
    const surEvenement = (ev: EvenementDialogue) => {
      switch (ev.type) {
        case "avis":
          avis.push(ev.donnees);
          setAvisEnCours((a) => (a ? { ...a, recus: a.recus + 1 } : a));
          break;
        case "debut": {
          const d = ev.donnees as typeof ev.donnees & { experts?: { id: string }[] };
          if (d.experts) setAvisEnCours({ attendus: d.experts.length, recus: 0 });
          setActive(d.conversation_id);
          setConversations((cs) => {
            const existante = cs.find((c) => c.id === d.conversation_id);
            const maj = new Date().toISOString();
            const conv: ResumeConversation = existante
              ? { ...existante, titre: d.titre, maj_le: maj, nb_messages: existante.nb_messages + 1 }
              : { id: d.conversation_id, titre: d.titre, titre_source: "extrait", epinglee: false, archivee: false, cree_le: maj, maj_le: maj, nb_messages: 1 };
            return [conv, ...cs.filter((c) => c.id !== d.conversation_id)];
          });
          break;
        }
        case "delta":
          setPremierMorceau(true);
          setMessages((ms) => {
            const dernier = ms.at(-1);
            if (dernier?.cle === cleJarvis) return [...ms.slice(0, -1), { ...dernier, texte: dernier.texte + ev.donnees.texte }];
            return [...ms, { cle: cleJarvis, role: "jarvis", texte: ev.donnees.texte, enCours: true, ...(avis.length ? { meta: { conseil: [...avis] } } : {}) }];
          });
          break;
        case "fin":
          setMessages((ms) => [...ms.filter((m) => m.cle !== cleJarvis), { cle: cleJarvis, role: "jarvis", texte: ev.donnees.texte, meta: ev.donnees }]);
          setConversations((cs) => cs.map((c, i) => (i === 0 ? { ...c, nb_messages: c.nb_messages + 1 } : c)));
          setAnnonce("Réponse de JARVIS terminée.");
          break;
        case "erreur":
          setMessages((ms) => [
            ...ms.map((m) => (m.cle === cleJarvis ? { ...m, enCours: false, meta: { ...m.meta, interrompu: true } } : m)),
            { cle: nouvelleCle(), role: "erreur", texte: ev.donnees.message },
          ]);
          signalerAlerte();
          break;
      }
    };

    const demande = {
      message: texte,
      ...(active ? { conversation_id: active } : {}),
      moteur,
      ...(moteur !== "auto" && modeles[moteur] ? { modele: modeles[moteur] } : {}),
      ...(moteurInfo?.efforts.length && effort ? { effort } : {}),
    };
    const appel = conseil
      ? conseiller({ question: texte, ...(active ? { conversation_id: active } : {}) }, surEvenement, ctrl.signal)
      : dialoguer(demande, surEvenement, ctrl.signal);
    appel
      .catch((err: unknown) => {
        const message = err instanceof ErreurApi || err instanceof Error ? err.message : "Réponse impossible.";
        setMessages((ms) => [...ms, { cle: nouvelleCle(), role: "erreur", texte: message }]);
        signalerAlerte();
        if (err instanceof ErreurApi && err.statut === 423) rafraichir();
      })
      .finally(() => {
        if (ctrl.signal.aborted) {
          setMessages((ms) => ms.map((m) => (m.cle === cleJarvis && m.enCours ? { ...m, enCours: false, meta: { ...m.meta, interrompu: true } } : m)));
        }
        setEnCours(false);
        setAvisEnCours(null);
        if (controleur.current === ctrl) controleur.current = null;
      });
  };

  const arreter = () => {
    controleur.current?.abort();
  };

  const etatNoyau: EtatNoyau = alerte || urgence ? "alerte" : enCours ? (premierMorceau ? "parole" : "reflexion") : "repos";
  const moteurs = etat?.moteurs ?? [];
  const titreActif = conversations.find((c) => c.id === active)?.titre;
  const nbDemandes = etat?.demandes.length ?? 0;

  const actionsDialogue = (
    <div className="panneau-actions">
      {active && (
        <>
          <button type="button" className="btn btn-discret btn-mini" title="Archiver (🟡, demande votre accord)" onClick={() => { agirSurConversation("conversation.archiver"); }}>
            Archiver
          </button>
          <button type="button" className="btn btn-discret btn-mini btn-danger" title="Supprimer définitivement (🔴, clé d'accès)" onClick={() => { agirSurConversation("conversation.supprimer"); }}>
            Supprimer
          </button>
        </>
      )}
      <button type="button" className="btn btn-mini" onClick={nouvelle}>
        <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 5v14M5 12h14" />
        </svg>
        Nouvelle
      </button>
    </div>
  );

  const ONGLETS: { id: Onglet; nom: string; pastille?: number }[] = [
    { id: "conversations", nom: "Conversations" },
    { id: "demandes", nom: "Demandes", pastille: nbDemandes },
    { id: "securite", nom: "Sécurité" },
  ];

  return (
    <div className="hud" data-noyau={etatNoyau}>
      <div className="fond" aria-hidden="true">
        <div className="fond-grille" />
      </div>

      <header className="barre">
        <div className="barre-marque">
          <Reacteur etat={etatNoyau} compact />
          <span className="marque">JARVIS</span>
          <span className="marque-version">2</span>
        </div>
        <div className="barre-etat" role="status">
          <span className="point-etat" data-ok={erreurEtat ? false : etat ? !urgence : undefined} aria-hidden="true" />
          <span className="barre-etat-texte">{erreurEtat ? "Core hors ligne" : etat ? (urgence ? "Arrêt d'urgence" : "Core en ligne") : "Connexion…"}</span>
        </div>
        <button
          type="button"
          className="btn btn-discret btn-mini btn-connecteurs"
          aria-pressed={vue === "connecteurs"}
          onClick={() => {
            setVue((v) => (v === "connecteurs" ? "dialogue" : "connecteurs"));
          }}
        >
          Connecteurs
        </button>
        <button
          type="button"
          className="btn btn-discret btn-mini btn-connecteurs"
          aria-pressed={vue === "agents"}
          onClick={() => {
            setVue((v) => (v === "agents" ? "dialogue" : "agents"));
          }}
        >
          Agents
        </button>
        <SelecteurTheme className="selecteur-theme--barre" />
        {!urgence && etat && (
          <button type="button" className="btn btn-rouge btn-mini btn-urgence" onClick={declencherUrgence} title="Tout arrêter tout de suite">
            <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 3v9M6.3 6.3a8 8 0 1 0 11.4 0" />
            </svg>
            <span className="btn-urgence-texte">Arrêt d'urgence</span>
          </button>
        )}
        <button
          type="button"
          className="icone-btn btn-historique"
          aria-label={`Panneau latéral${nbDemandes ? ` (${String(nbDemandes)} demande${nbDemandes > 1 ? "s" : ""} en attente)` : ""}`}
          aria-expanded={lateralOuvert}
          onClick={() => {
            setLateralOuvert((o) => !o);
          }}
        >
          <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 6h16M4 12h16M4 18h10" />
          </svg>
          {nbDemandes > 0 && <span className="pastille pastille--ambre">{nbDemandes}</span>}
        </button>
        {urgence && (
          <div className="bandeau-urgence" role="alert">
            <span>
              <b>Arrêt d'urgence actif</b>
              {etat?.urgence.par ? ` · déclenché par ${etat.urgence.par.replace(/^appareil:/, "")}` : ""} : plus aucune
              action n'est acceptée.
            </span>
            <button type="button" className="btn btn-mini" onClick={demanderLevee}>
              Lever l'arrêt (clé d'accès)
            </button>
          </div>
        )}
      </header>

      <aside className="colonne-gauche">
        <Panneau titre="Noyau" className="panneau-noyau" ordre={0}>
          <div className="zone-noyau">
            <Reacteur etat={etatNoyau} />
          </div>
        </Panneau>
        <Panneau titre="État" className="panneau-etat" ordre={1} meta={etat ? `v${etat.version}` : undefined}>
          <ul className="etat-liste">
            <li className="etat-item">
              <span className="point-etat" data-ok={erreurEtat ? false : etat ? !urgence : undefined} aria-hidden="true" />
              <span className="etat-nom">JARVIS-Core</span>
              <span className="etat-valeur">{erreurEtat ? "hors ligne" : etat ? (urgence ? "arrêt d'urgence" : "en ligne") : "…"}</span>
            </li>
            {etat && (
              <li className="etat-item" title={`${String(etat.memoire.noyau)} souvenirs noyau · ${String(etat.memoire.local_uniquement)} privés (IA locales uniquement)`}>
                <span className="point-etat" data-ok={etat.memoire.total > 0} aria-hidden="true" />
                <span className="etat-nom">Mémoire</span>
                <span className="etat-valeur">{etat.memoire.total.toLocaleString("fr-FR")} souvenirs</span>
              </li>
            )}
            {moteurs.map((m) => (
              <li className="etat-item" key={m.id} title={m.detail}>
                <span className="point-etat" data-ok={m.disponible} aria-hidden="true" />
                <span className="etat-nom">{m.nom}</span>
                <span className="etat-valeur">{m.disponible ? `${String(m.modeles.length)} modèle${m.modeles.length > 1 ? "s" : ""}` : "arrêté"}</span>
              </li>
            ))}
            {etat && (
              <li className="etat-item">
                <span className="point-etat" aria-hidden="true" />
                <button
                  type="button"
                  className="etat-nom etat-lien"
                  onClick={() => {
                    setVue("accueil");
                  }}
                >
                  Installation
                </button>
                <span className="etat-valeur">diagnostic</span>
              </li>
            )}
            {etat && (
              <li className="etat-item">
                <span className="point-etat" data-ok={nbDemandes === 0} aria-hidden="true" />
                <button type="button" className="etat-nom etat-lien" onClick={montrerDemandes}>
                  Demandes
                </button>
                <span className="etat-valeur">{nbDemandes ? `${String(nbDemandes)} en attente` : "aucune"}</span>
              </li>
            )}
          </ul>
        </Panneau>
      </aside>

      <main className="scene">
        {vue === "accueil" ? (
          <Panneau titre="Installation" className="panneau-scene" ordre={2} id="accueil" meta="premier lancement">
            <div className="panneau-corps">
              <VueAccueil
                surChangement={rafraichir}
                surTermine={() => {
                  setVue("dialogue");
                  rafraichir("JARVIS est prêt.");
                }}
              />
            </div>
          </Panneau>
        ) : vue === "agents" ? (
          <Panneau
            titre="Agents"
            className="panneau-scene"
            ordre={2}
            id="agents"
            meta="missions, recettes, mémoire, outils MCP"
            actions={
              <button
                type="button"
                className="btn btn-mini"
                onClick={() => {
                  setVue("dialogue");
                }}
              >
                Retour au dialogue
              </button>
            }
          >
            <div className="panneau-corps">
              <VueAgents
                surChangement={rafraichir}
                surOuvrirConversation={(id) => {
                  setVue("dialogue");
                  ouvrir(id);
                }}
                surAction={(r) => {
                  suiteAction(r, "Outil appelé.");
                }}
              />
            </div>
          </Panneau>
        ) : vue === "connecteurs" ? (
          <Panneau
            titre="Connecteurs"
            className="panneau-scene"
            ordre={2}
            id="connecteurs"
            meta="vos IA : comptes, clés d'API, modèles locaux"
            actions={
              <button
                type="button"
                className="btn btn-mini"
                onClick={() => {
                  setVue("dialogue");
                }}
              >
                Retour au dialogue
              </button>
            }
          >
            <div className="panneau-corps">
              <VueConnecteurs surChangement={rafraichir} />
            </div>
          </Panneau>
        ) : (
        <Panneau titre="Dialogue" className="panneau-scene" ordre={2} id="dialogue" meta={titreActif ?? "Nouvelle conversation"} actions={actionsDialogue}>
            {erreurEtat ? (
              <div className="vide">
                <p className="vide-titre">Le Core ne répond pas</p>
                <p>{erreurEtat}</p>
                <button
                  type="button"
                  className="btn btn-principal"
                  onClick={() => {
                    charger();
                  }}
                >
                  Réessayer
                </button>
              </div>
            ) : (
              <>
                <Fil
                messages={messages}
                moteurs={moteurs}
                reflexion={enCours && !premierMorceau}
                chargement={chargement || !etat}
                {...(avisEnCours ? { etapeReflexion: `Conseil : ${String(avisEnCours.recus)} avis sur ${String(avisEnCours.attendus)}…` } : {})}
              />
                <Console
                  moteurs={moteurs}
                  moteur={moteur}
                  modele={modeles[moteur] ?? ""}
                  effort={effort}
                  enCours={enCours}
                  bloquee={urgence}
                conseil={conseil}
                surConseil={setConseil}
                  surMoteur={setMoteur}
                  surModele={(id) => {
                    setModeles((ms) => ({ ...ms, [moteur]: id }));
                  }}
                  surEffort={setEffort}
                  surEnvoyer={envoyer}
                  surArreter={arreter}
                />
              </>
            )}
          </Panneau>
        )}
      </main>

      <aside className="colonne-droite" data-ouvert={lateralOuvert || undefined}>
        <section className="panneau panneau-lateral" style={{ "--ordre": 3 } as React.CSSProperties} aria-label="Panneau latéral">
          <header className="panneau-tete panneau-tete--onglets">
            <div className="onglets" role="tablist" aria-label="Vues">
              {ONGLETS.map((o) => (
                <button
                  key={o.id}
                  type="button"
                  role="tab"
                  className="onglet"
                  id={`onglet-${o.id}`}
                  aria-selected={onglet === o.id}
                  aria-controls={`vue-${o.id}`}
                  onClick={() => {
                    setOnglet(o.id);
                  }}
                >
                  {o.nom}
                  {o.pastille ? <span className="pastille pastille--ambre">{o.pastille}</span> : null}
                </button>
              ))}
            </div>
            <button
              type="button"
              className="icone-btn petit btn-fermer-historique"
              aria-label="Fermer"
              onClick={() => {
                setLateralOuvert(false);
              }}
            >
              <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </header>
          <div className="panneau-corps" role="tabpanel" id={`vue-${onglet}`} aria-labelledby={`onglet-${onglet}`}>
            {onglet === "conversations" && <ListeConversations conversations={conversations} active={active} surChoisir={ouvrir} />}
            {onglet === "demandes" && <ListeDemandes demandes={etat?.demandes ?? []} nbCles={etat?.cles_acces ?? 0} surChangement={rafraichir} />}
            {onglet === "securite" && <PanneauSecurite nbCles={etat?.cles_acces ?? 0} surChangement={rafraichir} />}
          </div>
        </section>
      </aside>
      {lateralOuvert && (
        <div
          className="voile-historique"
          aria-hidden="true"
          onClick={() => {
            setLateralOuvert(false);
          }}
        />
      )}
      {notif && (
        <div className="notif" role="status">
          {notif}
        </div>
      )}
      <p className="visuellement-cache" aria-live="polite">
        {annonce}
      </p>
    </div>
  );
}
