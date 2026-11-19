// Vue « Coûts » : dépenses du jour et du mois, jauges d'abonnement Claude Code, 30 derniers jours, plafonds.

import { type CSSProperties, useCallback, useEffect, useState } from "react";

import { definirPlafond, lireCouts } from "../api";
import {
  dollars,
  ilYa,
  nombre,
  pourcent,
  reinitialisation,
  texteJauge,
  tonPlafond,
  type CoutConnecteur,
  type JaugeAbonnement,
  type ResumeCouts,
} from "../couts";
import "../styles/couts.css";

const FAMILLES: Record<CoutConnecteur["famille"], string> = { cli: "compte", api: "clé d'API", local: "local" };

function Jauge({ j }: { j: JaugeAbonnement }) {
  const mesuree = j.etat !== "inconnu" && j.utilisation != null;
  const ton = j.statut === "rejected" ? "danger" : (j.utilisation ?? 0) >= 0.8 ? "attention" : "ok";
  return (
    <li className="jauge" data-etat={j.etat} data-ton={mesuree ? ton : undefined}>
      <div className="jauge-tete">
        <span className="jauge-nom">{j.nom}</span>
        <span className="jauge-valeur">{texteJauge(j)}</span>
      </div>
      <div
        className="jauge-barre"
        role="meter"
        aria-label={`Abonnement Claude, fenêtre de ${j.nom}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={mesuree ? Math.round((j.utilisation ?? 0) * 100) : undefined}
        aria-valuetext={texteJauge(j)}
      >
        {mesuree && <span className="jauge-remplie" style={{ "--part": String(j.utilisation) } as CSSProperties} />}
      </div>
      <p className="jauge-detail">
        {j.etat === "inconnu"
          ? "Rien de mesuré : la jauge se remplit à votre prochain échange avec Claude."
          : [
              j.age_s != null ? `mesuré ${ilYa(j.age_s)}` : "",
              j.reinitialisation ? `remise à zéro ${reinitialisation(j.reinitialisation)}` : "",
              j.etat === "perime" ? "plus de 30 min : valeur à confirmer" : "",
            ]
              .filter(Boolean)
              .join(" · ")}
      </p>
    </li>
  );
}

function Histogramme({ jours }: { jours: ResumeCouts["jours"] }) {
  const max = Math.max(...jours.map((j) => j.cout_usd), 0);
  const total = jours.reduce((a, j) => a + j.cout_usd, 0);
  if (max === 0) {
    return <p className="couts-vide">Aucune dépense ces 30 derniers jours.</p>;
  }
  return (
    <figure className="histo">
      <ol className="histo-barres" aria-label={`Dépenses par jour sur 30 jours, total ${dollars(total)}`}>
        {jours.map((j) => {
          const date = new Date(`${j.jour}T12:00:00`);
          const libelle = date.toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" });
          return (
            <li key={j.jour} className="histo-jour" title={`${libelle} : ${dollars(j.cout_usd)}`}>
              <span className="histo-barre" style={{ "--part": String(j.cout_usd / max) } as CSSProperties} />
              <span className="visuellement-cache">
                {libelle} : {dollars(j.cout_usd)}
              </span>
            </li>
          );
        })}
      </ol>
      <figcaption className="histo-legende">
        <span>{new Date(`${jours[0]?.jour ?? ""}T12:00:00`).toLocaleDateString("fr-FR", { day: "numeric", month: "short" })}</span>
        <span>max {dollars(max)} / jour</span>
        <span>aujourd'hui</span>
      </figcaption>
    </figure>
  );
}

function Plafond({ c, surChangement }: { c: CoutConnecteur; surChangement: () => void }) {
  const [valeur, setValeur] = useState(c.plafond ? String(c.plafond.plafond_usd) : "");
  const [message, setMessage] = useState<string | null>(null);
  const [occupe, setOccupe] = useState(false);
  const p = c.plafond;

  const enregistrer = (plafond: number | null) => {
    setOccupe(true);
    setMessage(null);
    definirPlafond(c.id, plafond)
      .then(() => {
        surChangement();
      })
      .catch((e: unknown) => {
        setMessage(e instanceof Error ? e.message : "Échec.");
      })
      .finally(() => {
        setOccupe(false);
      });
  };

  return (
    <div className="plafond" data-ton={tonPlafond(p)}>
      {p ? (
        <>
          <div className="jauge-tete">
            <span className="jauge-nom">Plafond mensuel</span>
            <span className="jauge-valeur">
              {dollars(p.depense_usd)} / {dollars(p.plafond_usd)} · {pourcent(p.part)}
            </span>
          </div>
          <div
            className="jauge-barre"
            role="meter"
            aria-label={`Plafond de ${c.nom}`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.min(100, Math.round(p.part * 100))}
          >
            <span className="jauge-remplie" style={{ "--part": String(Math.min(1, p.part)) } as CSSProperties} />
          </div>
          {p.atteint ? (
            <p className="plafond-message" role="status">
              Plafond atteint : ce connecteur refuse de répondre et le routeur passe à une autre IA.
            </p>
          ) : p.alerte ? (
            <p className="plafond-message" role="status">
              Plus de 80 % du plafond dépensés ce mois-ci.
            </p>
          ) : null}
        </>
      ) : (
        <p className="plafond-message plafond-message--neutre">Aucun plafond : les dépenses ne sont pas limitées.</p>
      )}
      <form
        className="plafond-saisie"
        onSubmit={(e) => {
          e.preventDefault();
          const nb = Number(valeur.replace(",", "."));
          if (!valeur.trim() || !Number.isFinite(nb) || nb < 0) {
            setMessage("Indiquez un montant en dollars (0 bloque toute dépense).");
            return;
          }
          enregistrer(nb);
        }}
      >
        <label className="plafond-champ">
          <span>Plafond par mois ($)</span>
          <input
            type="text"
            inputMode="decimal"
            value={valeur}
            placeholder="ex. 20"
            onChange={(e) => {
              setValeur(e.target.value);
            }}
          />
        </label>
        <button type="submit" className="btn btn-mini" disabled={occupe}>
          Enregistrer
        </button>
        {p && (
          <button
            type="button"
            className="btn btn-mini btn-discret"
            disabled={occupe}
            onClick={() => {
              setValeur("");
              enregistrer(null);
            }}
          >
            Retirer
          </button>
        )}
      </form>
      {message && <p className="plafond-message plafond-message--erreur">{message}</p>}
    </div>
  );
}

function Carte({ c, surChangement }: { c: CoutConnecteur; surChangement: () => void }) {
  const approx = c.estime ? "≈ " : "";
  return (
    <li className="carte-cout" data-payant={c.payant || undefined}>
      <div className="carte-cout-tete">
        <h4 className="carte-cout-nom">{c.nom}</h4>
        <span className="badge-co">{FAMILLES[c.famille]}</span>
        {!c.actif && <span className="badge-co">désactivé</span>}
      </div>
      <dl className="carte-cout-chiffres">
        <div>
          <dt>Aujourd'hui</dt>
          <dd>
            {approx}
            {dollars(c.jour.cout_usd)}
          </dd>
        </div>
        <div>
          <dt>Ce mois-ci</dt>
          <dd>
            {approx}
            {dollars(c.mois.cout_usd)}
          </dd>
        </div>
        <div>
          <dt>Appels (mois)</dt>
          <dd>
            {nombre(c.mois.appels)}
            {c.mois.erreurs ? <span className="carte-cout-note"> · {nombre(c.mois.erreurs)} en erreur</span> : null}
          </dd>
        </div>
        <div>
          <dt>Jetons (mois)</dt>
          <dd>
            {nombre(c.mois.jetons_entree)} → {nombre(c.mois.jetons_sortie)}
          </dd>
        </div>
      </dl>
      {c.famille === "cli" && (
        <p className="carte-cout-note">
          Inclus dans votre abonnement{c.equivalent_api_usd ? ` · équivalent API ≈ ${dollars(c.equivalent_api_usd)} ce mois-ci` : ""}.
        </p>
      )}
      {c.estime && <p className="carte-cout-note">≈ estimation d'après les tarifs de votre configuration locale.</p>}
      {c.cout_inconnu > 0 && (
        <p className="carte-cout-note carte-cout-note--ambre">
          {nombre(c.cout_inconnu)} réponse{c.cout_inconnu > 1 ? "s" : ""} sans tarif connu : coût non compté.
        </p>
      )}
      {c.payant && <Plafond key={String(c.plafond?.plafond_usd ?? "")} c={c} surChangement={surChangement} />}
    </li>
  );
}

export function VueCouts() {
  const [resume, setResume] = useState<ResumeCouts | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  const charger = useCallback(() => {
    lireCouts()
      .then((r) => {
        setResume(r);
        setErreur(null);
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Coûts indisponibles.");
      });
  }, []);

  useEffect(() => {
    charger();
    const minuteur = window.setInterval(charger, 60_000);
    return () => {
      window.clearInterval(minuteur);
    };
  }, [charger]);

  if (erreur && !resume) {
    return (
      <div className="vide">
        <p className="vide-titre">Coûts indisponibles</p>
        <p>{erreur}</p>
        <button type="button" className="btn btn-mini" onClick={charger}>
          Réessayer
        </button>
      </div>
    );
  }
  if (!resume) {
    return (
      <div className="couts" aria-busy="true">
        <div className="squelette couts-squelette" />
        <div className="squelette couts-squelette" />
      </div>
    );
  }
  const estimation = resume.connecteurs.some((c) => c.estime);
  const mois = new Date(`${resume.mois}-15T12:00:00`).toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
  return (
    <div className="couts">
      <section className="couts-totaux" aria-label="Totaux">
        <div className="total">
          <span className="total-libelle">Aujourd'hui</span>
          <span className="total-valeur">
            {estimation ? "≈ " : ""}
            {dollars(resume.total_jour_usd)}
          </span>
        </div>
        <div className="total">
          <span className="total-libelle">{mois}</span>
          <span className="total-valeur">
            {estimation ? "≈ " : ""}
            {dollars(resume.total_mois_usd)}
          </span>
        </div>
        <p className="couts-note">
          Ce que vos IA payantes ont coûté, mesuré à chaque appel. {estimation ? "« ≈ » : estimation d'après vos tarifs." : ""}
        </p>
      </section>

      <section className="couts-section">
        <h3 className="couts-titre">Abonnement Claude</h3>
        <p className="couts-note">
          Lu dans les réponses de vos propres échanges avec Claude Code ; JARVIS ne consulte jamais votre compte ni vos identifiants.
        </p>
        <ul className="jauges">
          {resume.jauges.map((j) => (
            <Jauge key={j.type} j={j} />
          ))}
        </ul>
      </section>

      <section className="couts-section">
        <h3 className="couts-titre">30 derniers jours</h3>
        <Histogramme jours={resume.jours} />
      </section>

      <section className="couts-section">
        <h3 className="couts-titre">Par connecteur</h3>
        {resume.connecteurs.length === 0 ? (
          <p className="couts-vide">Aucun connecteur actif : activez une IA dans Connecteurs.</p>
        ) : (
          <ul className="cartes-couts">
            {resume.connecteurs.map((c) => (
              <Carte key={c.id} c={c} surChangement={charger} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
