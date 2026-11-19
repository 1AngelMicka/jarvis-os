// Mission « projet » : brainstorm → spec → plan à valider → exécution en graphe de dépendances.
// En phase « à valider », la spec et le plan sont modifiables et l'aperçu du graphe est lu côté client pendant la
// saisie (src/missionsGraphe.ts) ; le Core reste la référence et valide avant l'exécution.

import { useMemo, useState } from "react";
import type { CSSProperties } from "react";

import { executerMission, modifierPlanMission } from "../api";
import { grouperParNiveau, lirePlan } from "../missionsGraphe";
import { TexteRiche } from "../texte";
import type { EtapeGraphe, Mission, PhasePlan, PlanMission, StatutEtape } from "../types";

import "../styles/missions.css";

/** Taille maximale de la spec et du plan (contrat du Core). */
const LONGUEUR_MAX = 20000;

export const PHASES: Record<PhasePlan, { texte: string; ton?: string }> = {
  preparation: { texte: "Préparation", ton: "attention" },
  a_valider: { texte: "À valider", ton: "attention" },
  execution: { texte: "Exécution", ton: "attention" },
  terminee: { texte: "Terminée", ton: "ok" },
  echec: { texte: "Échec", ton: "risque" },
};

const STATUTS_ETAPE: Record<StatutEtape, { texte: string; ton?: string }> = {
  a_faire: { texte: "À faire" },
  attente_approbation: { texte: "Attend votre accord", ton: "attention" },
  en_cours: { texte: "En cours", ton: "attention" },
  faite: { texte: "Faite", ton: "ok" },
  refusee: { texte: "Refusée", ton: "risque" },
  echec: { texte: "Échec", ton: "risque" },
  sautee: { texte: "Sautée" },
};

const message = (e: unknown, defaut: string) => (e instanceof Error ? e.message : defaut);

/** Barre d'avancement « N / M cases cochées », annoncée aux lecteurs d'écran. */
function Avancement({ faites, total }: { faites: number; total: number }) {
  const pourcent = total > 0 ? Math.round((faites / total) * 100) : 0;
  return (
    <div className="graphe-avancement">
      <div className="progression" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={faites} aria-label="Cases cochées">
        <span style={{ width: `${String(pourcent)}%` }} />
      </div>
      <p className="graphe-avancement-texte" aria-live="polite">
        {faites} / {total} case{total > 1 ? "s" : ""} cochée{faites > 1 ? "s" : ""}
      </p>
    </div>
  );
}

function CarteEtape({ e, surOuvrirDemandes }: { e: EtapeGraphe; surOuvrirDemandes?: (() => void) | undefined }) {
  const s = STATUTS_ETAPE[e.statut];
  return (
    <li className="etape-graphe" data-statut={e.statut}>
      <div className="etape-graphe-tete">
        <span className="etape-graphe-id">{e.id}</span>
        <h5 className="etape-graphe-titre">{e.titre || "Sans titre"}</h5>
        <span className="badge-co" data-ton={s.ton}>
          {s.texte}
        </span>
      </div>
      {e.apres.length > 0 && <p className="etape-graphe-ligne">après {e.apres.join(", ")}</p>}
      {e.detail && <p className="etape-graphe-detail">{e.detail}</p>}
      {e.moteur && (
        <p className="etape-graphe-ligne">
          Moteur : {e.moteur}
          {e.raison && <span className="etape-graphe-raison"> — {e.raison}</span>}
        </p>
      )}
      {e.statut === "attente_approbation" && (
        <p className="etape-graphe-attente">
          En attente de votre approbation —{" "}
          {surOuvrirDemandes ? (
            <button type="button" className="graphe-lien" onClick={surOuvrirDemandes}>
              file d'approbations
            </button>
          ) : (
            "file d'approbations"
          )}
        </p>
      )}
      {e.resultat && <p className="etape-graphe-extrait">{e.resultat}</p>}
      {e.erreur && <p className="etape-graphe-erreur">{e.erreur}</p>}
    </li>
  );
}

/** Graphe en colonnes : une colonne par niveau (empilées sur un écran étroit). */
function Graphe({ etapes, titre, surOuvrirDemandes }: { etapes: readonly EtapeGraphe[]; titre: string; surOuvrirDemandes?: (() => void) | undefined }) {
  const colonnes = grouperParNiveau(etapes);
  if (colonnes.length === 0) return null;
  return (
    <div className="graphe" role="group" aria-label={titre}>
      <div className="graphe-colonnes" style={{ "--niveaux": colonnes.length } as CSSProperties}>
        {colonnes.map((col, i) => (
          <section key={col[0]?.niveau ?? i} className="graphe-colonne" aria-label={`Niveau ${String(i + 1)}`}>
            <h5 className="graphe-colonne-titre">{i === 0 ? "Niveau 1 · sans dépendance" : `Niveau ${String(i + 1)}`}</h5>
            <ol className="graphe-etapes">
              {col.map((e) => (
                <CarteEtape key={e.id} e={e} surOuvrirDemandes={surOuvrirDemandes} />
              ))}
            </ol>
          </section>
        ))}
      </div>
    </div>
  );
}

function Brainstorm({ texte }: { texte: string }) {
  if (!texte.trim()) return null;
  return (
    <details className="graphe-replie">
      <summary>Brainstorm</summary>
      <div className="rapport md">
        <TexteRiche source={texte} />
      </div>
    </details>
  );
}

/** Phase « à valider » : spec et plan modifiables, aperçu du graphe pendant la saisie. */
function Validation({ mission, plan, surChangement, surRecharger }: { mission: Mission; plan: PlanMission; surChangement: (m?: string) => void; surRecharger: () => void }) {
  // Valeurs du Core : reprises tant que l'utilisateur n'a rien modifié (rafraîchissement, enregistrement)
  const [base, setBase] = useState({ spec: plan.spec, plan: plan.plan, erreurs: plan.erreurs });
  const [spec, setSpec] = useState(plan.spec);
  const [texte, setTexte] = useState(plan.plan);
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  if (base.spec !== plan.spec || base.plan !== plan.plan || base.erreurs !== plan.erreurs) {
    if (spec === base.spec) setSpec(plan.spec);
    if (texte === base.plan) setTexte(plan.plan);
    setBase({ spec: plan.spec, plan: plan.plan, erreurs: plan.erreurs });
  }
  const modifie = spec !== base.spec || texte !== base.plan;
  const lu = useMemo(() => lirePlan(texte), [texte]);
  // Le Core fait foi pour le plan enregistré ; l'aperçu local pour un plan en cours de saisie
  const erreurs = modifie ? lu.erreurs : base.erreurs.length > 0 ? base.erreurs : lu.erreurs;
  const apercu: EtapeGraphe[] = lu.etapes.map((e) => ({
    ...e,
    statut: e.faite ? "faite" : "a_faire",
    moteur: null,
    raison: null,
    demande_id: null,
    resultat: null,
    erreur: null,
    debut: null,
    fin: null,
  }));
  const idSpec = `mission-spec-${mission.id}`;
  const idPlan = `mission-plan-${mission.id}`;
  const idAide = `mission-plan-aide-${mission.id}`;

  const enregistrer = async (): Promise<PlanMission | null> => {
    const m = await modifierPlanMission(mission.id, spec, texte);
    if (m.plan) setBase({ spec: m.plan.spec, plan: m.plan.plan, erreurs: m.plan.erreurs });
    return m.plan;
  };

  return (
    <div className="graphe-validation">
      <p className="sec-texte">Relisez et corrigez la spec et le plan : rien ne s'exécute sans vous. Chaque étape demandera encore votre accord.</p>
      <Brainstorm texte={plan.brainstorm} />
      <div className="graphe-champs">
        <div className="graphe-champ">
          <label className="graphe-etiquette" htmlFor={idSpec}>
            Spec (Markdown)
          </label>
          <textarea
            id={idSpec}
            className="graphe-saisie"
            rows={8}
            maxLength={LONGUEUR_MAX}
            spellCheck
            value={spec}
            onChange={(e) => {
              setSpec(e.target.value);
            }}
          />
        </div>
        <div className="graphe-champ">
          <label className="graphe-etiquette" htmlFor={idPlan}>
            Plan à cases (Markdown)
          </label>
          <textarea
            id={idPlan}
            className="graphe-saisie graphe-saisie--mono"
            rows={8}
            maxLength={LONGUEUR_MAX}
            spellCheck={false}
            aria-describedby={idAide}
            value={texte}
            onChange={(e) => {
              setTexte(e.target.value);
            }}
          />
          <p className="sec-texte" id={idAide}>
            Une étape par ligne : <code>- [ ] E1 : Titre</code>, détail sur les lignes indentées, dépendances en fin de ligne <code>(après E1, E2)</code>.
          </p>
        </div>
      </div>
      {erreurs.length > 0 && (
        <ul className="graphe-erreurs" aria-label="Erreurs du plan">
          {erreurs.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {lu.total === 0 && (
        <p className="graphe-repli" role="note">
          Aucune étape exploitable : l'exécution se repliera sur une simple conversation (un seul appel d'IA sur l'objectif et la spec).
        </p>
      )}
      <h5 className="graphe-sous-titre">Aperçu du graphe{modifie ? " (non enregistré)" : ""}</h5>
      <Graphe etapes={apercu} titre="Aperçu du graphe des étapes" />
      <div className="carte-co-actions">
        <button
          type="button"
          className="btn btn-mini"
          disabled={!modifie || occupe}
          onClick={() => {
            setOccupe(true);
            setErreur(null);
            enregistrer()
              .then(() => {
                surChangement("Spec et plan enregistrés.");
              })
              .catch((e: unknown) => {
                setErreur(message(e, "Enregistrement impossible."));
              })
              .finally(() => {
                setOccupe(false);
              });
          }}
        >
          Enregistrer
        </button>
        <button
          type="button"
          className="btn btn-principal btn-mini"
          disabled={occupe || erreurs.length > 0}
          onClick={() => {
            setOccupe(true);
            setErreur(null);
            // Un plan modifié est d'abord enregistré : le Core exécute ce qui est enregistré
            const pret: Promise<PlanMission | null> = modifie ? enregistrer() : Promise.resolve(plan);
            pret
              .then((p) => {
                if (p && p.erreurs.length > 0) throw new Error("Le plan contient encore des erreurs : corrigez-les avant de lancer.");
                return executerMission(mission.id);
              })
              .then(() => {
                surChangement("Exécution lancée : chaque étape attend votre accord dans la file d'approbations.");
                surRecharger();
              })
              .catch((e: unknown) => {
                setErreur(message(e, "Lancement impossible."));
              })
              .finally(() => {
                setOccupe(false);
              });
          }}
        >
          Lancer l'exécution
        </button>
      </div>
      {erreur && (
        <p className="securite-erreur" role="alert">
          {erreur}
        </p>
      )}
    </div>
  );
}

interface Props {
  mission: Mission;
  plan: PlanMission;
  surChangement: (m?: string) => void;
  surRecharger: () => void;
  /** Ouvre la file d'approbations (étape en attente de votre accord) */
  surOuvrirDemandes?: (() => void) | undefined;
}

/** Corps d'une mission projet, selon sa phase. */
export function MissionGraphe({ mission, plan, surChangement, surRecharger, surOuvrirDemandes }: Props) {
  if (plan.phase === "preparation") {
    return (
      <p className="sec-texte graphe-attente" aria-live="polite">
        Préparation en cours : brainstorm, puis spec, puis plan à cases. Vous pourrez tout relire et corriger avant l'exécution.
      </p>
    );
  }
  if (plan.phase === "a_valider") {
    return <Validation mission={mission} plan={plan} surChangement={surChangement} surRecharger={surRecharger} />;
  }
  return (
    <div className="graphe-execution">
      {plan.repli ? (
        <p className="graphe-repli">Repli sur la conversation simple : le plan n'avait aucune étape exploitable, un seul appel d'IA a porté l'objectif et la spec.</p>
      ) : (
        <>
          <Avancement faites={plan.faites} total={plan.total} />
          <p className="sec-texte">
            Jusqu'à {plan.parallele} étape{plan.parallele > 1 ? "s" : ""} en parallèle ; chacune attend votre accord avant de tourner.
          </p>
          <Graphe etapes={plan.etapes} titre="Graphe des étapes" surOuvrirDemandes={surOuvrirDemandes} />
        </>
      )}
      <Brainstorm texte={plan.brainstorm} />
      {(plan.spec.trim() || plan.plan.trim()) && (
        <details className="graphe-replie">
          <summary>Spec et plan</summary>
          {plan.spec.trim() && (
            <div className="rapport md">
              <TexteRiche source={plan.spec} />
            </div>
          )}
          {plan.plan.trim() && <pre className="graphe-plan-brut">{plan.plan}</pre>}
        </details>
      )}
    </div>
  );
}
