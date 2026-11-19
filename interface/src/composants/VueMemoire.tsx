import { useCallback, useEffect, useState } from "react";

import { listerOrigines, listerSouvenirs } from "../api";
import { TexteRiche } from "../texte";
import type { OrigineMemoire, Souvenir } from "../types";
import { SectionMemoire } from "./Memoire";
import { VueProfil } from "./VueProfil";

const JOUR = 86_400_000;
const DATE = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long" });
const DATE_ANNEE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", year: "numeric" });
const HEURE = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });

const NOMS_TYPE: Record<string, string> = { note: "note", idee: "idée", decision: "décision", fait: "fait", projet: "projet" };

function jourDe(date: Date, maintenant: Date): string {
  const debut = new Date(maintenant.getFullYear(), maintenant.getMonth(), maintenant.getDate()).getTime();
  const t = date.getTime();
  if (t >= debut) return "Aujourd'hui";
  if (t >= debut - JOUR) return "Hier";
  return date.getFullYear() === maintenant.getFullYear() ? DATE.format(date) : DATE_ANNEE.format(date);
}

function Carte({ s, origines }: { s: Souvenir; origines: Map<string, string> }) {
  const [ouvert, setOuvert] = useState(false);
  const long = s.contenu.length > 280;
  return (
    <li className="souvenir" data-origine={s.origine}>
      <div className="souvenir-tete">
        <span className="souvenir-origine">{origines.get(s.origine) ?? s.origine}</span>
        <span className="souvenir-type">{NOMS_TYPE[s.type] ?? s.type}</span>
        {s.confidentialite === "local_uniquement" && (
          <span className="badge-co" data-ton="attention" title="Ne part jamais vers une IA externe">
            privé
          </span>
        )}
        {s.tags.includes("noyau") && <span className="badge-co">noyau</span>}
        <time className="souvenir-heure" dateTime={s.cree_le}>
          {HEURE.format(new Date(s.cree_le))}
        </time>
      </div>
      <div className="souvenir-texte" data-replie={long && !ouvert ? "" : undefined}>
        <TexteRiche source={s.contenu} />
      </div>
      {long && (
        <button
          type="button"
          className="lien-btn"
          aria-expanded={ouvert}
          onClick={() => {
            setOuvert((o) => !o);
          }}
        >
          {ouvert ? "Réduire" : "Lire la suite"}
        </button>
      )}
    </li>
  );
}

/** Vue Mémoire : tout ce que JARVIS sait, par origine, du plus récent au plus ancien, et la recherche telle que le
 * dialogue la fait. Les blocs éditables, le modèle et les tâches de nuit restent en bas. */
export function VueMemoire({ surChangement }: { surChangement: (m?: string) => void }) {
  const [origines, setOrigines] = useState<OrigineMemoire[]>([]);
  const [origine, setOrigine] = useState("");
  const [recherche, setRecherche] = useState("");
  const [souvenirs, setSouvenirs] = useState<Souvenir[] | null>(null);
  const [suite, setSuite] = useState(false);
  const [chargement, setChargement] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [profil, setProfil] = useState(false);
  const texte = recherche.trim();

  useEffect(() => {
    listerOrigines()
      .then((r) => {
        setOrigines(r.origines);
      })
      .catch(() => {
        /* les filtres attendront : la liste dit déjà l'erreur */
      });
  }, []);

  const charger = useCallback(
    (avant?: string) => {
      setChargement(true);
      setErreur(null);
      return listerSouvenirs({ origine, q: texte, ...(avant ? { avant } : {}) })
        .then((r) => {
          setSouvenirs((liste) => (avant && liste ? [...liste, ...r.souvenirs] : r.souvenirs));
          setSuite(r.suite);
        })
        .catch((e: unknown) => {
          setErreur(e instanceof Error ? e.message : "Mémoire illisible.");
        })
        .finally(() => {
          setChargement(false);
        });
    },
    [origine, texte],
  );

  useEffect(() => {
    const minuterie = window.setTimeout(() => void charger(), texte ? 300 : 0);
    return () => {
      window.clearTimeout(minuterie);
    };
  }, [charger, texte]);

  const noms = new Map(origines.map((o) => [o.id, o.nom]));
  const total = origines.reduce((n, o) => n + o.nombre, 0);
  const maintenant = new Date();
  const jours = new Map<string, Souvenir[]>();
  for (const s of souvenirs ?? []) {
    const j = texte ? "Résultats" : jourDe(new Date(s.cree_le), maintenant);
    jours.set(j, [...(jours.get(j) ?? []), s]);
  }

  if (profil)
    return (
      <VueProfil
        surRetour={() => {
          setProfil(false);
          void charger();
        }}
      />
    );

  return (
    <div className="memoire-vue">
      <div className="memoire-profil">
        <p className="memoire-profil-texte">Aidez JARVIS à vous connaître : un questionnaire guidé, par sections, à l'écrit ou à voix haute.</p>
        <button
          type="button"
          className="btn btn-mini"
          onClick={() => {
            setProfil(true);
          }}
        >
          Profil guidé
        </button>
      </div>
      <div className="memoire-outils">
        <label className="hist-recherche memoire-recherche">
          <span className="visuellement-cache">Chercher dans la mémoire</span>
          <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="11" cy="11" r="6.5" />
            <path d="m16 16 4.5 4.5" />
          </svg>
          <input
            type="search"
            value={recherche}
            placeholder="Chercher dans la mémoire"
            title="La recherche suit le sens autant que les mots, comme JARVIS quand il répond"
            onChange={(e) => {
              setRecherche(e.target.value);
            }}
          />
        </label>
        <div className="puces" role="group" aria-label="Filtrer par origine">
          <button
            type="button"
            className="puce"
            aria-pressed={!origine}
            onClick={() => {
              setOrigine("");
            }}
          >
            Tout <span className="puce-nombre">{total.toLocaleString("fr-FR")}</span>
          </button>
          {origines.map((o) => (
            <button
              key={o.id}
              type="button"
              className="puce"
              aria-pressed={origine === o.id}
              onClick={() => {
                setOrigine((x) => (x === o.id ? "" : o.id));
              }}
            >
              {o.nom} <span className="puce-nombre">{o.nombre.toLocaleString("fr-FR")}</span>
            </button>
          ))}
        </div>
      </div>

      {erreur && (
        <p className="securite-erreur" role="alert">
          {erreur}
        </p>
      )}
      {souvenirs === null ? (
        <div className="memoire-chargement" aria-busy="true" aria-label="Chargement de la mémoire">
          <div className="squelette squelette--ligne" />
          <div className="squelette squelette--ligne" />
          <div className="squelette squelette--ligne" />
        </div>
      ) : !souvenirs.length ? (
        <div className="vide vide--calme">
          <p className="vide-titre">{texte ? "Rien de tel en mémoire" : "Aucun souvenir ici"}</p>
          <p>{texte ? "Essayez d'autres mots : la recherche suit le sens autant que les mots." : "Ce qu'apprend JARVIS apparaîtra ici."}</p>
        </div>
      ) : (
        <div className="memoire-chronologie" aria-busy={chargement || undefined}>
          {[...jours].map(([jour, liste]) => (
            <section key={jour} className="memoire-jour" aria-label={jour}>
              <h3 className="hist-groupe-titre">{jour}</h3>
              <ul className="souvenirs">
                {liste.map((s) => (
                  <Carte key={s.id} s={s} origines={noms} />
                ))}
              </ul>
            </section>
          ))}
          {suite && !texte && (
            <button
              type="button"
              className="btn btn-discret memoire-plus"
              disabled={chargement}
              onClick={() => {
                const dernier = souvenirs.at(-1);
                if (dernier) void charger(dernier.cree_le);
              }}
            >
              {chargement ? "Chargement…" : "Plus ancien"}
            </button>
          )}
        </div>
      )}

      <details className="memoire-reglages">
        <summary>Blocs, modèle d'embeddings et tâches de nuit</summary>
        <SectionMemoire surChangement={surChangement} />
      </details>
    </div>
  );
}
