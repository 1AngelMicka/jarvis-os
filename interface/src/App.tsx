import { useCallback, useEffect, useRef, useState } from "react";

import { arreterUrgence, conseiller, demanderAction, dialoguer, ErreurApi, leverUrgence, lireAccueil, lireActivite, lireConversation, lireEtat, lireNouveautes, listerDemandes, resumerConversation, sonderCore } from "./api";
import { EVENEMENT_NON_AUTORISE, lireJeton } from "./auth";
import { VueAccueil } from "./composants/Accueil";
import { type CibleActivite, PanneauActivite } from "./composants/Activite";
import { VueAgents } from "./composants/Agents";
import { VueAteliers } from "./composants/Ateliers";
import { VueConnecteurs } from "./composants/Connecteurs";
import { VueCouts } from "./composants/Couts";
import { ListeDemandes } from "./composants/Demandes";
import { Console, EVENEMENT_JOINDRE, Fil, type MessageAffiche } from "./composants/Dialogue";
import { Aide, type ModePalette, Palette } from "./composants/Palette";
import { commande as infoCommande, commandeDuRaccourci, type IdCommande, themeDepuis, themeSuivant } from "./commandes";
import type { ImageJointe } from "./images";
import { choisirTheme, lireTheme, THEMES, type Theme } from "./theme";
import { ListeConversations } from "./composants/Historique";
import { VueMemoire } from "./composants/VueMemoire";
import { VueConnaissances } from "./composants/Connaissances";
import { AccueilMatin } from "./composants/Matin";
import { EcranJumelage } from "./composants/Jumelage";
import { Panneau } from "./composants/Panneau";
import { type EtatNoyau, Reacteur } from "./composants/Reacteur";
import { PanneauSecurite } from "./composants/Securite";
import { CommandesVoix } from "./composants/Voix";
import { SelecteurTheme } from "./composants/SelecteurTheme";
import { ecrirePreferences, lirePreferences } from "./preferences";
import { couperVoix, LecteurVocal } from "./voix";
import type { Activite, AvisExpert, Etat, EvenementDialogue, InfoMoteur, MessageStocke, ReponseAction, ResumeConversation } from "./types";

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

type Onglet = "conversations" | "activite" | "demandes" | "securite";

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
  const [vue, setVue] = useState<"dialogue" | "connecteurs" | "accueil" | "agents" | "ateliers" | "memoire" | "connaissances" | "couts">("dialogue");
  const [conseil, setConseil] = useState(false);
  const [avisEnCours, setAvisEnCours] = useState<{ attendus: number; recus: number } | null>(null);
  const [annonce, setAnnonce] = useState("");
  const [notif, setNotif] = useState<string | null>(null);
  // Panneau Activité (chantiers, missions, ateliers, créations) et élément à ouvrir dans une vue
  const [activite, setActivite] = useState<Activite | null>(null);
  const [erreurActivite, setErreurActivite] = useState<string | null>(null);
  const [cible, setCible] = useState<CibleActivite | null>(null);
  const [palette, setPalette] = useState<{ mode: ModePalette; requete: string } | null>(null);
  const [aide, setAide] = useState(false);
  const controleur = useRef<AbortController | null>(null);
  const lecteur = useRef(new LecteurVocal()).current;
  const [rejouerMatin, setRejouerMatin] = useState(0); // « Rejouer l'accueil » du matin (panneau État)
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

  // « JARVIS a appris : … » : ce qui entre dans la mémoire (missions, résumés, imports) est signalé une fois
  const signalerAppris = useCallback(async () => {
    const CLE = "jarvis2.memoire.vu";
    let vu: string | null = null;
    try {
      vu = localStorage.getItem(CLE);
    } catch {
      /* stockage indisponible : pas de notification, rien de grave */
    }
    const maintenant = new Date().toISOString();
    try {
      if (!vu) return;
      const r = await lireNouveautes(vu);
      const premier = r.souvenirs[0];
      if (r.nombre && premier) {
        const apercu = premier.contenu.length > 90 ? `${premier.contenu.slice(0, 89)}…` : premier.contenu;
        notifier(`JARVIS a appris : ${apercu}${r.nombre > 1 ? ` (+${String(r.nombre - 1)})` : ""}`);
      }
    } catch {
      return; // Core injoignable : on retentera
    } finally {
      try {
        localStorage.setItem(CLE, maintenant);
      } catch {
        /* idem */
      }
    }
  }, [notifier]);

  const rafraichirActivite = useCallback(() => {
    lireActivite()
      .then((a) => {
        setErreurActivite(null);
        setActivite((avant) => (avant && JSON.stringify(avant) === JSON.stringify(a) ? avant : a));
      })
      .catch((e: unknown) => {
        setErreurActivite(e instanceof Error ? e.message : "Activité illisible.");
      });
  }, []);
  useEffect(rafraichirActivite, [rafraichirActivite]);
  // L'élément ciblé depuis l'Activité ne vaut que pour la vue qu'il a ouverte
  useEffect(() => {
    setCible((c) => (c && c.vue !== vue ? null : c));
  }, [vue]);

  // Surveillance de la connexion : l'état « Core en ligne / hors ligne » suit la réalité (toutes les 15 s, et dès que la
  // fenêtre revient au premier plan) ; au retour du Core, tout est rechargé.
  const horsLigne = erreurEtat !== null;
  useEffect(() => {
    const sonder = () => {
      sonderCore()
        .then(() => {
          if (horsLigne) {
            charger(false);
            return;
          }
          // File d'approbations : une demande créée ou close ailleurs (autre appareil, expiration) apparaît ici
          void signalerAppris();
          rafraichirActivite(); // panneau Activité et sa pastille
          return listerDemandes().then(({ demandes }) => {
            setEtat((e) => (e && JSON.stringify(e.demandes) !== JSON.stringify(demandes) ? { ...e, demandes } : e));
          });
        })
        .catch(() => {
          if (!horsLigne) setErreurEtat("Core injoignable.");
        });
    };
    const minuterie = window.setInterval(sonder, 15000);
    const auRetour = () => {
      if (document.visibilityState === "visible") sonder();
    };
    document.addEventListener("visibilitychange", auRetour);
    window.addEventListener("online", sonder);
    return () => {
      window.clearInterval(minuterie);
      document.removeEventListener("visibilitychange", auRetour);
      window.removeEventListener("online", sonder);
    };
  }, [horsLigne, charger, signalerAppris, rafraichirActivite]);

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
    setVue("dialogue"); // depuis n'importe quelle vue (assistant, connecteurs…), la conversation s'affiche
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
    setVue("dialogue");
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

  const resumer = () => {
    if (!active) return;
    notifier("Résumé en cours…");
    resumerConversation(active)
      .then((r) => {
        notifier(
          r.statut === "ok"
            ? `Résumé ajouté à la mémoire${r.prive ? " (privé : IA locale)" : ""}.`
            : `Pas de résumé : ${r.raison ?? "rien à résumer"}.`,
        );
      })
      .catch((e: unknown) => {
        notifier(e instanceof Error ? e.message : "Résumé impossible.");
      });
  };

  const mettreAJourConversation = useCallback((conv: ResumeConversation) => {
    setConversations((cs) => {
      const autres = cs.filter((c) => c.id !== conv.id);
      if (conv.archivee) return autres;
      const liste = cs.some((c) => c.id === conv.id) ? cs.map((c) => (c.id === conv.id ? conv : c)) : [conv, ...autres];
      return [...liste].sort((a, b) => Number(b.epinglee) - Number(a.epinglee) || b.maj_le.localeCompare(a.maj_le));
    });
  }, []);

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

  const envoyer = (texte: string, images: ImageJointe[] = []) => {
    const cleJarvis = nouvelleCle();
    const affichees = images.map(({ id, nom, dataUrl, poids }) => ({ id, nom, dataUrl, poids }));
    setMessages((ms) => [...ms, { cle: nouvelleCle(), role: "utilisateur", texte, ...(affichees.length ? { images: affichees } : {}) }]);
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
          if (d.avertissement) notifier(d.avertissement); // plafond de dépenses atteint : réponse par une autre IA
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
          lecteur.pousser(ev.donnees.texte);
          setPremierMorceau(true);
          setMessages((ms) => {
            const dernier = ms.at(-1);
            if (dernier?.cle === cleJarvis) return [...ms.slice(0, -1), { ...dernier, texte: dernier.texte + ev.donnees.texte }];
            return [...ms, { cle: cleJarvis, role: "jarvis", texte: ev.donnees.texte, enCours: true, ...(avis.length ? { meta: { conseil: [...avis] } } : {}) }];
          });
          break;
        case "fin":
          lecteur.finir();
          setMessages((ms) => [...ms.filter((m) => m.cle !== cleJarvis), { cle: cleJarvis, role: "jarvis", texte: ev.donnees.texte, meta: ev.donnees }]);
          setConversations((cs) => cs.map((c, i) => (i === 0 ? { ...c, nb_messages: c.nb_messages + 1 } : c)));
          setAnnonce("Réponse de JARVIS terminée.");
          break;
        case "invente": // déjà dans la meta de « fin » ; repris ici si l'ordre des événements change
          setMessages((ms) => ms.map((m) => (m.cle === cleJarvis ? { ...m, meta: { ...m.meta, invente: ev.donnees.affirmations } } : m)));
          break;
        case "titre":
          setConversations((cs) => cs.map((c) => (c.id === ev.donnees.conversation_id ? { ...c, titre: ev.donnees.titre, titre_source: "auto" } : c)));
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
      ...(images.length ? { images: images.map((i) => i.dataUrl) } : {}),
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
    lecteur.arreter();
    controleur.current?.abort();
  };

  // --- Commandes : palette Ctrl+K, « / » dans la saisie, raccourcis ---
  const changerTheme = (t: Theme) => {
    choisirTheme(t);
    notifier(`Thème : ${THEMES.find((x) => x.id === t)?.nom ?? t}.`);
  };

  const executer = (id: IdCommande, argument = "") => {
    const vues: Partial<Record<IdCommande, typeof vue>> = {
      memoire: "memoire",
      connecteurs: "connecteurs",
      agents: "agents",
      ateliers: "ateliers",
      dialogue: "dialogue",
      installation: "accueil",
    };
    const versVue = vues[id];
    if (versVue) {
      setVue(versVue);
      setLateralOuvert(false);
      return;
    }
    switch (id) {
      case "nouvelle":
        nouvelle();
        break;
      case "historique":
        setOnglet("conversations");
        setLateralOuvert(true);
        // Large écran : la colonne est déjà visible, le focus va à sa recherche
        window.setTimeout(() => {
          document.querySelector<HTMLElement>(".colonne-droite input")?.focus();
        }, 0);
        break;
      case "chercher":
        setPalette({ mode: "conversations", requete: argument });
        break;
      case "theme": {
        const t = argument ? themeDepuis(argument) : themeSuivant(lireTheme());
        if (t) changerTheme(t);
        else notifier(`Thème inconnu : « ${argument} ». Thèmes : ${THEMES.map((x) => x.nom).join(", ")}.`);
        break;
      }
      case "demandes":
        montrerDemandes();
        break;
      case "securite":
        setOnglet("securite");
        setLateralOuvert(true);
        break;
      case "silence":
        couperVoix(lecteur);
        notifier("Voix coupée.");
        break;
      case "image":
        setVue("dialogue");
        window.setTimeout(() => {
          window.dispatchEvent(new CustomEvent(EVENEMENT_JOINDRE));
        }, 0);
        break;
      case "resumer":
        if (active) resumer();
        else notifier("Aucune conversation ouverte à résumer.");
        break;
      case "urgence":
        setPalette({ mode: "urgence", requete: "" });
        break;
      case "aide":
        setAide(true);
        break;
      case "palette":
        setPalette((pal) => (pal ? null : { mode: "tout", requete: "" }));
        break;
      default:
        notifier(`${infoCommande(id).nom} : indisponible ici.`);
    }
  };
  const executerRef = useRef(executer);
  executerRef.current = executer;

  // Depuis la palette : elle se ferme d'abord (le focus revient), puis la commande agit
  const depuisPalette = (action: () => void) => {
    setPalette(null);
    window.setTimeout(action, 0);
  };

  useEffect(() => {
    const surTouche = (e: KeyboardEvent) => {
      const id = commandeDuRaccourci(e);
      if (id) {
        e.preventDefault();
        executerRef.current(id);
        return;
      }
      const cible = e.target as HTMLElement | null;
      const saisie = cible?.closest("input, textarea, select, [contenteditable='true']");
      if (e.key === "?" && !saisie && !e.ctrlKey && !e.metaKey && !e.altKey && !document.querySelector("dialog[open]")) {
        e.preventDefault();
        setAide(true);
      }
    };
    window.addEventListener("keydown", surTouche);
    return () => {
      window.removeEventListener("keydown", surTouche);
    };
  }, []);

  const etatNoyau: EtatNoyau = alerte || urgence ? "alerte" : enCours ? (premierMorceau ? "parole" : "reflexion") : "repos";
  const moteurs = etat?.moteurs ?? [];
  const titreActif = conversations.find((c) => c.id === active)?.titre;
  const nbDemandes = etat?.demandes.length ?? 0;

  const actionsDialogue = (
    <div className="panneau-actions">
      {active && (
        <>
          <button type="button" className="btn btn-discret btn-mini" title="Résumer cette conversation dans la mémoire (sinon chaque nuit)" onClick={resumer}>
            Résumer
          </button>
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
    { id: "activite", nom: "Activité", pastille: activite?.en_cours ?? 0 },
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
        <nav className="barre-nav" aria-label="Vues">
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
            aria-pressed={vue === "couts"}
            onClick={() => {
              setVue((v) => (v === "couts" ? "dialogue" : "couts"));
            }}
          >
            Coûts
          </button>
          <button
            type="button"
            className="btn btn-discret btn-mini btn-connecteurs"
            aria-pressed={vue === "memoire"}
            onClick={() => {
              setVue((v) => (v === "memoire" ? "dialogue" : "memoire"));
            }}
          >
            Mémoire
          </button>
          <button
            type="button"
            className="btn btn-discret btn-mini btn-connecteurs"
            aria-pressed={vue === "connaissances"}
            onClick={() => {
              setVue((v) => (v === "connaissances" ? "dialogue" : "connaissances"));
            }}
          >
            Savoir
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
          <button
            type="button"
            className="btn btn-discret btn-mini btn-connecteurs"
            aria-pressed={vue === "ateliers"}
            onClick={() => {
              setVue((v) => (v === "ateliers" ? "dialogue" : "ateliers"));
            }}
          >
            Ateliers
          </button>
        </nav>
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
                <span className="point-etat" aria-hidden="true" />
                <button
                  type="button"
                  className="etat-nom etat-lien"
                  disabled={urgence}
                  onClick={() => {
                    setVue("dialogue");
                    setRejouerMatin((n) => n + 1);
                  }}
                >
                  Accueil du matin
                </button>
                <span className="etat-valeur">rejouer</span>
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
        ) : vue === "ateliers" ? (
          <Panneau
            titre="Ateliers"
            className="panneau-scene"
            ordre={2}
            id="ateliers"
            meta="Claude Code dans vos projets, un worktree par atelier"
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
              <VueAteliers
                initial={cible?.vue === "ateliers" ? cible.id : undefined}
                surChangement={rafraichir}
                surAction={(r) => {
                  suiteAction(r, "Atelier fusionné.");
                }}
              />
            </div>
          </Panneau>
        ) : vue === "memoire" ? (
          <Panneau
            titre="Mémoire"
            className="panneau-scene"
            ordre={2}
            id="memoire"
            meta="tout ce que JARVIS sait, par origine"
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
              <VueMemoire surChangement={rafraichir} />
            </div>
          </Panneau>
        ) : vue === "connaissances" ? (
          <Panneau
            titre="Connaissances"
            className="panneau-scene"
            ordre={2}
            id="connaissances"
            meta="domaines, cartes, fiches, révisions"
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
              <VueConnaissances surChangement={rafraichir} />
            </div>
          </Panneau>
        ) : vue === "agents" ? (
          <Panneau
            titre="Agents"
            className="panneau-scene"
            ordre={2}
            id="agents"
            meta="missions, recettes, créations, outils MCP"
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
                cible={cible?.vue === "agents" ? cible : null}
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
        ) : vue === "couts" ? (
          <Panneau
            titre="Coûts"
            className="panneau-scene"
            ordre={2}
            id="couts"
            meta="dépenses, plafonds, abonnement Claude"
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
              <VueCouts />
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
                {etat && <AccueilMatin lecteur={lecteur} urgence={urgence} rejouer={rejouerMatin} surNotifier={notifier} />}
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
                  surCommande={executer}
                  surArreter={arreter}
                  extras={
                    <CommandesVoix
                      lecteur={lecteur}
                      enCours={enCours}
                      bloquee={urgence}
                      surEnvoyer={envoyer}
                      surNotifier={notifier}
                      surDescription={(texte) => {
                        setMessages((ms) => [...ms, { cle: nouvelleCle(), role: "jarvis", texte: `Votre écran : ${texte}` }]);
                        lecteur.pousser(`${texte}\n`);
                        lecteur.finir();
                      }}
                    />
                  }
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
                  {o.pastille ? <span className={o.id === "demandes" ? "pastille pastille--ambre" : "pastille"}>{o.pastille}</span> : null}
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
            {onglet === "conversations" && <ListeConversations conversations={conversations} active={active} surChoisir={ouvrir} surMiseAJour={mettreAJourConversation} surErreur={notifier} />}
            {onglet === "activite" && (
              <PanneauActivite
                activite={activite}
                erreur={erreurActivite}
                surRafraichir={rafraichirActivite}
                surNotifier={notifier}
                surAction={(r) => {
                  suiteAction(r, "Chantier abandonné.");
                  rafraichirActivite();
                }}
                surOuvrir={(c) => {
                  setCible(c);
                  setVue(c.vue);
                  setLateralOuvert(false);
                }}
              />
            )}
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
      {palette && (
        <Palette
          mode={palette.mode}
          requeteInitiale={palette.requete}
          conversations={conversations}
          urgenceActive={urgence}
          surFermer={() => {
            setPalette(null);
          }}
          surCommande={(id) => {
            depuisPalette(() => {
              executer(id);
            });
          }}
          surTheme={(t) => {
            depuisPalette(() => {
              changerTheme(t);
            });
          }}
          surOuvrirConversation={(id) => {
            depuisPalette(() => {
              ouvrir(id);
            });
          }}
          surUrgence={() => {
            depuisPalette(declencherUrgence);
          }}
        />
      )}
      {aide && (
        <Aide
          surFermer={() => {
            setAide(false);
          }}
        />
      )}
    </div>
  );
}
