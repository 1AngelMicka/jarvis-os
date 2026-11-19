import { useState } from "react";

import { EMOJI_NIVEAU, libelleBouton } from "../pilotage";
import type { ActionPilotage } from "../types";

interface Props {
  actions: ActionPilotage[];
  ecartees?: string[] | undefined;
  /** Les immédiates déjà appliquées (mode « oui », réponse en direct) : le bouton dit « Rouvrir ». */
  appliquees?: boolean;
  /** Applique l'action ; renvoie un court compte rendu (« Mission lancée »), ou lève une erreur affichable. */
  surAction: (a: ActionPilotage) => Promise<string | undefined>;
}

/** Sous une réponse : ce que JARVIS propose. Rien n'est lancé sans ce clic (protection contre l'injection). */
export function ActionsJarvis({ actions, ecartees, appliquees = false, surAction }: Props) {
  const [etats, setEtats] = useState<Record<number, { occupe?: boolean; fait?: string; erreur?: string }>>({});
  if (!actions.length && !ecartees?.length) return null;

  const agir = (a: ActionPilotage, i: number) => {
    setEtats((e) => ({ ...e, [i]: { occupe: true } }));
    surAction(a)
      .then((compte) => {
        setEtats((e) => ({ ...e, [i]: { fait: compte ?? "Fait" } }));
      })
      .catch((err: unknown) => {
        setEtats((e) => ({ ...e, [i]: { erreur: err instanceof Error ? err.message : "Impossible." } }));
      });
  };

  const propositions = actions.some((a) => a.genre === "proposition");
  return (
    <section className="pilotage" aria-label={propositions ? "Propositions de JARVIS" : "Actions de JARVIS"}>
      {propositions && <p className="pilotage-titre">JARVIS propose — rien n'est lancé sans votre clic</p>}
      <ul className="pilotage-liste">
        {actions.map((a, i) => {
          const etat = etats[i] ?? {};
          const lancement = a.genre === "proposition" && a.type !== "ajouter_regle";
          // Une proposition déjà acceptée ne se relance pas d'un second clic (une mission en double coûte)
          const fige = Boolean(etat.fait) && lancement;
          return (
            <li key={`${a.type}-${String(i)}`} className="pilotage-action" data-genre={a.genre} data-niveau={a.niveau}>
              <span className="pilotage-libelle">
                {a.genre === "proposition" && a.niveau !== "vert" && (
                  <span className="pilotage-niveau" aria-label={a.niveau === "rouge" ? "sensible" : "à valider"}>
                    {EMOJI_NIVEAU[a.niveau]}{" "}
                  </span>
                )}
                {a.libelle}
              </span>
              <span className="pilotage-suite">
                {etat.fait && (
                  <span className="pilotage-fait" role="status">
                    {etat.fait}
                  </span>
                )}
                {etat.erreur && (
                  <span className="pilotage-erreur" role="alert">
                    {etat.erreur}
                  </span>
                )}
                {!fige && (
                  <button
                    type="button"
                    className={a.genre === "proposition" ? (a.niveau === "rouge" ? "btn btn-rouge btn-mini" : "btn btn-mini") : "btn btn-discret btn-mini"}
                    disabled={etat.occupe}
                    onClick={() => {
                      agir(a, i);
                    }}
                  >
                    {libelleBouton(a, appliquees || Boolean(etat.fait))}
                  </button>
                )}
              </span>
            </li>
          );
        })}
      </ul>
      {ecartees && ecartees.length > 0 && (
        <p className="pilotage-ecartees" title={ecartees.join(" · ")}>
          {ecartees.length} action{ecartees.length > 1 ? "s" : ""} écartée{ecartees.length > 1 ? "s" : ""} par le Core
        </p>
      )}
    </section>
  );
}
