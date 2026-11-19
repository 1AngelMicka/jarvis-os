import { useCallback, useEffect, useRef, useState } from "react";

import { accorderImages, ajouterRegle, annulerDerniere, arreterUrgence, conseiller, creerAtelier, demanderAction, dialoguer, ErreurApi, executerCommandeRapide, lancerMission, leverUrgence, lireAccueil, lireActivite, lireConversation, lireEtat, lireNouveautes, lirePilotage, listerDemandes, proposerAmelioration, recevoirPartage, verifierLien, resumerConversation, sonderCore } from "./api";
import { choisirAnimations, estChoixAnimations } from "./animations";
import { aAppliquerSeules, EVENEMENT_PILOTAGE, texteVisible } from "./pilotage";
import { EVENEMENT_NON_AUTORISE, lireJeton } from "./auth";
import { emettre, estGadget, EVENEMENT_ECOUTER, EVENEMENT_PREREMPLIR, lireDecision, lireLien, lirePartage, nettoyerAdresse } from "./bureau";
import { VueAccueil } from "./composants/Accueil";
import { AppelDecision, CartePartage, Gadget, PropositionEcran } from "./composants/Bureau";
import { type CibleActivite, PanneauActivite } from "./composants/Activite";
import { VueAgents } from "./composants/Agents";
import { VueAmeliorations } from "./composants/Ameliorations";
import { VueAteliers } from "./composants/Ateliers";
import { VueConnecteurs } from "./composants/Connecteurs";
import { VueCouts } from "./composants/Couts";
import { ActionsAnnulables } from "./composants/ActionsAnnulables";
import { ListeDemandes } from "./composants/Demandes";
import { DicteeGlobale } from "./composants/Dictee";
import { Console, EVENEMENT_JOINDRE, Fil, type MessageAffiche } from "./composants/Dialogue";
import { FenetreAccordImages } from "./composants/AccordImages";
import { Aide, type ModePalette, Palette } from "./composants/Palette";
import { commande as infoCommande, commandeDuRaccourci, type IdCommande, themeDepuis, themeSuivant } from "./commandes";
import { t, tn } from "./i18n";
import { useLangue } from "./i18n/react";
import type { ImageJointe } from "./images";
import { choisirTheme, lireTheme, THEMES, type Theme } from "./theme";
import { ListeConversations } from "./composants/Historique";
import { VueMemoire } from "./composants/VueMemoire";
import { VueConnaissances } from "./composants/Connaissances";
import { type DemandeReglages, VueReglages } from "./composants/Reglages";
import { adresse as adresseReglages, lireAdresse, resoudre as resoudreReglage } from "./reglages";
import { AccueilMatin } from "./composants/Matin";
import { EcranJumelage } from "./composants/Jumelage";
import { Panneau } from "./composants/Panneau";
import { type EtatNoyau, Reacteur } from "./composants/Reacteur";
import { OrbeFond, Presence } from "./composants/Orbe";
import { etatPresence } from "./presence";
import { usePresence } from "./usePresence";
import { PanneauSecurite } from "./composants/Securite";
import { CommandesVoix } from "./composants/Voix";
import { SelecteurTheme } from "./composants/SelecteurTheme";
import { ecrirePreferences, lirePreferences } from "./preferences";
import { couperVoix, LecteurVocal } from "./voix";
import type { ActionPilotage, Activite, AvisExpert, Etat, EvenementDialogue, InfoMoteur, LienVerifie, MessageStocke, ModePilotage, Partage, ReponseAction, ResumeConversation } from "./types";
import { useAlertesVeille } from "./veilleClaude";
import { type ActionsWidgets, ContexteWidgets, WidgetsEpingles } from "./composants/Widgets";
import { epinglerWidget, retirerWidget, type Widget, type WidgetEpingle } from "./widgets";

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
  useLangue(); // un changement de langue redessine toute l'interface
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
    estGadget(window.location.search) ? (
      <Gadget />
    ) : (
      <Hud />
    )
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
  useLangue();
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
  const [compactage, setCompactage] = useState(false);
  const presence = usePresence();
  const [lateralOuvert, setLateralOuvert] = useState(false);
  const [onglet, setOnglet] = useState<Onglet>("conversations");
  const [vue, setVue] = useState<"dialogue" | "connecteurs" | "accueil" | "agents" | "ateliers" | "ameliorations" | "memoire" | "connaissances" | "couts" | "reglages">("dialogue");
  const [demandeReglages, setDemandeReglages] = useState<DemandeReglages | null>(null);
  const [conseil, setConseil] = useState(false);
  const [avisEnCours, setAvisEnCours] = useState<{ attendus: number; recus: number } | null>(null);
  // Phrase d'attente (14 · D 16) : un outil long a démarré (conseil, lecture d'images…)
  const [attente, setAttente] = useState<string | null>(null);
  // Widgets épinglés dans le HUD (14 · D 16), lus avec l'état au démarrage
  const [widgetsEpingles, setWidgetsEpingles] = useState<WidgetEpingle[]>([]);
  const [annonce, setAnnonce] = useState("");
  const [notif, setNotif] = useState<string | null>(null);
  // Panneau Activité (chantiers, missions, ateliers, créations) et élément à ouvrir dans une vue
  const [activite, setActivite] = useState<Activite | null>(null);
  const [erreurActivite, setErreurActivite] = useState<string | null>(null);
  const [cible, setCible] = useState<CibleActivite | null>(null);
  const [palette, setPalette] = useState<{ mode: ModePalette; requete: string } | null>(null);
  // Image jointe pour un connecteur cloud sans accord : rien n'est parti, la fenêtre d'accord attend la réponse
  const [accordImages, setAccordImages] = useState<{ connecteur: string; nom: string; texte: string; images: ImageJointe[]; cle: string } | null>(null);
  const [aide, setAide] = useState(false);
  // Bureau et téléphone (lot M) : appel de décision, contenu partagé, raccourci « écran »
  const [decision, setDecision] = useState<string | null>(null);
  const [partageRecu, setPartageRecu] = useState<{ partage: Partage; message: string } | null>(null);
  const [propositionEcran, setPropositionEcran] = useState(false);
  const controleur = useRef<AbortController | null>(null);
  const lecteur = useRef(new LecteurVocal()).current;
  const [rejouerMatin, setRejouerMatin] = useState(0); // « Rejouer l'accueil » du matin (panneau État)
  const minuterieNotif = useRef<number | undefined>(undefined);
  // Pilotage par JARVIS (lot F) : mode lu au démarrage et suivi quand il change dans les Réglages
  const modePilotage = useRef<ModePilotage>("demander");
  const [rechercheMemoire, setRechercheMemoire] = useState<{ texte: string; jeton: number } | null>(null);
  useEffect(() => {
    const lire = () => {
      lirePilotage()
        .then((p) => {
          modePilotage.current = p.mode;
        })
        .catch(() => {
          /* Core ancien ou injoignable : « Me demander » (prudent) */
        });
    };
    lire();
    window.addEventListener(EVENEMENT_PILOTAGE, lire);
    return () => {
      window.removeEventListener(EVENEMENT_PILOTAGE, lire);
    };
  }, []);

  const notifier = useCallback((message: string) => {
    setNotif(message);
    setAnnonce(message);
    window.clearTimeout(minuterieNotif.current);
    minuterieNotif.current = window.setTimeout(() => {
      setNotif(null);
    }, 4200);
  }, []);

  // Veille des sessions Claude Code (désactivée par défaut) : bandeau, voix si choisie, notification si page cachée
  useAlertesVeille((alerte, reglages) => {
    notifier(alerte.texte);
    if (reglages.voix) lecteur.lire(alerte.texte);
  });

  const charger = useCallback((initial = true) => {
    setErreurEtat(null);
    lireEtat()
      .then((e) => {
        setEtat(e);
        setConversations(e.conversations);
        if (e.widgets) setWidgetsEpingles(e.widgets);
        if (!initial) return;
        const prefs = lirePreferences();
        // « auto » : le routeur choisit ; un choix mémorisé n'est repris que s'il existe encore
        setMoteur(prefs.moteur && e.moteurs.some((m) => m.id === prefs.moteur) ? prefs.moteur : "auto");
        setModeles(Object.fromEntries(e.moteurs.map((m) => [m.id, modeleParDefaut(m, prefs.modeles?.[m.id])])));
        const claude = e.moteurs.find((m) => m.efforts.length);
        setEffort(prefs.effort && claude?.efforts.includes(prefs.effort) ? prefs.effort : (claude?.effort_defaut ?? ""));
      })
      .catch((err: unknown) => {
        setErreurEtat(err instanceof Error ? err.message : t("erreur.injoignableCourt"));
      });
  }, []);

  // Arrivée par un lien jarvis://, une notification ou un partage : l'assistant de premier lancement ne la masque pas
  const arriveeParLien = useRef(
    Boolean(lireLien(window.location.hash) ?? lireDecision(window.location.hash) ?? lirePartage(window.location.search)),
  );
  useEffect(() => {
    charger();
    // Premier lancement : l'assistant s'ouvre tant qu'il n'a pas été terminé
    lireAccueil()
      .then((a) => {
        // …sauf si une adresse directe (`#reglages/…`) ou un lien a déjà ouvert une autre vue
        if (!a.termine && !lireAdresse(window.location.hash) && !arriveeParLien.current) setVue("accueil");
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

  // Réglages : `#reglages/<catégorie ou section>` ouvre la vue (au chargement, depuis un lien, ou en changeant l'adresse) ;
  // l'adresse suit la catégorie affichée et disparaît quand on quitte la vue.
  const ouvrirReglages = useCallback((demande: Omit<DemandeReglages, "jeton"> = {}) => {
    setDemandeReglages({ ...demande, jeton: Date.now() });
    setVue("reglages");
    setLateralOuvert(false);
  }, []);
  useEffect(() => {
    const suivre = () => {
      const c = lireAdresse(window.location.hash);
      if (c) ouvrirReglages(c);
    };
    suivre();
    window.addEventListener("hashchange", suivre);
    return () => {
      window.removeEventListener("hashchange", suivre);
    };
  }, [ouvrirReglages]);
  useEffect(() => {
    // Téléphone : la rangée des vues défile de côté ; le bouton de la vue ouverte reste visible
    document.querySelector(".barre-nav [aria-pressed='true']")?.scrollIntoView({ block: "nearest", inline: "nearest" });
    if (vue !== "reglages" && window.location.hash.startsWith("#reglages")) history.replaceState(null, "", window.location.pathname + window.location.search);
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
          if (!horsLigne) setErreurEtat(t("erreur.injoignableCourt"));
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
    setCompactage(true);
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
      })
      .finally(() => {
        setCompactage(false);
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
    // Commande rapide : une phrase courte, sans image, hors conseil, reconnue par le Core SANS IA
    if (images.length || conseil || texte.length > 300) {
      envoyerIA(texte, images);
      return;
    }
    setEnCours(true);
    executerCommandeRapide(texte)
      .then(async (r) => {
        if (!r.trouvee || !r.commande) {
          envoyerIA(texte, images);
          return;
        }
        setEnCours(false);
        const reponse = await suiteCommandeRapide(r.action, r.resultat, r.erreur);
        setMessages((ms) => [
          ...ms,
          { cle: nouvelleCle(), role: "utilisateur", texte },
          { cle: nouvelleCle(), role: "jarvis", texte: reponse, rapide: true },
        ]);
        setAnnonce(reponse);
      })
      .catch(() => {
        envoyerIA(texte, images); // Core ancien ou erreur : la phrase part à l'IA, qui dira ce qui ne va pas
      });
  };

  /** « Annuler » (commande rapide, palette, /annuler) : la dernière action réversible exécutée. */
  const annulerDerniereAction = async (): Promise<string> => {
    try {
      const r = await annulerDerniere();
      rafraichir();
      return `Annulé : ${r.annulation.resume} (${r.annulation.comment.toLowerCase()}).`;
    } catch (e: unknown) {
      return e instanceof Error ? e.message : "Annulation impossible.";
    }
  };

  const suiteCommandeRapide = async (action: { type: string; libelle: string; genre?: string } | undefined, resultat: ReponseAction | undefined, erreur: string | undefined): Promise<string> => {
    if (erreur) return `Commande reconnue, mais refusée : ${erreur}`;
    if (!action) return "Commande reconnue.";
    if (resultat) {
      if (resultat.statut === "en_attente") {
        montrerDemandes();
        rafraichir();
        return `${resultat.demande.niveau === "rouge" ? "🔴" : "🟡"} En attente de votre accord : ${resultat.demande.resume}`;
      }
      rafraichir();
      return `Fait : ${action.libelle}.`;
    }
    if (action.type === "annuler") return annulerDerniereAction();
    try {
      return (await appliquerAction(action as ActionPilotage)) ?? `${action.libelle}.`;
    } catch (e: unknown) {
      return e instanceof Error ? e.message : "Action impossible.";
    }
  };

  const envoyerIA = (texte: string, images: ImageJointe[] = []) => {
    const cleJarvis = nouvelleCle();
    const cleUtilisateur = nouvelleCle();
    const affichees = images.map(({ id, nom, dataUrl, poids }) => ({ id, nom, dataUrl, poids }));
    setMessages((ms) => [...ms, { cle: cleUtilisateur, role: "utilisateur", texte, ...(affichees.length ? { images: affichees } : {}) }]);
    setEnCours(true);
    setPremierMorceau(false);
    setAttente(null);
    setAnnonce("");
    const ctrl = new AbortController();
    controleur.current = ctrl;
    const moteurInfo = etat?.moteurs.find((m) => m.id === moteur);

    const avis: AvisExpert[] = [];
    // Flux brut : le bloc d'actions de JARVIS n'est ni affiché ni lu à voix haute (le Core le retire à la fin)
    let brut = "";
    let lu = 0;
    const surEvenement = (ev: EvenementDialogue) => {
      switch (ev.type) {
        case "attente":
          // Phrase fixe du Core : affichée à la place de « réflexion », dite si la lecture à voix haute est active
          setAttente(ev.donnees.phrase);
          if (lecteur.actif) lecteur.pousser(`${ev.donnees.phrase}\n`);
          break;
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
        case "delta": {
          brut += ev.donnees.texte;
          const visible = texteVisible(brut);
          if (visible.length > lu) {
            lecteur.pousser(visible.slice(lu));
            lu = visible.length;
          }
          setPremierMorceau(true);
          setMessages((ms) => {
            const dernier = ms.at(-1);
            if (dernier?.cle === cleJarvis) return [...ms.slice(0, -1), { ...dernier, texte: visible }];
            return [...ms, { cle: cleJarvis, role: "jarvis", texte: visible, enCours: true, ...(avis.length ? { meta: { conseil: [...avis] } } : {}) }];
          });
          break;
        }
        case "fin": {
          lecteur.finir();
          // Mode « oui » : la vue ou l'élément demandé s'ouvre seul ; les propositions attendent toujours un clic
          const seules = aAppliquerSeules(ev.donnees.actions, modePilotage.current);
          for (const a of seules) {
            appliquerAction(a).catch((e: unknown) => {
              notifier(e instanceof Error ? e.message : "Action impossible.");
            });
          }
          setMessages((ms) => [
            ...ms.filter((m) => m.cle !== cleJarvis),
            { cle: cleJarvis, role: "jarvis", texte: ev.donnees.texte, meta: ev.donnees, ...(seules.length ? { actionsAppliquees: true } : {}) },
          ]);
          setConversations((cs) => cs.map((c, i) => (i === 0 ? { ...c, nb_messages: c.nb_messages + 1 } : c)));
          setAnnonce("Réponse de JARVIS terminée.");
          break;
        }
        case "invente": // déjà dans la meta de « fin » ; repris ici si l'ordre des événements change
          setMessages((ms) => ms.map((m) => (m.cle === cleJarvis ? { ...m, meta: { ...m.meta, invente: ev.donnees.affirmations } } : m)));
          break;
        case "titre":
          setConversations((cs) => cs.map((c) => (c.id === ev.donnees.conversation_id ? { ...c, titre: ev.donnees.titre, titre_source: "auto" } : c)));
          break;
        case "accord_images":
          setAccordImages({ connecteur: ev.donnees.connecteur, nom: ev.donnees.nom, texte, images, cle: cleUtilisateur });
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
        setAttente(null);
        if (controleur.current === ctrl) controleur.current = null;
      });
  };

  // --- Widgets générés (14 · D 16) : épingler, retirer, liens internes, fin d'un minuteur ---
  const epingler = (w: Widget) => {
    epinglerWidget(w)
      .then((r) => {
        setWidgetsEpingles((ws) => (ws.some((x) => x.id === r.widget.id) ? ws : [...ws, r.widget]));
        notifier(r.nouveau ? `Widget « ${r.widget.titre} » épinglé dans le HUD.` : "Ce widget est déjà épinglé.");
      })
      .catch((e: unknown) => {
        notifier(e instanceof Error ? e.message : "Épinglage impossible.");
      });
  };
  const retirerEpingle = (id: string) => {
    retirerWidget(id)
      .then(() => {
        setWidgetsEpingles((ws) => ws.filter((w) => w.id !== id));
        notifier("Widget retiré du HUD.");
      })
      .catch((e: unknown) => {
        notifier(e instanceof Error ? e.message : "Retrait impossible.");
      });
  };
  const rappelsWidgets: Pick<ActionsWidgets, "surNaviguer" | "surFinMinuteur"> = {
    surNaviguer: (v) => {
      appliquerAction({ type: "naviguer", genre: "immediate", niveau: "vert", libelle: "Ouvrir la vue", parametres: { vue: v } }).catch((e: unknown) => {
        notifier(e instanceof Error ? e.message : "Vue indisponible.");
      });
    },
    surFinMinuteur: (titre) => {
      const message = `Minuteur « ${titre} » terminé.`;
      notifier(message);
      if (lecteur.actif) lecteur.lire(message);
    },
  };
  const actionsWidgets: ActionsWidgets = { ...rappelsWidgets, epingles: new Set(widgetsEpingles.map((w) => w.empreinte)), surEpingler: epingler };

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
      case "reglages": {
        const c = argument.trim() ? resoudreReglage(argument) : null;
        ouvrirReglages(c ?? (argument.trim() ? { recherche: argument.trim() } : {}));
        break;
      }
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
      case "annuler":
        void annulerDerniereAction().then(notifier);
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

  // --- Liens jarvis:// (application de bureau, gadget, raccourcis) : vérifiés par le Core, action 🟢 au plus ---
  const appliquerLien = (l: LienVerifie) => {
    const p = l.parametres;
    switch (l.action) {
      case "ouvrir":
        void appliquerAction({ type: "naviguer", genre: "immediate", niveau: "vert", libelle: l.libelle, parametres: { vue: p.vue ?? "dialogue" } });
        break;
      case "conversation":
        if (p.id) ouvrir(p.id);
        break;
      case "nouvelle":
        nouvelle();
        break;
      case "ecouter":
        setVue("dialogue");
        window.setTimeout(() => {
          emettre(EVENEMENT_ECOUTER);
        }, 0);
        break;
      case "ecran":
        setVue("dialogue");
        setPropositionEcran(true);
        break;
      case "dire":
        setVue("dialogue");
        window.setTimeout(() => {
          emettre(EVENEMENT_PREREMPLIR, p.texte ?? "");
        }, 0);
        notifier("Texte reçu par un lien : relisez-le avant de l'envoyer.");
        break;
      case "decision":
        if (p.id) setDecision(p.id);
        break;
      case "gadget":
        notifier("Le gadget de bureau s'ouvre depuis l'application de bureau.");
        break;
    }
  };
  const appliquerLienRef = useRef(appliquerLien);
  appliquerLienRef.current = appliquerLien;
  useEffect(() => {
    const traiter = () => {
      const lien = lireLien(window.location.hash);
      const idDecision = lireDecision(window.location.hash);
      if (!lien && !idDecision) return;
      history.replaceState(null, "", window.location.pathname + window.location.search); // un rechargement ne le rejoue pas
      if (idDecision) setDecision(idDecision);
      if (lien)
        verifierLien(lien)
          .then((l) => {
            appliquerLienRef.current(l);
          })
          .catch((e: unknown) => {
            notifier(`Lien refusé : ${e instanceof Error ? e.message : "inconnu"}`);
          });
    };
    traiter();
    window.addEventListener("hashchange", traiter);
    return () => {
      window.removeEventListener("hashchange", traiter);
    };
  }, [notifier]);
  // « Partager vers JARVIS » (téléphone) : le contenu est gardé par le Core, affiché comme non fiable, rien ne part seul
  useEffect(() => {
    const recu = lirePartage(window.location.search);
    if (!recu) return;
    nettoyerAdresse();
    setVue("dialogue");
    recevoirPartage(recu)
      .then(setPartageRecu)
      .catch((e: unknown) => {
        notifier(`Partage non reçu : ${e instanceof Error ? e.message : "erreur"}`);
      });
  }, [notifier]);

  // --- JARVIS pilote l'interface : actions validées par le Core (lot F) ---
  const appliquerAction = async (a: ActionPilotage): Promise<string | undefined> => {
    const p = a.parametres;
    const texte = (cle: string) => (typeof p[cle] === "string" ? p[cle] : "");
    switch (a.type) {
      case "naviguer": {
        const v = texte("vue");
        if (v === "reglages") {
          const ancre = texte("ancre");
          ouvrirReglages(ancre ? (resoudreReglage(ancre) ?? { recherche: ancre }) : {});
        } else if (v === "historique" || v === "demandes" || v === "securite") {
          executer(v as IdCommande);
        } else if (v === "activite") {
          setOnglet("activite");
          setLateralOuvert(true);
        } else {
          setVue(v as typeof vue);
          setLateralOuvert(false);
        }
        return a.libelle;
      }
      case "ouvrir": {
        const id = texte("id");
        const objet = texte("objet");
        if (objet === "conversation") ouvrir(id);
        else if (objet === "atelier") {
          setVue("ateliers");
          setCible({ vue: "ateliers", id });
        } else {
          setVue("agents");
          setCible({ vue: "agents", type: objet === "creation" ? "creation" : "mission", id });
        }
        setLateralOuvert(false);
        return a.libelle;
      }
      case "rechercher_memoire":
        setRechercheMemoire({ texte: texte("requete"), jeton: Date.now() });
        setVue("memoire");
        return a.libelle;
      case "regler": {
        const valeur = texte("valeur");
        if (texte("cle") === "theme") {
          const t = themeDepuis(valeur);
          if (t) changerTheme(t);
        } else if (estChoixAnimations(valeur)) choisirAnimations(valeur);
        return a.libelle;
      }
      case "proposer_mission": {
        const type = texte("mission") as "recherche" | "brainstorm" | "revue";
        await lancerMission(type, texte("objectif"));
        rafraichirActivite();
        return "Mission lancée";
      }
      case "proposer_amelioration": {
        await proposerAmelioration({ projet: texte("projet"), titre: texte("titre"), raison: texte("raison"), origine: "jarvis" });
        setVue("ameliorations");
        return "Suggestion gardée";
      }
      case "proposer_atelier": {
        const atelier = await creerAtelier(texte("projet"), texte("nom"));
        setVue("ateliers");
        setCible({ vue: "ateliers", id: atelier.id });
        return "Atelier ouvert";
      }
      case "demander_action": {
        const parametres = (typeof p.parametres === "object" && p.parametres ? p.parametres : {}) as Record<string, unknown>;
        const r = await demanderAction({ action: texte("action"), parametres });
        suiteAction(r, "Fait.");
        return r.statut === "en_attente" ? "En attente de votre accord" : "Fait";
      }
      case "ajouter_regle": {
        const genre = texte("genre") === "demander" ? "demander" : "interdire";
        await ajouterRegle({ genre, motif: texte("motif"), libelle: texte("libelle"), origine: "jarvis" });
        return "Règle ajoutée";
      }
      default:
        return undefined;
    }
  };

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
  const etatOrbe = etatPresence({ enCours, premierMorceau, parle: presence.parle, microOuvert: presence.micro, compactage });
  const alerteOrbe = alerte || urgence;
  const moteurs = etat?.moteurs ?? [];
  const titreActif = conversations.find((c) => c.id === active)?.titre;
  const nbDemandes = etat?.demandes.length ?? 0;

  const actionsDialogue = (
    <div className="panneau-actions">
      {active && (
        <>
          <button type="button" className="btn btn-discret btn-mini" title={t("dialogue.resumerTitre")} onClick={resumer}>
            {t("dialogue.resumer")}
          </button>
          <button type="button" className="btn btn-discret btn-mini" title={t("dialogue.archiverTitre")} onClick={() => { agirSurConversation("conversation.archiver"); }}>
            {t("dialogue.archiver")}
          </button>
          <button type="button" className="btn btn-discret btn-mini btn-danger" title={t("dialogue.supprimerTitre")} onClick={() => { agirSurConversation("conversation.supprimer"); }}>
            {t("dialogue.supprimer")}
          </button>
        </>
      )}
      <button type="button" className="btn btn-mini" onClick={nouvelle}>
        <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 5v14M5 12h14" />
        </svg>
        {t("dialogue.nouvelle")}
      </button>
    </div>
  );

  const ONGLETS: { id: Onglet; nom: string; pastille?: number }[] = [
    { id: "conversations", nom: t("onglet.conversations") },
    { id: "activite", nom: t("onglet.activite"), pastille: activite?.en_cours ?? 0 },
    { id: "demandes", nom: t("onglet.demandes"), pastille: nbDemandes },
    { id: "securite", nom: t("onglet.securite") },
  ];

  return (
    <div className="hud" data-noyau={etatNoyau} data-orbe-fond={presence.fond || undefined}>
      <div className="fond" aria-hidden="true">
        <div className="fond-grille" />
        {presence.fond && <OrbeFond etat={etatOrbe} alerte={alerteOrbe} />}
      </div>

      <header className="barre">
        <div className="barre-marque">
          {presence.actif ? <Presence etat={etatOrbe} alerte={alerteOrbe} mode="compact" /> : <Reacteur etat={etatNoyau} compact />}
          <span className="marque">JARVIS</span>
          <span className="marque-version">2</span>
        </div>
        <div className="barre-etat" role="status">
          <span className="point-etat" data-ok={erreurEtat ? false : etat ? !urgence : undefined} aria-hidden="true" />
          <span className="barre-etat-texte">{erreurEtat ? t("barre.coreHorsLigne") : etat ? (urgence ? t("barre.urgence") : t("barre.coreEnLigne")) : t("barre.connexion")}</span>
        </div>
        <nav className="barre-nav" aria-label={t("barre.vues")}>
          <button
            type="button"
            className="btn btn-discret btn-mini btn-connecteurs"
            aria-pressed={vue === "connecteurs"}
            onClick={() => {
              setVue((v) => (v === "connecteurs" ? "dialogue" : "connecteurs"));
            }}
          >
            {t("vue.connecteurs")}
          </button>
          <button
            type="button"
            className="btn btn-discret btn-mini btn-connecteurs"
            aria-pressed={vue === "couts"}
            onClick={() => {
              setVue((v) => (v === "couts" ? "dialogue" : "couts"));
            }}
          >
            {t("vue.couts")}
          </button>
          <button
            type="button"
            className="btn btn-discret btn-mini btn-connecteurs"
            aria-pressed={vue === "memoire"}
            onClick={() => {
              setVue((v) => (v === "memoire" ? "dialogue" : "memoire"));
            }}
          >
            {t("vue.memoire")}
          </button>
          <button
            type="button"
            className="btn btn-discret btn-mini btn-connecteurs"
            aria-pressed={vue === "connaissances"}
            onClick={() => {
              setVue((v) => (v === "connaissances" ? "dialogue" : "connaissances"));
            }}
          >
            {t("vue.savoir")}
          </button>
          <button
            type="button"
            className="btn btn-discret btn-mini btn-connecteurs"
            aria-pressed={vue === "agents"}
            onClick={() => {
              setVue((v) => (v === "agents" ? "dialogue" : "agents"));
            }}
          >
            {t("vue.agents")}
          </button>
          <button
            type="button"
            className="btn btn-discret btn-mini btn-connecteurs"
            aria-pressed={vue === "ateliers"}
            onClick={() => {
              setVue((v) => (v === "ateliers" ? "dialogue" : "ateliers"));
            }}
          >
            {t("vue.ateliers")}
          </button>
          <button
            type="button"
            className="btn btn-discret btn-mini btn-connecteurs"
            aria-pressed={vue === "ameliorations"}
            onClick={() => {
              setVue((v) => (v === "ameliorations" ? "dialogue" : "ameliorations"));
            }}
          >
            {t("vue.ameliorer")}
          </button>
          <button
            type="button"
            className="btn btn-discret btn-mini btn-connecteurs"
            aria-pressed={vue === "reglages"}
            onClick={() => {
              if (vue === "reglages") setVue("dialogue");
              else ouvrirReglages();
            }}
          >
            {t("vue.reglages")}
          </button>
        </nav>
        <SelecteurTheme className="selecteur-theme--barre" />
        {!urgence && etat && (
          <button type="button" className="btn btn-rouge btn-mini btn-urgence" onClick={declencherUrgence} title={t("barre.urgenceTitre")}>
            <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 3v9M6.3 6.3a8 8 0 1 0 11.4 0" />
            </svg>
            <span className="btn-urgence-texte">{t("barre.urgence")}</span>
          </button>
        )}
        <button
          type="button"
          className="icone-btn btn-historique"
          aria-label={nbDemandes ? tn("barre.lateralDemandes", nbDemandes) : t("barre.lateral")}
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
              <b>{t("urgence.bandeau")}</b>
              {etat?.urgence.par ? t("urgence.declenchePar", { qui: etat.urgence.par.replace(/^appareil:/, "") }) : ""}
              {t("urgence.bandeauSuite")}
            </span>
            <button type="button" className="btn btn-mini" onClick={demanderLevee}>
              {t("urgence.lever")}
            </button>
          </div>
        )}
      </header>

      <aside className="colonne-gauche">
        <Panneau titre={t("panneau.noyau")} className="panneau-noyau" ordre={0}>
          <div className="zone-noyau">
            {presence.actif ? (
              <Presence etat={etatOrbe} alerte={alerteOrbe} mode="panneau" avecToile={!presence.fond} />
            ) : (
              <Reacteur etat={etatNoyau} />
            )}
          </div>
        </Panneau>
        <Panneau titre={t("panneau.etat")} className="panneau-etat" ordre={1} meta={etat ? `v${etat.version}` : undefined}>
          <ul className="etat-liste">
            <li className="etat-item">
              <span className="point-etat" data-ok={erreurEtat ? false : etat ? !urgence : undefined} aria-hidden="true" />
              <span className="etat-nom">JARVIS-Core</span>
              <span className="etat-valeur">{erreurEtat ? t("etat.horsLigne") : etat ? (urgence ? t("etat.urgence") : t("etat.enLigne")) : "…"}</span>
            </li>
            {etat && (
              <li className="etat-item" title={t("etat.memoireDetail", { noyau: etat.memoire.noyau, prives: etat.memoire.local_uniquement })}>
                <span className="point-etat" data-ok={etat.memoire.total > 0} aria-hidden="true" />
                <span className="etat-nom">{t("vue.memoire")}</span>
                <span className="etat-valeur">{tn("etat.souvenirs", etat.memoire.total)}</span>
              </li>
            )}
            {etat?.sans_ecran && (
              <li className="etat-item" title={t("etat.sansEcranDetail")}>
                <span className="point-etat" aria-hidden="true" />
                <span className="etat-nom">{t("etat.ecran")}</span>
                <span className="etat-valeur">{t("etat.sansEcran")}</span>
              </li>
            )}
            {moteurs.map((m) => (
              <li className="etat-item" key={m.id} title={m.detail}>
                <span className="point-etat" data-ok={m.disponible} aria-hidden="true" />
                <span className="etat-nom">{m.nom}</span>
                <span className="etat-valeur">{m.disponible ? tn("etat.modeles", m.modeles.length) : t("etat.arrete")}</span>
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
                  {t("etat.installation")}
                </button>
                <span className="etat-valeur">{t("etat.diagnostic")}</span>
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
                  {t("etat.matin")}
                </button>
                <span className="etat-valeur">{t("etat.rejouer")}</span>
              </li>
            )}
            {etat && (
              <li className="etat-item">
                <span className="point-etat" data-ok={nbDemandes === 0} aria-hidden="true" />
                <button type="button" className="etat-nom etat-lien" onClick={montrerDemandes}>
                  {t("etat.demandes")}
                </button>
                <span className="etat-valeur">{nbDemandes ? t("etat.enAttente", { n: nbDemandes }) : t("etat.aucune")}</span>
              </li>
            )}
          </ul>
        </Panneau>
        {widgetsEpingles.length > 0 && (
          <Panneau titre="Widgets" className="panneau-widgets" ordre={2} meta={`${String(widgetsEpingles.length)} épinglé${widgetsEpingles.length > 1 ? "s" : ""}`}>
            <WidgetsEpingles widgets={widgetsEpingles} surRetirer={retirerEpingle} {...rappelsWidgets} />
          </Panneau>
        )}
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
                {t("reglages.retourDialogue")}
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
        ) : vue === "ameliorations" ? (
          <Panneau
            titre="Améliorations"
            className="panneau-scene"
            ordre={2}
            id="ameliorations"
            meta="suggestions, atelier, aperçu testé, mise en service et retour arrière"
            actions={
              <button
                type="button"
                className="btn btn-mini"
                onClick={() => {
                  setVue("dialogue");
                }}
              >
                {t("reglages.retourDialogue")}
              </button>
            }
          >
            <div className="panneau-corps">
              <VueAmeliorations
                surChangement={rafraichir}
                surAction={(r) => {
                  suiteAction(r, "Fait.");
                }}
                surOuvrirAtelier={(id) => {
                  setVue("ateliers");
                  setCible({ vue: "ateliers", id });
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
                {t("reglages.retourDialogue")}
              </button>
            }
          >
            <div className="panneau-corps">
              <VueMemoire surChangement={rafraichir} demande={rechercheMemoire} />
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
                {t("reglages.retourDialogue")}
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
                {t("reglages.retourDialogue")}
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
        ) : vue === "reglages" ? (
          <Panneau
            titre={t("vue.reglages")}
            className="panneau-scene"
            ordre={2}
            id="reglages"
            meta={t("reglages.panneauMeta")}
            actions={
              <button
                type="button"
                className="btn btn-mini"
                onClick={() => {
                  setVue("dialogue");
                }}
              >
                {t("reglages.retourDialogue")}
              </button>
            }
          >
            <div className="panneau-corps panneau-corps--reglages">
              <VueReglages
                etat={etat}
                lecteur={lecteur}
                cible={demandeReglages}
                surPosition={(c) => {
                  const a = adresseReglages(c);
                  if (window.location.hash !== a) history.replaceState(null, "", a);
                }}
                surChangement={rafraichir}
                surNotifier={notifier}
                surRejouerMatin={() => {
                  setVue("dialogue");
                  setRejouerMatin((n) => n + 1);
                }}
                surInstallation={() => {
                  setVue("accueil");
                }}
                surAide={() => {
                  setAide(true);
                }}
                surPalette={() => {
                  setPalette({ mode: "tout", requete: "" });
                }}
                surDemandes={montrerDemandes}
                surUrgence={() => {
                  setPalette({ mode: "urgence", requete: "" });
                }}
                surLeverUrgence={demanderLevee}
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
                {t("reglages.retourDialogue")}
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
                {t("reglages.retourDialogue")}
              </button>
            }
          >
            <div className="panneau-corps">
              <VueConnecteurs surChangement={rafraichir} />
            </div>
          </Panneau>
        ) : (
        <Panneau titre={t("dialogue.titre")} className="panneau-scene" ordre={2} id="dialogue" meta={titreActif ?? t("dialogue.nouvelleConversation")} actions={actionsDialogue}>
            {erreurEtat ? (
              <div className="vide">
                <p className="vide-titre">{t("erreur.coreMuet")}</p>
                <p>{erreurEtat}</p>
                <button
                  type="button"
                  className="btn btn-principal"
                  onClick={() => {
                    charger();
                  }}
                >
                  {t("erreur.reessayer")}
                </button>
              </div>
            ) : (
              <>
                {etat && <AccueilMatin lecteur={lecteur} urgence={urgence} rejouer={rejouerMatin} surNotifier={notifier} />}
                {propositionEcran && (
                  <PropositionEcran
                    surFermer={() => {
                      setPropositionEcran(false);
                    }}
                  />
                )}
                {partageRecu && (
                  <CartePartage
                    partage={partageRecu.partage}
                    message={partageRecu.message}
                    surDemander={(m) => {
                      setPartageRecu(null);
                      envoyer(m);
                    }}
                    surFermer={() => {
                      setPartageRecu(null);
                    }}
                  />
                )}
                <WidgetsEpingles className="widgets-mobile" widgets={widgetsEpingles} surRetirer={retirerEpingle} {...rappelsWidgets} />
                <ContexteWidgets.Provider value={actionsWidgets}>
                <Fil
                messages={messages}
                moteurs={moteurs}
                reflexion={enCours && !premierMorceau}
                chargement={chargement || !etat}
                {...(avisEnCours && (avisEnCours.recus > 0 || !attente)
                  ? { etapeReflexion: t("dialogue.conseilEtape", { recus: avisEnCours.recus, attendus: avisEnCours.attendus }) }
                  : attente
                    ? { etapeReflexion: attente }
                    : {})}
                surAction={appliquerAction}
              />
                </ContexteWidgets.Provider>
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
                      sansEcran={etat?.sans_ecran === true}
                      surEnvoyer={envoyer}
                      surArreter={arreter}
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
      <DicteeGlobale />

      <aside className="colonne-droite" data-ouvert={lateralOuvert || undefined}>
        <section className="panneau panneau-lateral" style={{ "--ordre": 3 } as React.CSSProperties} aria-label={t("barre.lateral")}>
          <header className="panneau-tete panneau-tete--onglets">
            <div className="onglets" role="tablist" aria-label={t("onglet.vues")}>
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
              aria-label={t("onglet.fermer")}
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
            {onglet === "demandes" && (
              <>
                <ListeDemandes demandes={etat?.demandes ?? []} nbCles={etat?.cles_acces ?? 0} surChangement={rafraichir} />
                <ActionsAnnulables surChangement={rafraichir} />
              </>
            )}
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
      {accordImages && (
        <FenetreAccordImages
          nom={accordImages.nom}
          nbImages={accordImages.images.length}
          surAccepter={() => {
            const a = accordImages;
            setAccordImages(null);
            accorderImages(a.connecteur, true)
              .then(() => {
                setMessages((ms) => ms.filter((m) => m.cle !== a.cle)); // renvoyé tel quel, la bulle revient avec l'envoi
                envoyer(a.texte, a.images);
              })
              .catch((e: unknown) => {
                notifier(e instanceof Error ? e.message : "Accord non enregistré.");
              });
          }}
          surRefuser={() => {
            const a = accordImages;
            setAccordImages(null);
            setMessages((ms) => [
              ...ms,
              { cle: nouvelleCle(), role: "erreur", texte: `Message non envoyé : l'image n'est pas partie vers « ${a.nom} ». Choisissez une IA locale ou renvoyez sans image.` },
            ]);
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
      {decision && (
        <AppelDecision
          id={decision}
          surFermer={(m) => {
            setDecision(null);
            rafraichir(m);
          }}
        />
      )}
    </div>
  );
}
