// Pied dépliable sous chaque réponse : moteur, modèle, durée, jetons, coût (estimation signalée).

import { dollars, duree, nombre, pourcent } from "../couts";
import type { MetaMessage } from "../types";
import "../styles/couts.css";

const SOURCES: Record<string, string> = {
  none: "abonnement (compte)",
  compte: "abonnement (compte)",
  cle_api: "clé d'API",
  local: "sur ce PC",
};

function texteCout(meta: MetaMessage): { valeur: string; note: string } {
  if (meta.source_auth === "none" || meta.source_auth === "compte") {
    return {
      valeur: "0 $",
      note: meta.cout_equivalent_api_usd ? `inclus dans l'abonnement · équivalent API ≈ ${dollars(meta.cout_equivalent_api_usd)}` : "inclus dans l'abonnement",
    };
  }
  if (meta.cout_inconnu) return { valeur: "inconnu", note: "aucun tarif pour ce modèle dans la configuration locale" };
  if (meta.source_auth === "local") return { valeur: "0 $", note: "calcul local" };
  if (meta.cout_estime) return { valeur: `≈ ${dollars(meta.cout_usd)}`, note: "estimation d'après les tarifs configurés" };
  return { valeur: dollars(meta.cout_usd), note: meta.cout_usd ? "coût renvoyé par le fournisseur" : "" };
}

export function PiedReponse({ meta, nomMoteur }: { meta: MetaMessage; nomMoteur: string }) {
  if (!meta.moteur) return null;
  const cout = texteCout(meta);
  const resume = [duree(meta.duree_ms), meta.jetons_sortie ? `${nombre(meta.jetons_sortie)} jetons` : "", cout.valeur].filter(Boolean).join(" · ");
  return (
    <>
    <details className="pied-reponse">
      <summary>
        <span className="pied-reponse-titre">Détails</span>
        <span className="pied-reponse-resume">{resume}</span>
      </summary>
      <dl className="pied-reponse-grille">
        <dt>Moteur</dt>
        <dd>{nomMoteur || meta.moteur}</dd>
        {meta.modele && (
          <>
            <dt>Modèle</dt>
            <dd className="pied-reponse-mono">{meta.modele}</dd>
          </>
        )}
        {meta.source_auth && (
          <>
            <dt>Accès</dt>
            <dd>{SOURCES[meta.source_auth] ?? meta.source_auth}</dd>
          </>
        )}
        {meta.duree_ms != null && (
          <>
            <dt>Durée</dt>
            <dd>{duree(meta.duree_ms)}</dd>
          </>
        )}
        <dt>Jetons</dt>
        <dd>
          {meta.jetons_entree == null && meta.jetons_sortie == null
            ? "non communiqués"
            : `${nombre(meta.jetons_entree)} en entrée · ${nombre(meta.jetons_sortie)} en sortie`}
        </dd>
        <dt>Coût</dt>
        <dd>
          {cout.valeur}
          {cout.note && <span className="pied-reponse-note"> — {cout.note}</span>}
        </dd>
        <dt>Énergie</dt>
        <dd className="pied-reponse-note">non mesurable ici</dd>
      </dl>
    </details>
      {meta.plafond && (
        <p className="pied-reponse-alerte" data-ton={meta.plafond.atteint ? "danger" : "attention"} role="status">
          {meta.plafond.atteint ? "Plafond de dépenses atteint" : `Plafond de dépenses à ${pourcent(meta.plafond.part)}`} : {dollars(meta.plafond.depense_usd)} sur{" "}
          {dollars(meta.plafond.plafond_usd)} ce mois-ci.
        </p>
      )}
    </>
  );
}
