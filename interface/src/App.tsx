import { useCallback, useEffect, useRef, useState } from "react";

import { dialoguer, ErreurApi, lireConversation, lireEtat } from "./api";
import { Console, Fil, type MessageAffiche } from "./composants/Dialogue";
import { ListeConversations } from "./composants/Historique";
import { Panneau } from "./composants/Panneau";
import { type EtatNoyau, Reacteur } from "./composants/Reacteur";
import { ecrirePreferences, lirePreferences } from "./preferences";
import type { Etat, EvenementDialogue, InfoMoteur, MessageStocke, ResumeConversation } from "./types";

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

export function App() {
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
  const [historiqueOuvert, setHistoriqueOuvert] = useState(false);
  const [annonce, setAnnonce] = useState("");
  const controleur = useRef<AbortController | null>(null);

  const charger = useCallback(() => {
    setErreurEtat(null);
    lireEtat()
      .then((e) => {
        setEtat(e);
        setConversations(e.conversations);
        const prefs = lirePreferences();
        const choisi = e.moteurs.find((m) => m.id === prefs.moteur) ?? e.moteurs.find((m) => m.id === e.moteur_defaut);
        setMoteur(choisi?.id ?? e.moteurs[0]?.id ?? "");
        setModeles(Object.fromEntries(e.moteurs.map((m) => [m.id, modeleParDefaut(m, prefs.modeles?.[m.id])])));
        const claude = e.moteurs.find((m) => m.efforts.length);
        setEffort(prefs.effort && claude?.efforts.includes(prefs.effort) ? prefs.effort : (claude?.effort_defaut ?? ""));
      })
      .catch((err: unknown) => {
        setErreurEtat(err instanceof Error ? err.message : "Core injoignable.");
      });
  }, []);

  useEffect(charger, [charger]);

  useEffect(() => {
    if (moteur) ecrirePreferences({ moteur, modeles, effort });
  }, [moteur, modeles, effort]);

  useEffect(() => {
    if (!historiqueOuvert) return;
    document.querySelector<HTMLElement>(".colonne-droite .hist-item, .colonne-droite .btn-fermer-historique")?.focus();
    const surTouche = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setHistoriqueOuvert(false);
        document.querySelector<HTMLElement>(".btn-historique")?.focus();
      }
    };
    window.addEventListener("keydown", surTouche);
    return () => {
      window.removeEventListener("keydown", surTouche);
    };
  }, [historiqueOuvert]);

  const ouvrir = useCallback((id: string) => {
    controleur.current?.abort();
    setActive(id);
    setHistoriqueOuvert(false);
    setChargement(true);
    lireConversation(id)
      .then((d) => {
        setMessages(d.messages.map(depuisStocke));
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
    setHistoriqueOuvert(false);
    document.getElementById("saisie-message")?.focus();
  };

  const signalerAlerte = () => {
    setAlerte(true);
    window.setTimeout(() => {
      setAlerte(false);
    }, 2400);
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

    const surEvenement = (ev: EvenementDialogue) => {
      switch (ev.type) {
        case "debut": {
          const d = ev.donnees;
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
            return [...ms, { cle: cleJarvis, role: "jarvis", texte: ev.donnees.texte, enCours: true }];
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
      ...(modeles[moteur] ? { modele: modeles[moteur] } : {}),
      ...(moteurInfo?.efforts.length && effort ? { effort } : {}),
    };
    dialoguer(demande, surEvenement, ctrl.signal)
      .catch((err: unknown) => {
        const message = err instanceof ErreurApi || err instanceof Error ? err.message : "Réponse impossible.";
        setMessages((ms) => [...ms, { cle: nouvelleCle(), role: "erreur", texte: message }]);
        signalerAlerte();
      })
      .finally(() => {
        if (ctrl.signal.aborted) {
          setMessages((ms) => ms.map((m) => (m.cle === cleJarvis && m.enCours ? { ...m, enCours: false, meta: { ...m.meta, interrompu: true } } : m)));
        }
        setEnCours(false);
        if (controleur.current === ctrl) controleur.current = null;
      });
  };

  const arreter = () => {
    controleur.current?.abort();
  };

  const etatNoyau: EtatNoyau = alerte ? "alerte" : enCours ? (premierMorceau ? "parole" : "reflexion") : "repos";
  const moteurs = etat?.moteurs ?? [];
  const titreActif = conversations.find((c) => c.id === active)?.titre;

  const historique = <ListeConversations conversations={conversations} active={active} surChoisir={ouvrir} />;
  const boutonNouvelle = (
    <button type="button" className="btn btn-mini" onClick={nouvelle}>
      <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 5v14M5 12h14" />
      </svg>
      Nouvelle
    </button>
  );

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
          <span className="point-etat" data-ok={erreurEtat ? false : etat ? true : undefined} aria-hidden="true" />
          <span className="barre-etat-texte">{erreurEtat ? "Core hors ligne" : etat ? "Core en ligne" : "Connexion…"}</span>
        </div>
        <button
          type="button"
          className="icone-btn btn-historique"
          aria-label="Conversations"
          aria-expanded={historiqueOuvert}
          onClick={() => {
            setHistoriqueOuvert((o) => !o);
          }}
        >
          <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 6h16M4 12h16M4 18h10" />
          </svg>
        </button>
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
              <span className="point-etat" data-ok={erreurEtat ? false : etat ? true : undefined} aria-hidden="true" />
              <span className="etat-nom">JARVIS-Core</span>
              <span className="etat-valeur">{erreurEtat ? "hors ligne" : etat ? "en ligne" : "…"}</span>
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
          </ul>
        </Panneau>
      </aside>

      <main className="scene">
        <Panneau
          titre="Dialogue"
          className="panneau-scene"
          ordre={2}
          id="dialogue"
          meta={titreActif ?? "Nouvelle conversation"}
          actions={boutonNouvelle}
        >
          {erreurEtat ? (
            <div className="vide">
              <p className="vide-titre">Le Core ne répond pas</p>
              <p>{erreurEtat}</p>
              <button type="button" className="btn btn-principal" onClick={charger}>
                Réessayer
              </button>
            </div>
          ) : (
            <>
              <Fil messages={messages} moteurs={moteurs} reflexion={enCours && !premierMorceau} chargement={chargement || !etat} />
              <Console
                moteurs={moteurs}
                moteur={moteur}
                modele={modeles[moteur] ?? ""}
                effort={effort}
                enCours={enCours}
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
      </main>

      <aside className="colonne-droite" data-ouvert={historiqueOuvert || undefined}>
        <Panneau
          titre="Conversations"
          className="panneau-historique"
          ordre={3}
          meta={conversations.length ? String(conversations.length) : undefined}
          actions={
            <button
              type="button"
              className="icone-btn petit btn-fermer-historique"
              aria-label="Fermer"
              onClick={() => {
                setHistoriqueOuvert(false);
              }}
            >
              <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          }
        >
          <div className="panneau-corps">{historique}</div>
        </Panneau>
      </aside>
      {historiqueOuvert && (
        <div
          className="voile-historique"
          aria-hidden="true"
          onClick={() => {
            setHistoriqueOuvert(false);
          }}
        />
      )}
      <p className="visuellement-cache" aria-live="polite">
        {annonce}
      </p>
    </div>
  );
}
