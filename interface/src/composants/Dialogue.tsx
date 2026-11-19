import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";

import { EVENEMENT_PREREMPLIR, prendre } from "../bureau";
import { analyserCommande, type IdCommande, suggererSlash, texteAEnvoyer } from "../commandes";
import { ErreurImage, type ImageJointe, imagesDe, NB_MAX_IMAGES, places, preparerImage, TYPES_ACCEPTES } from "../images";
import { TexteRiche } from "../texte";
import { DomainesEvoques } from "./Connaissances";
import type { ActionPilotage, AffirmationInventee, AvisExpert, InfoMoteur, MetaMessage } from "../types";
import { ActionsJarvis } from "./ActionsJarvis";
import { type ImageAffichee, Vignettes, versAffichees } from "./PiecesJointes";
import { PiedReponse } from "./PiedReponse";

export interface MessageAffiche {
  cle: string;
  role: "utilisateur" | "jarvis" | "erreur";
  texte: string;
  meta?: MetaMessage;
  enCours?: boolean;
  /** Images jointes (gardées dans cette page seulement : le Core ne les conserve pas). */
  images?: ImageAffichee[];
  /** Actions immédiates déjà appliquées seules (mode de pilotage « oui ») : leurs boutons disent « Rouvrir ». */
  actionsAppliquees?: boolean;
  /** Réponse d'une commande rapide (aucune IA) : gardée dans cette page seulement. */
  rapide?: boolean;
}

/** Applique une action proposée par JARVIS ; renvoie un compte rendu court ou lève une erreur affichable. */
export type SurActionPilotage = (a: ActionPilotage) => Promise<string | undefined>;

const NOMS_EFFORT: Record<string, string> = {
  low: "Rapide",
  medium: "Équilibré",
  high: "Élevé",
  xhigh: "Très élevé",
  max: "Maximal",
};

function nomModele(moteurs: InfoMoteur[], meta: MetaMessage | undefined): string {
  if (!meta?.moteur) return "";
  const moteur = moteurs.find((m) => m.id === meta.moteur);
  const modele = moteur?.modeles.find((x) => x.id === meta.modele)?.nom ?? meta.modele ?? "";
  return [moteur?.nom ?? meta.moteur, modele, meta.effort ? NOMS_EFFORT[meta.effort] : ""]
    .filter(Boolean)
    .join(" · ");
}

function nbMasques(meta: MetaMessage): number {
  return Object.values(meta.masques ?? {}).reduce((a, b) => a + b, 0);
}

function Avis({ avis }: { avis: AvisExpert[] }) {
  return (
    <details className="msg-avis">
      <summary>
        Avis des experts ({avis.length}) · {avis.filter((a) => !a.erreur).length} réponse
        {avis.filter((a) => !a.erreur).length > 1 ? "s" : ""}
      </summary>
      <ul>
        {avis.map((a) => (
          <li key={a.connecteur} className="avis" data-erreur={a.erreur ? true : undefined}>
            <span className="avis-nom">
              {a.nom}
              {a.modele ? ` · ${a.modele}` : ""} · {(a.duree_ms / 1000).toFixed(1)} s
            </span>
            {a.erreur ? <p className="avis-erreur">{a.erreur}</p> : <TexteRiche source={a.texte} />}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** Exécution inventée : la réponse affirme avoir agi, mais le journal du tour ne montre aucune action. Discret,
 * jamais une correction de la réponse : le détail (phrases en cause) se déplie. */
export function AvertissementInvente({ affirmations }: { affirmations: AffirmationInventee[] }) {
  const phrases = [...new Set(affirmations.map((a) => a.extrait))]; // une phrase peut affirmer plusieurs actions
  return (
    <details className="msg-invente">
      <summary>
        <span className="msg-invente-titre">JARVIS dit avoir agi, mais aucune action n'a été faite</span>
      </summary>
      <p className="msg-invente-texte">
        Aucun outil ni aucune action n'a été exécuté pendant cette réponse. Phrase{phrases.length > 1 ? "s" : ""} en cause :
      </p>
      <ul className="msg-invente-liste">
        {phrases.map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ul>
    </details>
  );
}

function Message({ m, moteurs, surAction }: { m: MessageAffiche; moteurs: InfoMoteur[]; surAction?: SurActionPilotage | undefined }) {
  const local = moteurs.find((x) => x.id === m.meta?.moteur)?.famille === "local";
  return (
    <article className={`msg msg--${m.role}`} data-interlocuteur={m.role === "jarvis" ? (local ? "local" : "jarvis") : undefined} aria-busy={m.enCours || undefined}>
      <span className="msg-auteur">
        {m.role === "utilisateur" ? "Vous" : m.role === "erreur" ? "Incident" : "JARVIS"}
        {m.rapide && <span className="msg-rapide"> · commande rapide, sans IA</span>}
      </span>
      {m.images && m.images.length > 0 && <Vignettes images={m.images} libelle="Images jointes" className="vignettes--fil" />}
      {(m.texte || m.role !== "utilisateur" || !m.images?.length) && (
        <div className="msg-corps">
          {m.role === "jarvis" ? <TexteRiche source={m.texte} /> : m.texte}
          {m.enCours && <span className="curseur-flux" aria-hidden="true" />}
        </div>
      )}
      {!m.images?.length && m.meta?.images && m.meta.images.length > 0 && (
        <p className="msg-images-absentes">
          {m.meta.images.length} image{m.meta.images.length > 1 ? "s" : ""} jointe{m.meta.images.length > 1 ? "s" : ""} · non conservée{m.meta.images.length > 1 ? "s" : ""}
        </p>
      )}
      {m.role === "jarvis" && !m.enCours && m.meta?.invente && m.meta.invente.length > 0 && <AvertissementInvente affirmations={m.meta.invente} />}
      {m.meta?.conseil && m.meta.conseil.length > 0 && <Avis avis={m.meta.conseil} />}
      {m.role === "jarvis" && !m.enCours && surAction && (m.meta?.actions?.length || m.meta?.actions_ecartees?.length) ? (
        <ActionsJarvis actions={m.meta.actions ?? []} ecartees={m.meta.actions_ecartees} appliquees={m.actionsAppliquees ?? false} surAction={surAction} />
      ) : null}
      {m.role === "jarvis" && !m.enCours && m.meta && (
        <div className="msg-pied">
          <span className="msg-meta">{nomModele(moteurs, m.meta)}</span>
          {m.meta.souvenirs?.length ? (
            <span className="msg-meta">
              {m.meta.souvenirs.length} souvenir{m.meta.souvenirs.length > 1 ? "s" : ""}
            </span>
          ) : null}
          {m.meta.domaines?.length ? <DomainesEvoques domaines={m.meta.domaines} /> : null}
          {m.meta.memoire_consultee === false && <span className="msg-meta msg-meta--ambre">mémoire indisponible</span>}
          {m.meta.jetons_sortie ? <span className="msg-meta">{m.meta.jetons_sortie} jetons</span> : null}
          {nbMasques(m.meta) > 0 && (
            <span className="msg-meta msg-meta--ambre" title={Object.entries(m.meta.masques ?? {}).map(([k, n]) => `${k} : ${String(n)}`).join(" · ")}>
              {nbMasques(m.meta)} élément{nbMasques(m.meta) > 1 ? "s" : ""} masqué{nbMasques(m.meta) > 1 ? "s" : ""} avant envoi
            </span>
          )}
          {(m.meta.source_auth === "none" || m.meta.source_auth === "compte") && <span className="msg-meta msg-meta--ok">compte · 0 $</span>}
          {m.meta.cout_usd ? <span className="msg-meta">{m.meta.cout_usd.toFixed(4)} $</span> : null}
          {m.meta.interrompu && <span className="msg-meta msg-meta--ambre">interrompue</span>}
        </div>
      )}
      {m.role === "jarvis" && !m.enCours && m.meta?.moteur && !m.meta.interrompu && (
        <PiedReponse meta={m.meta} nomMoteur={moteurs.find((x) => x.id === m.meta?.moteur)?.nom ?? ""} />
      )}
    </article>
  );
}

interface FilProps {
  messages: MessageAffiche[];
  moteurs: InfoMoteur[];
  reflexion: boolean;
  chargement: boolean;
  etapeReflexion?: string;
  /** Boutons des actions de JARVIS sous ses réponses (sans : pas de boutons). */
  surAction?: SurActionPilotage;
}

export function Fil({ messages, moteurs, reflexion, chargement, etapeReflexion, surAction }: FilProps) {
  const zone = useRef<HTMLDivElement>(null);
  const collee = useRef(true);

  useLayoutEffect(() => {
    const el = zone.current;
    if (el && collee.current) el.scrollTop = el.scrollHeight;
  });

  if (chargement) {
    return (
      <div className="fil" aria-busy="true">
        <div className="squelette" />
        <div className="squelette squelette--court" />
      </div>
    );
  }
  if (!messages.length) {
    return (
      <div className="fil fil--vide">
        <div className="accueil">
          <p className="accueil-titre">Que voulez-vous faire ?</p>
          <p className="accueil-texte">Posez une question, réfléchissez à voix haute, confiez une idée. Claude répond par votre abonnement, ou un modèle local si vous le choisissez.</p>
          <p className="accueil-astuce">
            <span>
              <kbd>Entrée</kbd> envoyer
            </span>
            <span>
              <kbd>Maj</kbd> + <kbd>Entrée</kbd> nouvelle ligne
            </span>
            <span>
              <kbd>Échap</kbd> arrêter
            </span>
            <span>
              <kbd>Ctrl</kbd> + <kbd>K</kbd> commandes
            </span>
            <span>
              <kbd>/</kbd> dans la saisie
            </span>
          </p>
        </div>
      </div>
    );
  }
  return (
    <div
      className="fil"
      ref={zone}
      onScroll={(e) => {
        const el = e.currentTarget;
        collee.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
      }}
    >
      <div className="fil-colonne">
        {messages.map((m) => (
          <Message key={m.cle} m={m} moteurs={moteurs} surAction={surAction} />
        ))}
        {reflexion && (
          <div className="reflexion" role="status">
            <span className="reflexion-points" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
            {etapeReflexion ?? "JARVIS réfléchit…"}
          </div>
        )}
      </div>
    </div>
  );
}

interface ConsoleProps {
  moteurs: InfoMoteur[];
  moteur: string;
  modele: string;
  effort: string;
  enCours: boolean;
  /** Arrêt d'urgence : rien ne part. */
  bloquee?: boolean;
  conseil: boolean;
  surConseil: (actif: boolean) => void;
  surMoteur: (id: string) => void;
  surModele: (id: string) => void;
  surEffort: (e: string) => void;
  surEnvoyer: (texte: string, images: ImageJointe[]) => void;
  /** Commande « / » validée dans la saisie. */
  surCommande: (id: IdCommande, argument: string) => void;
  surArreter: () => void;
  /** Commandes supplémentaires (voix, vision), à côté du conseil. */
  extras?: React.ReactNode;
}

export function Console(p: ConsoleProps) {
  const [texte, setTexte] = useState("");
  const [images, setImages] = useState<ImageJointe[]>([]);
  const [enPreparation, setEnPreparation] = useState(0);
  const [erreurSaisie, setErreurSaisie] = useState<string | null>(null);
  const [survol, setSurvol] = useState(false);
  const [suggestion, setSuggestion] = useState(0);
  const [suggestionsFermees, setSuggestionsFermees] = useState(false);
  const champ = useRef<HTMLTextAreaElement>(null);
  const fichiers = useRef<HTMLInputElement>(null);
  const profondeurGlisser = useRef(0);
  const idSuggestions = useId();
  const auto = p.moteur === "auto";
  const moteurActif = auto ? undefined : p.moteurs.find((m) => m.id === p.moteur);
  const pret = auto ? p.moteurs.some((m) => m.disponible && !m.risque) : Boolean(moteurActif?.disponible);
  const suggestions = suggestionsFermees ? [] : suggererSlash(texte);
  const choisie = suggestions[Math.min(suggestion, suggestions.length - 1)];
  // Images refusées d'avance : conseil multi-IA, ou connecteur choisi qui ne sait pas les lire
  const refusImages = images.length
    ? p.conseil
      ? "Le conseil multi-IA ne lit pas les images : désactivez-le pour les envoyer."
      : moteurActif && moteurActif.vision === false
        ? `${moteurActif.nom} ne lit pas les images : choisissez Auto, Claude, une API ou Ollama avec un modèle de vision.`
        : null
    : null;
  const peutEnvoyer = (Boolean(texte.trim()) || images.length > 0) && pret && !p.bloquee && !refusImages && !enPreparation;

  useEffect(() => {
    const el = champ.current;
    if (!el) return;
    el.style.height = "auto";
    // box-sizing: border-box : la hauteur comprend les bordures, que scrollHeight ne compte pas
    const bordures = el.offsetHeight - el.clientHeight;
    el.style.height = `${String(Math.min(el.scrollHeight + bordures, 160))}px`;
  }, [texte]);

  useEffect(() => {
    const surTouche = (e: KeyboardEvent) => {
      if (e.key === "Escape" && p.enCours) p.surArreter();
      if (e.key === "/" && document.activeElement === document.body) {
        e.preventDefault();
        champ.current?.focus();
      }
    };
    window.addEventListener("keydown", surTouche);
    return () => {
      window.removeEventListener("keydown", surTouche);
    };
  }, [p]);

  const joindre = (liste: Iterable<File>) => {
    const { images: candidates, ignores } = imagesDe(liste);
    const libres = places(images.length + enPreparation);
    const retenues = candidates.slice(0, libres);
    const messages: string[] = [];
    if (ignores) messages.push(`${String(ignores)} fichier${ignores > 1 ? "s" : ""} ignoré${ignores > 1 ? "s" : ""} (seules les images sont acceptées).`);
    if (candidates.length > retenues.length) messages.push(`${String(NB_MAX_IMAGES)} images au plus par message.`);
    setErreurSaisie(messages.length ? messages.join(" ") : null);
    if (!retenues.length) return;
    setEnPreparation((n) => n + retenues.length);
    for (const f of retenues) {
      preparerImage(f)
        .then((img) => {
          setImages((is) => (is.length < NB_MAX_IMAGES ? [...is, img] : is));
        })
        .catch((e: unknown) => {
          setErreurSaisie(e instanceof ErreurImage ? e.message : `${f.name} : image illisible.`);
        })
        .finally(() => {
          setEnPreparation((n) => n - 1);
        });
    }
  };

  // Glisser-déposer : partout dans la fenêtre tant que le dialogue est affiché
  const joindreRef = useRef(joindre);
  joindreRef.current = joindre;
  useEffect(() => {
    const contientFichiers = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");
    const entree = (e: DragEvent) => {
      if (!contientFichiers(e)) return;
      profondeurGlisser.current++;
      setSurvol(true);
    };
    const dessus = (e: DragEvent) => {
      if (!contientFichiers(e)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    };
    const sortie = (e: DragEvent) => {
      if (!contientFichiers(e)) return;
      profondeurGlisser.current = Math.max(0, profondeurGlisser.current - 1);
      if (!profondeurGlisser.current) setSurvol(false);
    };
    const depot = (e: DragEvent) => {
      if (!contientFichiers(e)) return;
      e.preventDefault();
      profondeurGlisser.current = 0;
      setSurvol(false);
      if (e.dataTransfer?.files.length) joindreRef.current(e.dataTransfer.files);
      champ.current?.focus();
    };
    window.addEventListener("dragenter", entree);
    window.addEventListener("dragover", dessus);
    window.addEventListener("dragleave", sortie);
    window.addEventListener("drop", depot);
    return () => {
      window.removeEventListener("dragenter", entree);
      window.removeEventListener("dragover", dessus);
      window.removeEventListener("dragleave", sortie);
      window.removeEventListener("drop", depot);
    };
  }, []);

  // Lien jarvis://dire (lot M) : préremplit la saisie ; le texte vient de l'extérieur, l'utilisateur le relit et l'envoie
  useEffect(() => {
    const preremplir = () => {
      const texte = prendre(EVENEMENT_PREREMPLIR);
      if (!texte) return;
      setTexte(texte);
      window.setTimeout(() => champ.current?.focus(), 0);
    };
    preremplir(); // lien arrivé avant que la saisie soit montée
    window.addEventListener(EVENEMENT_PREREMPLIR, preremplir);
    return () => {
      window.removeEventListener(EVENEMENT_PREREMPLIR, preremplir);
    };
  }, []);

  // « /image » ou la palette : ouvrir le sélecteur de fichiers (photothèque sur iPhone)
  useEffect(() => {
    const ouvrir = () => {
      fichiers.current?.click();
    };
    window.addEventListener(EVENEMENT_JOINDRE, ouvrir);
    return () => {
      window.removeEventListener(EVENEMENT_JOINDRE, ouvrir);
    };
  }, []);

  const lancerCommande = (id: IdCommande, argument: string) => {
    setTexte("");
    setSuggestion(0);
    setErreurSaisie(null);
    p.surCommande(id, argument);
  };

  const envoyer = () => {
    if (p.enCours || p.bloquee) return;
    const analyse = analyserCommande(texte);
    if (analyse.type === "commande") {
      lancerCommande(analyse.commande.id, analyse.argument);
      return;
    }
    if (analyse.type === "inconnue") {
      setErreurSaisie(`Commande inconnue : « /${analyse.nom} ». Tapez /aide pour la liste, ou // pour envoyer un message qui commence par « / ».`);
      return;
    }
    if (!peutEnvoyer) return;
    p.surEnvoyer(texteAEnvoyer(texte), images);
    setTexte("");
    setImages([]);
    setErreurSaisie(null);
  };

  return (
    <form
      className="console"
      data-survol={survol || undefined}
      onSubmit={(e) => {
        e.preventDefault();
        if (p.enCours) p.surArreter();
        else envoyer();
      }}
    >
      <div className="console-reglages">
        <label className="reglage-compact reglage-cerveau">
          <span className="reglage-libelle">Cerveau</span>
          <select
            className="select select--compact"
            value={p.moteur}
            onChange={(e) => {
              p.surMoteur(e.target.value);
            }}
          >
            <option value="auto">Auto (routeur)</option>
            {p.moteurs.map((m) => (
              <option key={m.id} value={m.id} disabled={!m.disponible}>
                {m.nom}
                {m.risque ? " ⚠ risque" : ""}
                {m.disponible ? "" : " — indisponible"}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="segment-btn bouton-conseil"
          aria-pressed={p.conseil}
          title="Conseil multi-IA : plusieurs connecteurs donnent leur avis, puis une synthèse"
          onClick={() => {
            p.surConseil(!p.conseil);
          }}
        >
          Conseil
        </button>
        {p.extras}
        {moteurActif && moteurActif.modeles.length > 0 && (
          <label className="reglage-compact">
            <span className="visuellement-cache">Modèle</span>
            <select
              className="select select--compact"
              value={p.modele}
              onChange={(e) => {
                p.surModele(e.target.value);
              }}
            >
              {moteurActif.modeles.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.nom}
                </option>
              ))}
            </select>
          </label>
        )}
        {moteurActif && moteurActif.efforts.length > 0 && (
          <label className="reglage-compact">
            <span className="visuellement-cache">Effort</span>
            <select
              className="select select--compact"
              value={p.effort}
              onChange={(e) => {
                p.surEffort(e.target.value);
              }}
            >
              {moteurActif.efforts.map((e) => (
                <option key={e} value={e}>
                  {NOMS_EFFORT[e] ?? e}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {p.bloquee && (
        <p className="console-alerte" role="status">
          Arrêt d'urgence actif : JARVIS n'envoie plus rien tant qu'il n'est pas levé.
        </p>
      )}
      {moteurActif?.risque && (
        <p className="console-alerte" role="status">
          Connecteur à risque choisi : vos conditions d'utilisation chez ce fournisseur l'interdisent peut-être.
        </p>
      )}
      {moteurActif && !moteurActif.disponible && (
        <p className="console-alerte" role="status">
          {moteurActif.nom} indisponible : {moteurActif.detail}.
        </p>
      )}
      {erreurSaisie && (
        <p className="console-alerte" role="alert">
          {erreurSaisie}
        </p>
      )}
      {refusImages && (
        <p className="console-alerte" role="alert">
          {refusImages}
        </p>
      )}
      <Vignettes
        images={versAffichees(images)}
        enPreparation={enPreparation}
        libelle={`Images jointes au message (${String(images.length)} sur ${String(NB_MAX_IMAGES)})`}
        className="vignettes--saisie"
        surRetirer={(id) => {
          setImages((is) => is.filter((i) => i.id !== id));
          setErreurSaisie(null);
          champ.current?.focus();
        }}
      />
      {suggestions.length > 0 && (
        <ul className="suggestions" id={idSuggestions} role="listbox" aria-label="Commandes">
          {suggestions.map((c) => (
            <li
              key={c.id}
              id={`${idSuggestions}-${c.id}`}
              role="option"
              aria-selected={c === choisie}
              className="suggestion"
              onMouseDown={(e) => {
                e.preventDefault(); // le focus reste dans la saisie
                lancerCommande(c.id, "");
              }}
            >
              <code className="suggestion-nom">/{c.slash}</code>
              {c.argument && <span className="suggestion-argument">[{c.argument}]</span>}
              <span className="suggestion-detail">{c.nom}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="saisie">
        <input
          ref={fichiers}
          id="joindre-image"
          type="file"
          accept={TYPES_ACCEPTES.join(",")}
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files?.length) joindre(e.target.files);
            e.target.value = ""; // la même image peut être choisie de nouveau
          }}
        />
        <button
          type="button"
          className="joindre-btn"
          aria-label={`Joindre des images (${String(images.length)} sur ${String(NB_MAX_IMAGES)})`}
          title="Joindre des images (ou collez-les, ou glissez-les)"
          disabled={p.bloquee || places(images.length + enPreparation) === 0}
          onClick={() => {
            fichiers.current?.click();
          }}
        >
          <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M20 11.5l-7.8 7.8a5 5 0 0 1-7.1-7.1l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4L15 6.9" />
          </svg>
        </button>
        <label className="visuellement-cache" htmlFor="saisie-message">
          Message à JARVIS
        </label>
        <textarea
          id="saisie-message"
          ref={champ}
          rows={1}
          value={texte}
          placeholder={p.conseil ? "Question pour le conseil…" : images.length ? "Une question sur ces images ? (facultatif)" : "Écrire à JARVIS… (/ pour les commandes)"}
          autoComplete="off"
          role={suggestions.length ? "combobox" : undefined}
          aria-expanded={suggestions.length ? true : undefined}
          aria-controls={suggestions.length ? idSuggestions : undefined}
          aria-autocomplete={suggestions.length ? "list" : undefined}
          aria-activedescendant={choisie ? `${idSuggestions}-${choisie.id}` : undefined}
          onChange={(e) => {
            setTexte(e.target.value);
            setSuggestion(0);
            setSuggestionsFermees(false);
            if (erreurSaisie?.startsWith("Commande inconnue")) setErreurSaisie(null);
          }}
          onPaste={(e) => {
            const colles = Array.from(e.clipboardData.files);
            if (!colles.some((f) => f.type.startsWith("image/"))) return;
            if (!e.clipboardData.getData("text/plain")) e.preventDefault();
            joindre(colles);
          }}
          onKeyDown={(e) => {
            if (suggestions.length) {
              if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                e.preventDefault();
                const pas = e.key === "ArrowDown" ? 1 : -1;
                setSuggestion((i) => (Math.min(i, suggestions.length - 1) + pas + suggestions.length) % suggestions.length);
                return;
              }
              if (e.key === "Tab" && choisie?.slash) {
                e.preventDefault();
                setTexte(`/${choisie.slash}${choisie.argument ? " " : ""}`);
                return;
              }
              if (e.key === "Escape") {
                e.preventDefault();
                e.stopPropagation(); // ferme les suggestions sans arrêter la réponse
                setSuggestionsFermees(true);
                return;
              }
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && choisie) {
                e.preventDefault();
                // « /th » + Entrée : la commande choisie ; une commande qui attend un argument le laisse taper
                if (choisie.argument && analyserCommande(texte).type !== "commande") setTexte(`/${choisie.slash ?? ""} `);
                else lancerCommande(choisie.id, "");
                return;
              }
            }
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              envoyer();
            }
          }}
        />
        <button
          type="submit"
          className="envoyer-btn"
          data-arreter={p.enCours || undefined}
          disabled={!p.enCours && !peutEnvoyer && !texte.trim().startsWith("/")}
          aria-label={p.enCours ? "Arrêter la réponse" : "Envoyer"}
          title={p.enCours ? "Arrêter (Échap)" : "Envoyer (Entrée)"}
        >
          {p.enCours ? (
            <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
              <rect x="7" y="7" width="10" height="10" rx="1.5" />
            </svg>
          ) : (
            <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M5 12h13M13 6l6 6-6 6" />
            </svg>
          )}
        </button>
      </div>
      {survol && (
        <div className="depot-images" aria-hidden="true">
          Déposez vos images ({String(places(images.length + enPreparation))} place{places(images.length + enPreparation) > 1 ? "s" : ""})
        </div>
      )}
    </form>
  );
}

/** Événement de fenêtre : ouvrir le sélecteur d'images de la console (commande « /image », palette). */
export const EVENEMENT_JOINDRE = "jarvis2:joindre-image";
