// Réglages › Cerveau & coûts › Routes : modèle par type de tâche, scores mesurés, rétrogradations (14 · B 11).

import { useCallback, useEffect, useState } from "react";

import { duree, nombre } from "../couts";
import {
  essayerClassement,
  lireRoutes,
  reglerClassifieur,
  reglerRoute,
  retablirRoute,
  texteEtat,
  texteEvenement,
  texteScore,
  texteSource,
  tonScore,
  type RouteType,
  type SourceClassement,
  type TableauRoutes,
} from "../routage";
import "../styles/routes.css";

function message(e: unknown, defaut: string): string {
  return e instanceof Error ? e.message : defaut;
}

function CarteRoute({
  r,
  tableau,
  surMaj,
}: {
  r: RouteType;
  tableau: TableauRoutes;
  surMaj: (t: TableauRoutes) => void;
}) {
  const [erreur, setErreur] = useState<string | null>(null);
  const [occupe, setOccupe] = useState(false);
  const prive = r.type === "prive";
  const choix = tableau.connecteurs.filter((c) => !prive || c.local);
  const nomActuel = tableau.connecteurs.find((c) => c.id === r.actuel)?.nom ?? r.actuel;

  const agir = (appel: () => Promise<TableauRoutes>) => {
    setOccupe(true);
    setErreur(null);
    appel()
      .then(surMaj)
      .catch((e: unknown) => {
        setErreur(message(e, "Échec."));
      })
      .finally(() => {
        setOccupe(false);
      });
  };

  return (
    <li className="route" data-type={r.type}>
      <div className="route-tete">
        <h4 className="route-nom">{r.libelle}</h4>
        <span className="route-desc">{r.description}</span>
      </div>
      <label className="route-champ">
        <span>IA préférée</span>
        <select
          className="select"
          value={r.connecteur ?? ""}
          disabled={occupe}
          onChange={(e) => {
            const v = e.target.value || null;
            agir(() => reglerRoute(r.type, v));
          }}
        >
          <option value="">Automatique (routeur habituel{prive ? ", IA du PC" : ""})</option>
          {choix.map((c) => (
            <option key={c.id} value={c.id}>
              {c.nom}
            </option>
          ))}
          {r.connecteur && !choix.some((c) => c.id === r.connecteur) && <option value={r.connecteur}>{r.connecteur} (indisponible)</option>}
        </select>
      </label>
      <p className="route-actuel">
        En ce moment : <strong>{nomActuel ?? (prive ? "aucune IA du PC disponible : refus plutôt qu'une fuite" : "aucune IA disponible")}</strong>
        {prive && " · ne quitte jamais le PC"}
      </p>
      {r.candidats.length === 0 ? (
        <p className="route-vide">Aucune IA candidate pour cette route.</p>
      ) : (
        <ul className="route-candidats" aria-label={`Scores de la route ${r.libelle}`}>
          {r.candidats.map((c) => (
            <li key={c.connecteur} className="candidat" data-etat={c.etat} data-ton={tonScore(c.score, tableau.seuil)}>
              <div className="candidat-tete">
                <span className="candidat-nom">
                  {c.nom}
                  {!c.disponible && <span className="candidat-note"> · indisponible</span>}
                </span>
                <span className="candidat-score">{texteScore(c.score)}</span>
              </div>
              <p className="candidat-chiffres">
                {nombre(c.appels)} appel{c.appels > 1 ? "s" : ""} · {nombre(c.erreurs)} erreur{c.erreurs > 1 ? "s" : ""}
                {c.latence_moy_ms != null && ` · ${duree(c.latence_moy_ms)} en moyenne`} · 👍 {nombre(c.positifs)} · 👎 {nombre(c.negatifs)}
              </p>
              <div className="candidat-pied">
                <span className="candidat-etat">{texteEtat(c, tableau.min_mesures)}</span>
                {c.etat === "retrogradee" && (
                  <button
                    type="button"
                    className="btn btn-mini"
                    disabled={occupe}
                    onClick={() => {
                      agir(() => retablirRoute(r.type, c.connecteur));
                    }}
                  >
                    Rétablir
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {erreur && (
        <p className="route-erreur" role="alert">
          {erreur}
        </p>
      )}
    </li>
  );
}

function Classifieur({ tableau, surMaj }: { tableau: TableauRoutes; surMaj: (t: TableauRoutes) => void }) {
  const [erreur, setErreur] = useState<string | null>(null);
  const [texte, setTexte] = useState("");
  const [essai, setEssai] = useState<{ libelle: string; raison: string; source: SourceClassement } | null>(null);
  const k = tableau.classifieur;
  const modeles = k.modele && !k.modeles.includes(k.modele) ? [k.modele, ...k.modeles] : k.modeles;

  return (
    <section className="routes-section">
      <h3 className="routes-titre">Classement des messages</h3>
      <p className="routes-note">
        Des règles locales rangent chaque message (code, raisonnement, rapide, privé) et disent pourquoi. Un petit modèle Ollama ne sert que si elles hésitent,
        et seulement s'il tourne déjà : JARVIS ne démarre jamais Ollama pour ça.
      </p>
      <label className="route-champ">
        <span>Petit modèle en cas d'hésitation</span>
        <select
          className="select"
          value={k.modele ?? ""}
          onChange={(e) => {
            setErreur(null);
            reglerClassifieur(e.target.value || null)
              .then(surMaj)
              .catch((x: unknown) => {
                setErreur(message(x, "Échec."));
              });
          }}
        >
          <option value="">Aucun : les règles seules</option>
          {modeles.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </label>
      <p className="routes-note">
        {k.ollama_disponible ? `Ollama tourne : ${String(k.modeles.length)} modèle${k.modeles.length > 1 ? "s" : ""} installé${k.modeles.length > 1 ? "s" : ""}.` : "Ollama arrêté ou désactivé : les règles décident seules."}
      </p>
      <form
        className="routes-essai"
        onSubmit={(e) => {
          e.preventDefault();
          if (!texte.trim()) return;
          setErreur(null);
          essayerClassement(texte)
            .then(setEssai)
            .catch((x: unknown) => {
              setErreur(message(x, "Échec."));
            });
        }}
      >
        <label className="route-champ routes-essai-champ">
          <span>Essayer une phrase</span>
          <input
            type="text"
            value={texte}
            maxLength={8000}
            placeholder="ex. Pourquoi ce script Python plante-t-il ?"
            onChange={(e) => {
              setTexte(e.target.value);
            }}
          />
        </label>
        <button type="submit" className="btn btn-mini" disabled={!texte.trim()}>
          Classer
        </button>
      </form>
      {essai && (
        <p className="routes-resultat" role="status">
          <strong>{essai.libelle}</strong> — {essai.raison} <span className="routes-note">({texteSource(essai.source)})</span>
        </p>
      )}
      {erreur && (
        <p className="route-erreur" role="alert">
          {erreur}
        </p>
      )}
    </section>
  );
}

export function VueRoutes() {
  const [tableau, setTableau] = useState<TableauRoutes | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  const charger = useCallback(() => {
    lireRoutes()
      .then((t) => {
        setTableau(t);
        setErreur(null);
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Routes indisponibles."));
      });
  }, []);

  useEffect(() => {
    charger();
  }, [charger]);

  if (erreur && !tableau) {
    return (
      <div className="vide">
        <p className="vide-titre">Routes indisponibles</p>
        <p>{erreur}</p>
        <button type="button" className="btn btn-mini" onClick={charger}>
          Réessayer
        </button>
      </div>
    );
  }
  if (!tableau) {
    return (
      <div className="routes" aria-busy="true">
        <div className="squelette routes-squelette" />
      </div>
    );
  }
  const nom = (id: string) => tableau.connecteurs.find((c) => c.id === id)?.nom ?? id;
  return (
    <div className="routes">
      <section className="routes-section">
        <h3 className="routes-titre">Une IA par type de tâche</h3>
        <p className="routes-note">
          Score sur {String(tableau.fenetre_jours)} jours : réponses réussies, erreurs, durée et vos avis 👍 / 👎 sous les réponses. Après{" "}
          {String(tableau.min_mesures)} mesures, une IA sous {String(tableau.seuil)} / 100 est rétrogradée : la suivante prend le relais. Le plafond de dépenses
          reste respecté.
        </p>
        <ul className="routes-liste">
          {tableau.types.map((r) => (
            <CarteRoute key={r.type} r={r} tableau={tableau} surMaj={setTableau} />
          ))}
        </ul>
      </section>
      <Classifieur tableau={tableau} surMaj={setTableau} />
      <section className="routes-section">
        <h3 className="routes-titre">Rétrogradations</h3>
        {tableau.historique.length === 0 ? (
          <p className="route-vide">Aucune route rétrogradée pour l'instant.</p>
        ) : (
          <ol className="routes-historique">
            {tableau.historique.map((h) => (
              <li key={`${h.le}-${h.type}-${h.connecteur}-${h.evenement}`} data-evenement={h.evenement}>
                <time dateTime={h.le}>{new Date(h.le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</time>
                <span>
                  {tableau.types.find((t) => t.type === h.type)?.libelle ?? h.type} · {nom(h.connecteur)} : <strong>{texteEvenement(h)}</strong>
                </span>
                <span className="routes-note">{h.raison}</span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}
