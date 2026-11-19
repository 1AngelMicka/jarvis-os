import { useState } from "react";

import { approuver, optionsApprobation, refuser } from "../api";
import type { Demande } from "../types";
import { clesDisponibles, signerDefi } from "../webauthn";

const HEURE = new Intl.DateTimeFormat("fr-FR", {
  hour: "2-digit",
  minute: "2-digit",
});

/** Action relue par le Core (contrôle du PC…) : « vérifiée » ou « non vérifiée », avec la raison. */
function verification(resultat: Record<string, unknown>): string {
  if (resultat.verifiee === true) return " — vérifiée";
  if (resultat.verifiee !== false) return "";
  return typeof resultat.detail === "string"
    ? ` — non vérifiée (${resultat.detail})`
    : " — non vérifiée";
}

interface Props {
  demandes: Demande[];
  nbCles: number;
  surChangement: (message?: string) => void;
}

/** File d'approbations : 🟡 un clic, 🔴 une clé d'accès (empreinte, visage ou code de l'appareil). */
export function ListeDemandes({ demandes, nbCles, surChangement }: Props) {
  const [occupee, setOccupee] = useState<string | null>(null);
  const [erreurs, setErreurs] = useState<Record<string, string>>({});
  // « Toujours autoriser » coché, par demande (🟡 autorisable seulement : jamais 🔴, jamais un clic à l'écran)
  const [toujours, setToujours] = useState<Record<string, boolean>>({});

  const traiter = (d: Demande, accepter: boolean) => {
    setOccupee(d.id);
    setErreurs((e) => ({ ...e, [d.id]: "" }));
    const appel = async () => {
      if (!accepter) return refuser(d.id);
      if (d.niveau === "jaune")
        return approuver(
          d.id,
          undefined,
          Boolean(d.toujours_possible && toujours[d.id]),
        );
      if (nbCles === 0) {
        throw new Error(
          "Aucune clé d'accès enregistrée : ajoutez-en une dans l'onglet Sécurité pour approuver les actions 🔴.",
        );
      }
      if (!clesDisponibles()) {
        throw new Error(
          "Ce navigateur ne gère pas les clés d'accès ici : ouvrez JARVIS par http://localhost.",
        );
      }
      const defi = await optionsApprobation(d.id);
      return approuver(d.id, await signerDefi(defi));
    };
    appel()
      .then((r) => {
        const permanent =
          r.statut === "executee" && d.toujours_possible && toujours[d.id];
        surChangement(
          r.statut === "executee"
            ? `Fait : ${d.resume}${"resultat" in r && typeof r.resultat === "object" && r.resultat !== null ? verification(r.resultat as Record<string, unknown>) : ""}${permanent ? " — désormais toujours autorisé (Réglages › Sécurité pour retirer)" : ""}`
            : r.statut === "refusee"
              ? "Demande refusée."
              : undefined,
        );
      })
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : "Échec.";
        // Demande close entre-temps (refusée, expirée, traitée ailleurs) : la file est rechargée, la carte disparaît
        if (/déjà traitée|introuvable|expirée/i.test(message)) {
          surChangement(message);
          return;
        }
        setErreurs((x) => ({
          ...x,
          [d.id]: message.includes("NotAllowedError")
            ? "Approbation annulée."
            : message,
        }));
      })
      .finally(() => {
        setOccupee(null);
      });
  };

  if (!demandes.length) {
    return (
      <div className="vide vide--calme">
        <p className="vide-titre">Rien à approuver</p>
        <p>
          Les actions 🟡 et 🔴 que JARVIS ou vous lancez attendent ici votre
          accord.
        </p>
      </div>
    );
  }
  return (
    <ul className="demandes" aria-label="Demandes en attente">
      {demandes.map((d) => (
        <li key={d.id} className="demande" data-niveau={d.niveau}>
          <div className="demande-tete">
            <span className="demande-niveau">
              {d.niveau === "rouge" ? "🔴 Sensible" : "🟡 À valider"}
            </span>
            <span className="demande-heure">
              expire à {HEURE.format(new Date(d.expire_le))}
            </span>
          </div>
          <p className="demande-resume">{d.resume}</p>
          <p className="demande-meta">
            {d.action} · demandée par {d.demandeur.replace(/^appareil:/, "")}
          </p>
          {d.niveau === "jaune" && d.toujours_possible && (
            <label className="demande-toujours">
              <input
                type="checkbox"
                checked={Boolean(toujours[d.id])}
                onChange={(e) => {
                  setToujours((t) => ({ ...t, [d.id]: e.target.checked }));
                }}
              />
              Toujours autoriser « {d.action} » (sans redemander)
            </label>
          )}
          {erreurs[d.id] && (
            <p className="demande-erreur" role="alert">
              {erreurs[d.id]}
            </p>
          )}
          <div className="demande-actions">
            <button
              type="button"
              className="btn btn-discret btn-mini"
              disabled={occupee === d.id}
              onClick={() => {
                traiter(d, false);
              }}
            >
              Refuser
            </button>
            <button
              type="button"
              className={
                d.niveau === "rouge"
                  ? "btn btn-rouge btn-mini"
                  : "btn btn-ambre btn-mini"
              }
              disabled={occupee === d.id}
              onClick={() => {
                traiter(d, true);
              }}
            >
              {d.niveau === "rouge" ? "Approuver avec ma clé" : "Approuver"}
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}
