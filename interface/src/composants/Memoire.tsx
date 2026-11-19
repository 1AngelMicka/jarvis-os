import { useCallback, useEffect, useState } from "react";

import { ecrireBloc, lancerTacheMemoire, lireEtatMemoire, listerBlocs, noyauEnBlocs } from "../api";
import { confidentialiteDe, LIBELLES_NIVEAU, lireCompteurs, niveauBloc, phraseCompteurs } from "../niveaux";
import type { BlocMemoire, EtatMemoire, Niveau } from "../types";
import { SelecteurNiveau } from "./Niveau";
import { Telechargements } from "./Telechargements";

const DATE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function CarteBloc({ b, surEnregistre, surNotifier }: { b: BlocMemoire; surEnregistre: (m: string) => void; surNotifier: (m: string) => void }) {
  // Le bloc tel qu'enregistré : un changement de niveau le remplace sans toucher au brouillon du texte.
  const [bloc, setBloc] = useState(b);
  const [texte, setTexte] = useState(b.content);
  const [niveau, setNiveau] = useState<Niveau>(niveauBloc(b));
  const [occupe, setOccupe] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const modifie = texte !== bloc.content;
  /** Mise à jour optimiste : le niveau change tout de suite, et revient en arrière si le Core refuse. */
  const changerNiveau = (n: Niveau) => {
    const ancien = niveau;
    setNiveau(n);
    setOccupe(true);
    setMessage(null);
    ecrireBloc(bloc.label, bloc.content, confidentialiteDe(n), n)
      .then((r) => {
        setBloc(r);
        setNiveau(niveauBloc({ niveau: r.niveau ?? n, confidentialite: r.confidentialite }));
        surNotifier(`Bloc « ${r.label} » passé en ${LIBELLES_NIVEAU[n].nom}.`);
      })
      .catch((e: unknown) => {
        setNiveau(ancien);
        setMessage(e instanceof Error ? e.message : "Niveau inchangé.");
      })
      .finally(() => {
        setOccupe(false);
      });
  };
  return (
    <li className="carte-co" data-niveau={niveau}>
      <div className="carte-co-tete">
        <h4 className="carte-co-nom">{bloc.label}</h4>
        <span className="badge-co">v{bloc.version}</span>
        <SelecteurNiveau niveau={niveau} etiquette={`Niveau de confidentialité du bloc ${bloc.label}`} occupe={occupe} surChoisir={changerNiveau} />
      </div>
      <label className="visuellement-cache" htmlFor={`bloc-${bloc.label}`}>
        Contenu du bloc {bloc.label}
      </label>
      <textarea
        id={`bloc-${bloc.label}`}
        className="bloc-texte"
        rows={4}
        maxLength={bloc.char_limit}
        value={texte}
        onChange={(e) => {
          setTexte(e.target.value);
        }}
      />
      <p className="carte-co-detail">
        {texte.length} / {bloc.char_limit} caractères · modifié {DATE.format(new Date(bloc.maj_le))} · chaque version est gardée
      </p>
      {message && (
        <p className="carte-co-message" role="alert">
          {message}
        </p>
      )}
      <div className="carte-co-actions">
        <button
          type="button"
          className="btn btn-mini"
          disabled={!modifie || occupe}
          onClick={() => {
            ecrireBloc(bloc.label, texte, confidentialiteDe(niveau), niveau)
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

  const compteurs = lireCompteurs(etat?.niveaux);
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
          {etat.souvenirs.total.toLocaleString("fr-FR")} souvenirs actifs (
          {compteurs ? phraseCompteurs(compteurs) : `${etat.souvenirs.local_uniquement.toLocaleString("fr-FR")} privés`}) · modèle{" "}
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
        Les blocs sont de courts textes toujours donnés à JARVIS (vos préférences, votre situation…). Un bloc public peut accompagner
        chaque message vers une IA externe, un bloc semi-privé ou privé ne part jamais vers elle.
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
            <CarteBloc key={`${b.label}-${String(b.version)}`} b={b} surEnregistre={apres} surNotifier={surChangement} />
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
