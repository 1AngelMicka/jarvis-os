import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { TexteRiche } from "../texte";
import type { AvisExpert, InfoMoteur, MetaMessage } from "../types";

export interface MessageAffiche {
  cle: string;
  role: "utilisateur" | "jarvis" | "erreur";
  texte: string;
  meta?: MetaMessage;
  enCours?: boolean;
}

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

function Message({ m, moteurs }: { m: MessageAffiche; moteurs: InfoMoteur[] }) {
  const local = moteurs.find((x) => x.id === m.meta?.moteur)?.famille === "local";
  return (
    <article className={`msg msg--${m.role}`} data-interlocuteur={m.role === "jarvis" ? (local ? "local" : "jarvis") : undefined} aria-busy={m.enCours || undefined}>
      <span className="msg-auteur">{m.role === "utilisateur" ? "Vous" : m.role === "erreur" ? "Incident" : "JARVIS"}</span>
      <div className="msg-corps">
        {m.role === "jarvis" ? <TexteRiche source={m.texte} /> : m.texte}
        {m.enCours && <span className="curseur-flux" aria-hidden="true" />}
      </div>
      {m.meta?.conseil && m.meta.conseil.length > 0 && <Avis avis={m.meta.conseil} />}
      {m.role === "jarvis" && !m.enCours && m.meta && (
        <div className="msg-pied">
          <span className="msg-meta">{nomModele(moteurs, m.meta)}</span>
          {m.meta.souvenirs?.length ? (
            <span className="msg-meta">
              {m.meta.souvenirs.length} souvenir{m.meta.souvenirs.length > 1 ? "s" : ""}
            </span>
          ) : null}
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
    </article>
  );
}

interface FilProps {
  messages: MessageAffiche[];
  moteurs: InfoMoteur[];
  reflexion: boolean;
  chargement: boolean;
  etapeReflexion?: string;
}

export function Fil({ messages, moteurs, reflexion, chargement, etapeReflexion }: FilProps) {
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
          <Message key={m.cle} m={m} moteurs={moteurs} />
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
  surEnvoyer: (texte: string) => void;
  surArreter: () => void;
  /** Commandes supplémentaires (voix, vision), à côté du conseil. */
  extras?: React.ReactNode;
}

export function Console(p: ConsoleProps) {
  const [texte, setTexte] = useState("");
  const champ = useRef<HTMLTextAreaElement>(null);
  const auto = p.moteur === "auto";
  const moteurActif = auto ? undefined : p.moteurs.find((m) => m.id === p.moteur);
  const pret = auto ? p.moteurs.some((m) => m.disponible && !m.risque) : Boolean(moteurActif?.disponible);

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

  const envoyer = () => {
    const t = texte.trim();
    if (!t || p.enCours || p.bloquee || !pret) return;
    p.surEnvoyer(t);
    setTexte("");
  };

  return (
    <form
      className="console"
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
      <div className="saisie">
        <label className="visuellement-cache" htmlFor="saisie-message">
          Message à JARVIS
        </label>
        <textarea
          id="saisie-message"
          ref={champ}
          rows={1}
          value={texte}
          placeholder={p.conseil ? "Question pour le conseil…" : "Écrire à JARVIS…"}
          autoComplete="off"
          onChange={(e) => {
            setTexte(e.target.value);
          }}
          onKeyDown={(e) => {
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
          disabled={!p.enCours && (!texte.trim() || !pret || p.bloquee)}
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
    </form>
  );
}
