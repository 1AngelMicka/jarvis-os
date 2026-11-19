// Widgets générés à la demande (phase 14, D 16) : rendu React d'un fragment filtré (widgets.ts), sous une réponse
// ou épinglé dans le HUD. Le DOM n'est jamais construit par innerHTML : l'arbre filtré par DOMPurify est relu nœud
// par nœud, chaque balise et chaque attribut revérifiés, puis recréés par React.

import { createContext, createElement, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { attributPermis, BALISES, filtrer, formaterDuree, type Widget } from "../widgets";
import "../styles/widgets.css";

interface Rappels {
  /** Lien interne `#vue` d'un widget : l'application ouvre la vue (jamais d'adresse externe). */
  surNaviguer?: (vue: string) => void;
  /** Un minuteur arrive à zéro. */
  surFinMinuteur?: (titre: string) => void;
}

// Balises où React refuse les nœuds de texte (espaces entre les lignes d'un tableau)
const SANS_TEXTE = new Set(["table", "thead", "tbody", "tr", "ul", "ol"]);
const NUMERIQUES = new Set(["value", "min", "max", "low", "high"]);

function Minuteur({ secondes, titre, classe, surFin }: { secondes: number; titre: string; classe: string; surFin?: (titre: string) => void }) {
  const [restant, setRestant] = useState(secondes);
  const [enMarche, setEnMarche] = useState(false);

  useEffect(() => {
    if (!enMarche) return;
    const debut = Date.now();
    const depart = restant;
    const id = window.setInterval(() => {
      const r = Math.max(0, depart - Math.floor((Date.now() - debut) / 1000));
      setRestant(r);
      if (r === 0) {
        setEnMarche(false);
        surFin?.(titre);
      }
    }, 250);
    return () => {
      window.clearInterval(id);
    };
    // `restant` n'est lu qu'au départ : le relancer à chaque seconde fausserait le compte
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enMarche]);

  const fini = restant === 0;
  return (
    <span className="w-minuteur-bloc">
      <time className={`${classe} ${fini ? "w-succes" : ""}`} dateTime={`PT${String(restant)}S`} aria-live="polite">
        {fini ? "Terminé" : formaterDuree(restant)}
      </time>
      <span className="w-minuteur-boutons">
        <button
          type="button"
          className="btn btn-mini"
          disabled={fini}
          onClick={() => {
            setEnMarche((m) => !m);
          }}
        >
          {enMarche ? "Pause" : restant === secondes ? "Démarrer" : "Reprendre"}
        </button>
        <button
          type="button"
          className="btn btn-mini"
          disabled={restant === secondes && !enMarche}
          onClick={() => {
            setEnMarche(false);
            setRestant(secondes);
          }}
        >
          Remettre
        </button>
      </span>
    </span>
  );
}

function versReact(noeud: Node, cle: string, parent: string, titre: string, rappels: Rappels): ReactNode {
  if (noeud.nodeType === Node.TEXT_NODE) {
    const texte = noeud.textContent ?? "";
    return SANS_TEXTE.has(parent) && !texte.trim() ? null : texte;
  }
  if (noeud.nodeType !== Node.ELEMENT_NODE) return null;
  const el = noeud as Element;
  const balise = el.tagName.toLowerCase();
  if (!BALISES.includes(balise)) return null; // revérifié : le filtre l'a déjà refusé
  const props: Record<string, unknown> = { key: cle };
  let minuteur: number | null = null;
  for (const a of Array.from(el.attributes)) {
    if (!attributPermis(balise, a.name, a.value)) return null;
    const v = a.value.trim();
    if (a.name === "class") props.className = v;
    else if (a.name === "colspan") props.colSpan = Number(v);
    else if (a.name === "datetime") props.dateTime = v;
    else if (a.name === "data-minuteur") minuteur = Number(v);
    else if (NUMERIQUES.has(a.name)) props[a.name] = Number(v);
    else if (a.name === "href") {
      props.href = v;
      const vue = v.slice(1).split("/")[0] ?? "";
      props.onClick = (e: React.MouseEvent) => {
        e.preventDefault();
        rappels.surNaviguer?.(vue);
      };
    } else props[a.name] = v; // title, aria-label
  }
  if (balise === "time" && minuteur !== null) {
    return <Minuteur key={cle} secondes={minuteur} titre={titre} classe={typeof props.className === "string" ? props.className : ""} {...(rappels.surFinMinuteur ? { surFin: rappels.surFinMinuteur } : {})} />;
  }
  if (balise === "br") return createElement("br", props);
  const enfants = Array.from(el.childNodes).map((n, i) => versReact(n, `${cle}.${String(i)}`, balise, titre, rappels));
  return createElement(balise, props, ...enfants);
}

/** Contenu d'un widget, ou un refus clair si le fragment ne passe pas le filtre. */
export function ContenuWidget({ widget, ...rappels }: { widget: Pick<Widget, "titre" | "html"> } & Rappels) {
  const filtre = useMemo(() => filtrer(widget.html), [widget.html]);
  if (!filtre.ok) {
    return <p className="widget-refus">Widget refusé par le filtre de l'interface ({filtre.raison}).</p>;
  }
  const enfants = Array.from(filtre.fragment.childNodes).map((n, i) => versReact(n, String(i), "div", widget.titre, rappels));
  return <div className="widget-contenu">{enfants}</div>;
}

interface PropsReponse extends Rappels {
  widgets: readonly Widget[];
  ecartes?: readonly string[] | undefined;
  /** Empreintes déjà épinglées. */
  epingles: ReadonlySet<string>;
  surEpingler: (w: Widget) => void;
}

/** Widgets d'une réponse de JARVIS, épinglables dans le HUD. */
export function WidgetsReponse({ widgets, ecartes, epingles, surEpingler, ...rappels }: PropsReponse) {
  return (
    <div className="widgets-reponse">
      {widgets.map((w) => {
        const deja = epingles.has(w.id);
        return (
          <article className="widget" key={w.id} aria-label={`Widget : ${w.titre}`}>
            <header className="widget-tete">
              <h3 className="widget-titre">{w.titre}</h3>
              <button
                type="button"
                className="btn btn-mini"
                disabled={deja}
                onClick={() => {
                  surEpingler(w);
                }}
              >
                {deja ? "Épinglé" : "Épingler"}
              </button>
            </header>
            <ContenuWidget widget={w} {...rappels} />
          </article>
        );
      })}
      {ecartes?.length ? (
        <p className="widget-refus">
          {ecartes.length === 1 ? "Un widget a été écarté" : `${String(ecartes.length)} widgets ont été écartés`} par le Core : {ecartes.join(" ; ")}.
        </p>
      ) : null}
    </div>
  );
}

interface PropsEpingles extends Rappels {
  widgets: readonly { id: string; titre: string; html: string }[];
  surRetirer: (id: string) => void;
  className?: string;
}

/** Widgets épinglés dans le HUD : chacun se retire d'un clic. */
export function WidgetsEpingles({ widgets, surRetirer, className, ...rappels }: PropsEpingles) {
  if (!widgets.length) return null;
  return (
    <div className={`widgets-epingles ${className ?? ""}`}>
      {widgets.map((w) => (
        <article className="widget" key={w.id} aria-label={`Widget épinglé : ${w.titre}`}>
          <header className="widget-tete">
            <h3 className="widget-titre">{w.titre}</h3>
            <button
              type="button"
              className="btn btn-mini"
              aria-label={`Retirer le widget ${w.titre}`}
              onClick={() => {
                surRetirer(w.id);
              }}
            >
              Retirer
            </button>
          </header>
          <ContenuWidget widget={w} {...rappels} />
        </article>
      ))}
    </div>
  );
}

/** Ce que l'application fournit aux widgets du fil (épinglage, navigation, fin d'un minuteur). */
export interface ActionsWidgets extends Rappels {
  epingles: ReadonlySet<string>;
  surEpingler: (w: Widget) => void;
}

export const ContexteWidgets = createContext<ActionsWidgets | null>(null);

/** Widgets d'un message du fil (rien sans contexte : relecture hors du HUD). */
export function WidgetsDuMessage({ widgets, ecartes }: { widgets?: readonly Widget[] | undefined; ecartes?: readonly string[] | undefined }) {
  const actions = useContext(ContexteWidgets);
  if (!actions || (!widgets?.length && !ecartes?.length)) return null;
  return <WidgetsReponse widgets={widgets ?? []} ecartes={ecartes} {...actions} />;
}
