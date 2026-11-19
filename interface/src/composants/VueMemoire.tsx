import { useCallback, useEffect, useState } from "react";

import { changerNiveauSouvenir, lireEtatMemoire, listerOrigines, listerSouvenirs, listerVersionsSouvenir, remplacerSouvenir } from "../api";
import { avecNiveau, avecRemplacement, LIBELLES_NIVEAU, lireCompteurs, niveauSouvenir, phraseCompteurs, versionsOrdonnees } from "../niveaux";
import { TexteRiche } from "../texte";
import type { CompteursNiveaux, Niveau, OrigineMemoire, Souvenir, VersionSouvenir } from "../types";
import { SectionMemoire } from "./Memoire";
import { SelecteurNiveau } from "./Niveau";
import { VueProfil } from "./VueProfil";

const JOUR = 86_400_000;
const DATE = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long" });
const DATE_ANNEE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", year: "numeric" });
const HEURE = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });
const DATE_VERSION = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });

function messageErreur(e: unknown, defaut: string): string {
  return e instanceof Error ? e.message : defaut;
}

const NOMS_TYPE: Record<string, string> = { note: "note", idee: "idée", decision: "décision", fait: "fait", projet: "projet" };

function jourDe(date: Date, maintenant: Date): string {
  const debut = new Date(maintenant.getFullYear(), maintenant.getMonth(), maintenant.getDate()).getTime();
  const t = date.getTime();
  if (t >= debut) return "Aujourd'hui";
  if (t >= debut - JOUR) return "Hier";
  return date.getFullYear() === maintenant.getFullYear() ? DATE.format(date) : DATE_ANNEE.format(date);
}

/** Historique d'un souvenir remplacé : les anciennes versions barrées, avec la date où elles ont cessé d'être vraies. */
function Versions({ id }: { id: string }) {
  const [versions, setVersions] = useState<VersionSouvenir[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  useEffect(() => {
    listerVersionsSouvenir(id)
      .then((r) => {
        setVersions(versionsOrdonnees(r.versions));
      })
      .catch((e: unknown) => {
        setErreur(messageErreur(e, "Historique illisible."));
      });
  }, [id]);
  if (erreur)
    return (
      <p className="souvenir-erreur" role="alert">
        {erreur}
      </p>
    );
  if (!versions) return <div className="squelette squelette--ligne" aria-busy="true" aria-label="Chargement des versions" />;
  return (
    <ol className="souvenir-versions" aria-label="Versions de ce souvenir, de la plus ancienne à l'actuelle">
      {versions.map((v) => (
        <li key={v.id} className="souvenir-version" data-actuelle={v.valid_to === null || undefined}>
          {v.valid_to === null ? (
            <span className="souvenir-version-date">actuelle · depuis le {DATE_VERSION.format(new Date(v.cree_le))}</span>
          ) : (
            <span className="souvenir-version-date">
              valable jusqu'au <time dateTime={v.valid_to}>{DATE_VERSION.format(new Date(v.valid_to))}</time>
            </span>
          )}
          {v.valid_to === null ? <p className="souvenir-version-texte">{v.contenu}</p> : <del className="souvenir-version-texte">{v.contenu}</del>}
        </li>
      ))}
    </ol>
  );
}

function Carte({
  s,
  origines,
  surNiveau,
  surRemplace,
}: {
  s: Souvenir;
  origines: Map<string, string>;
  surNiveau: (s: Souvenir, n: Niveau) => Promise<void>;
  surRemplace: (s: Souvenir, contenu: string) => Promise<void>;
}) {
  const [ouvert, setOuvert] = useState(false);
  const [avis, setAvis] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);
  const [occupe, setOccupe] = useState(false);
  const [versions, setVersions] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const long = s.contenu.length > 280;
  const niveau = niveauSouvenir(s);
  const idAvis = `avis-${s.id}`;
  const nouveauTexte = avis?.trim() ?? "";
  const inchange = !nouveauTexte || nouveauTexte === s.contenu.trim();
  return (
    <li className="souvenir" data-origine={s.origine} data-niveau={niveau}>
      <div className="souvenir-tete">
        <span className="souvenir-origine">{origines.get(s.origine) ?? s.origine}</span>
        <span className="souvenir-type">{NOMS_TYPE[s.type] ?? s.type}</span>
        <SelecteurNiveau
          niveau={niveau}
          etiquette="Niveau de confidentialité du souvenir"
          occupe={occupe}
          surChoisir={(n) => {
            setOccupe(true);
            setErreur(null);
            surNiveau(s, n)
              .catch((e: unknown) => {
                setErreur(messageErreur(e, "Niveau inchangé."));
              })
              .finally(() => {
                setOccupe(false);
              });
          }}
        />
        {s.tags.includes("noyau") && <span className="badge-co">noyau</span>}
        <time className="souvenir-heure" dateTime={s.cree_le}>
          {HEURE.format(new Date(s.cree_le))}
        </time>
      </div>
      <div className="souvenir-texte" data-replie={long && !ouvert ? "" : undefined}>
        <TexteRiche source={s.contenu} />
      </div>
      {erreur && (
        <p className="souvenir-erreur" role="alert">
          {erreur}
        </p>
      )}
      {avis !== null && (
        <form
          className="souvenir-avis"
          onSubmit={(e) => {
            e.preventDefault();
            if (inchange) return;
            setEnvoi(true);
            setErreur(null);
            surRemplace(s, nouveauTexte).catch((err: unknown) => {
              setErreur(messageErreur(err, "Remplacement impossible."));
              setEnvoi(false);
            });
          }}
        >
          <label className="souvenir-avis-etiquette" htmlFor={idAvis}>
            Ce qui est vrai maintenant (l'ancienne version reste dans l'historique)
          </label>
          <textarea
            id={idAvis}
            className="bloc-texte"
            rows={3}
            value={avis}
            autoFocus
            onChange={(e) => {
              setAvis(e.target.value);
            }}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.stopPropagation();
                setAvis(null);
              }
            }}
          />
          <div className="carte-co-actions">
            <button type="submit" className="btn btn-mini" disabled={envoi || inchange}>
              {envoi ? "Remplacement…" : "Remplacer"}
            </button>
            <button
              type="button"
              className="btn btn-discret btn-mini"
              disabled={envoi}
              onClick={() => {
                setAvis(null);
              }}
            >
              Annuler
            </button>
          </div>
        </form>
      )}
      <div className="souvenir-actions">
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
        {avis === null && (
          <button
            type="button"
            className="lien-btn"
            onClick={() => {
              setAvis(s.contenu);
            }}
          >
            J'ai changé d'avis
          </button>
        )}
        {s.remplace && (
          <button
            type="button"
            className="lien-btn"
            aria-expanded={versions}
            onClick={() => {
              setVersions((v) => !v);
            }}
          >
            {versions ? "Masquer les versions" : "Versions"}
          </button>
        )}
      </div>
      {versions && <Versions id={s.id} />}
    </li>
  );
}

/** Vue Mémoire : tout ce que JARVIS sait, par origine, du plus récent au plus ancien, et la recherche telle que le
 * dialogue la fait. Les blocs éditables, le modèle et les tâches de nuit restent en bas. */
/** `demande` : recherche lancée de l'extérieur (JARVIS ou une commande rapide) ; un nouveau jeton la relance. */
export function VueMemoire({ surChangement, demande }: { surChangement: (m?: string) => void; demande?: { texte: string; jeton: number } | null }) {
  const [origines, setOrigines] = useState<OrigineMemoire[]>([]);
  const [origine, setOrigine] = useState("");
  const [recherche, setRecherche] = useState(demande?.texte ?? "");
  const jetonDemande = demande?.jeton;
  useEffect(() => {
    if (demande) setRecherche(demande.texte);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- seul un nouveau jeton (nouvelle demande) relance la recherche
  }, [jetonDemande]);
  const [souvenirs, setSouvenirs] = useState<Souvenir[] | null>(null);
  const [suite, setSuite] = useState(false);
  const [chargement, setChargement] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [profil, setProfil] = useState(false);
  const [compteurs, setCompteurs] = useState<CompteursNiveaux | null>(null);
  const texte = recherche.trim();

  useEffect(() => {
    listerOrigines()
      .then((r) => {
        setOrigines(r.origines);
      })
      .catch(() => {
        /* les filtres attendront : la liste dit déjà l'erreur */
      });
    lireEtatMemoire()
      .then((e) => {
        setCompteurs(lireCompteurs(e.niveaux));
      })
      .catch(() => {
        /* compteurs facultatifs (ancien Core) : rien à afficher */
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

  /** Mise à jour optimiste du niveau ; retour à l'ancien niveau si le Core refuse (l'erreur remonte à la carte). */
  const changerNiveau = (s: Souvenir, n: Niveau) => {
    const ancien = niveauSouvenir(s);
    setSouvenirs((liste) => (liste ? avecNiveau(liste, s.id, n) : liste));
    return changerNiveauSouvenir(s.id, n)
      .then((r) => {
        setSouvenirs((liste) => (liste ? liste.map((x) => (x.id === s.id ? { ...x, ...r.souvenir } : x)) : liste));
        setCompteurs((c) => (c && ancien !== n ? { ...c, [ancien]: Math.max(0, c[ancien] - 1), [n]: c[n] + 1 } : c));
        surChangement(`Souvenir passé en ${LIBELLES_NIVEAU[n].nom}.`);
      })
      .catch((e: unknown) => {
        setSouvenirs((liste) => (liste ? avecNiveau(liste, s.id, ancien) : liste));
        throw e;
      });
  };
  const remplacer = (s: Souvenir, contenu: string) =>
    remplacerSouvenir(s.id, contenu).then((r) => {
      setSouvenirs((liste) => (liste ? avecRemplacement(liste, s.id, r.nouveau) : liste));
      surChangement("Souvenir mis à jour : l'ancienne version est gardée dans l'historique.");
    });

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
        {compteurs && (
          <p className="memoire-niveaux" title="Public : peut partir vers une IA externe · semi-privé : seulement s'il est utile au message · privé : jamais">
            {phraseCompteurs(compteurs)}
          </p>
        )}
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
                  <Carte key={s.id} s={s} origines={noms} surNiveau={changerNiveau} surRemplace={remplacer} />
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
