import { useCallback, useEffect, useState } from "react";

import { ecrireBloc, lancerTacheMemoire, lireEtatMemoire, listerBlocs, noyauEnBlocs } from "../api";
import type { BlocMemoire, EtatMemoire } from "../types";
import { Telechargements } from "./Telechargements";

const DATE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function CarteBloc({ b, surEnregistre }: { b: BlocMemoire; surEnregistre: (m: string) => void }) {
  const [texte, setTexte] = useState(b.content);
  const [prive, setPrive] = useState(b.confidentialite === "local_uniquement");
  const [message, setMessage] = useState<string | null>(null);
  const modifie = texte !== b.content || prive !== (b.confidentialite === "local_uniquement");
  return (
    <li className="carte-co">
      <div className="carte-co-tete">
        <h4 className="carte-co-nom">{b.label}</h4>
        <span className="badge-co">v{b.version}</span>
        {prive && (
          <span className="badge-co" data-ton="attention" title="Jamais envoyé à une IA externe">
            Privé
          </span>
        )}
      </div>
      <label className="visuellement-cache" htmlFor={`bloc-${b.label}`}>
        Contenu du bloc {b.label}
      </label>
      <textarea
        id={`bloc-${b.label}`}
        className="bloc-texte"
        rows={4}
        maxLength={b.char_limit}
        value={texte}
        onChange={(e) => {
          setTexte(e.target.value);
        }}
      />
      <p className="carte-co-detail">
        {texte.length} / {b.char_limit} caractères · modifié {DATE.format(new Date(b.maj_le))} · chaque version est gardée
      </p>
      {message && <p className="carte-co-message">{message}</p>}
      <div className="carte-co-actions">
        <label className="carte-co-case carte-co-case--ligne">
          <input
            type="checkbox"
            checked={prive}
            onChange={(e) => {
              setPrive(e.target.checked);
            }}
          />
          Privé (IA locales seulement)
        </label>
        <button
          type="button"
          className="btn btn-mini"
          disabled={!modifie}
          onClick={() => {
            ecrireBloc(b.label, texte, prive ? "local_uniquement" : "normal")
              .then((n) => {
                surEnregistre(`Bloc « ${n.label} » enregistré (version ${String(n.version)}).`);
              })
              .catch((e: unknown) => {
                setMessage(e instanceof Error ? e.message : "Enregistrement impossible.");
              });
          }}
        >
          Enregistrer
        </button>
      </div>
    </li>
  );
}

/** Mémoire v2 : état, bascule de modèle, tâches de nuit, blocs éditables. */
export function SectionMemoire({ surChangement }: { surChangement: (m?: string) => void }) {
  const [etat, setEtat] = useState<EtatMemoire | null>(null);
  const [liste, setListe] = useState<BlocMemoire[] | null>(null);
  const [nouveau, setNouveau] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);

  const charger = useCallback(() => {
    Promise.all([lireEtatMemoire(), listerBlocs()])
      .then(([e, b]) => {
        setEtat(e);
        setListe(b.blocs);
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Lecture impossible.");
      });
  }, []);
  useEffect(charger, [charger]);
  useEffect(() => {
    if (!etat?.bascule?.cible) return;
    const minuterie = window.setInterval(charger, 4000);
    return () => {
      window.clearInterval(minuterie);
    };
  }, [etat?.bascule?.cible, charger]);

  const apres = (m: string) => {
    surChangement(m);
    charger();
  };

  return (
    <section className="famille-co" aria-labelledby="agents-memoire">
      <h3 className="sec-titre" id="agents-memoire">
        Mémoire
      </h3>
      {erreur && <p className="securite-erreur">{erreur}</p>}
      {etat && (
        <p className="sec-texte">
          {etat.souvenirs.total.toLocaleString("fr-FR")} souvenirs actifs ({etat.souvenirs.local_uniquement} privés) · modèle{" "}
          <code>{etat.modele_actif ?? "—"}</code>
          {etat.bascule?.cible &&
            ` · bascule vers ${etat.bascule.cible} : ${String(etat.bascule.faits)} faits, ${String(etat.bascule.restants)} restants (la recherche garde l'ancien modèle jusqu'à la fin)`}
          {etat.bascule?.erreur && ` · bascule interrompue : ${etat.bascule.erreur}`}
        </p>
      )}
      <Telechargements ids={["embeddings"]} surMessage={surChangement} />
      {etat && etat.taches.length > 0 && (
        <ul className="cartes-co">
          {etat.taches.map((t) => (
            <li key={t.id} className="carte-co">
              <div className="carte-co-tete">
                <h4 className="carte-co-nom">{t.nom}</h4>
                {t.derniere && (
                  <span className="badge-co" data-ton={t.derniere.statut === "ok" ? "ok" : t.derniere.statut === "erreur" ? "risque" : undefined}>
                    {t.derniere.statut}
                  </span>
                )}
              </div>
              <p className="carte-co-detail">
                <code>{t.planification}</code>
                {t.derniere ? ` · dernière : ${DATE.format(new Date(t.derniere.debut))}` : " · jamais lancée"}
                {t.derniere?.resultat && ` · ${t.derniere.resultat.slice(0, 160)}`}
              </p>
              <div className="carte-co-actions">
                <button
                  type="button"
                  className="btn btn-discret btn-mini"
                  onClick={() => {
                    lancerTacheMemoire(t.id)
                      .then(() => {
                        apres(`${t.nom} : lancée.`);
                      })
                      .catch((e: unknown) => {
                        setErreur(e instanceof Error ? e.message : "Lancement impossible.");
                      });
                  }}
                >
                  Lancer maintenant
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="sec-texte">
        Les blocs sont de courts textes toujours donnés à JARVIS (vos préférences, votre situation…). Un bloc privé ne part jamais vers une
        IA externe.
      </p>
      {etat && etat.souvenirs.noyau > 0 && (
        <button
          type="button"
          className="btn btn-mini"
          onClick={() => {
            noyauEnBlocs()
              .then((r) => {
                apres(`Noyau converti en blocs : ${Object.entries(r.convertis).map(([k, v]) => `${k} (${String(v)})`).join(", ")}.`);
              })
              .catch((e: unknown) => {
                setErreur(e instanceof Error ? e.message : "Conversion impossible.");
              });
          }}
        >
          Convertir le noyau ({etat.souvenirs.noyau} souvenirs) en blocs
        </button>
      )}
      {liste && (
        <ul className="cartes-co">
          {liste.map((b) => (
            <CarteBloc key={`${b.label}-${String(b.version)}`} b={b} surEnregistre={apres} />
          ))}
        </ul>
      )}
      <form
        className="carte-co-cle"
        onSubmit={(e) => {
          e.preventDefault();
          const label = nouveau.trim().toLowerCase();
          ecrireBloc(label, "")
            .then(() => {
              setNouveau("");
              apres(`Bloc « ${label} » créé : écrivez son contenu.`);
            })
            .catch((err: unknown) => {
              setErreur(err instanceof Error ? err.message : "Création impossible.");
            });
        }}
      >
        <label className="visuellement-cache" htmlFor="nouveau-bloc">
          Nom du nouveau bloc
        </label>
        <input
          id="nouveau-bloc"
          value={nouveau}
          placeholder="Nouveau bloc (ex. preferences, situation, persona)"
          onChange={(e) => {
            setNouveau(e.target.value);
          }}
        />
        <button type="submit" className="btn btn-mini" disabled={!/^[a-z0-9][a-z0-9_.:-]{0,63}$/.test(nouveau.trim().toLowerCase())}>
          Créer
        </button>
      </form>
    </section>
  );
}
