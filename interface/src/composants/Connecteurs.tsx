import { useCallback, useEffect, useState } from "react";

import {
  activerConnecteur,
  desactiverConnecteur,
  enregistrerCleApi,
  inclureAuConseil,
  lireMateriel,
  listerConnecteurs,
  supprimerCleApi,
  testerConnecteur,
} from "../api";
import type { Connecteur, Materiel } from "../types";

const FAMILLES: { id: Connecteur["famille"]; titre: string; texte: string }[] = [
  {
    id: "cli",
    titre: "Comptes",
    texte:
      "Le programme officiel du fournisseur, installé et connecté par vous. JARVIS ne voit jamais vos identifiants et ne passe pas par l'API.",
  },
  { id: "api", titre: "Clés d'API", texte: "Facturées à l'usage par le fournisseur. Les clés restent dans le coffre de ce PC." },
  { id: "local", titre: "Modèles locaux", texte: "Sur ce PC : rien ne sort. Les serveurs détectés s'activent à la main." },
];

const STATUTS: Record<Connecteur["statut"], { texte: string; ton: string }> = {
  disponible: { texte: "Disponible", ton: "ok" },
  non_connecte: { texte: "Non connecté", ton: "attention" },
  non_installe: { texte: "Non installé", ton: "neutre" },
  desactive: { texte: "Désactivé", ton: "neutre" },
};

interface CarteProps {
  c: Connecteur;
  surChangement: (message?: string) => void;
}

function Carte({ c, surChangement }: CarteProps) {
  const [cle, setCle] = useState("");
  const [coche, setCoche] = useState(false);
  const [avertissement, setAvertissement] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [occupe, setOccupe] = useState(false);

  const agir = (appel: () => Promise<unknown>, ok?: string) => {
    setOccupe(true);
    setMessage(null);
    appel()
      .then(() => {
        surChangement(ok);
      })
      .catch((e: unknown) => {
        setMessage(e instanceof Error ? e.message : "Échec.");
      })
      .finally(() => {
        setOccupe(false);
      });
  };

  // Avertissement à lire et à cocher soi-même : connecteur à risque, ou accueil de Claude Code
  const aAccepter = Boolean(c.conditions) && !c.conditions_acceptees;
  const statut = c.installe && !c.actif && aAccepter && !c.risque ? { texte: "À accepter", ton: "attention" } : STATUTS[c.statut];
  const activer = () => {
    if (aAccepter) {
      setAvertissement(true);
      return;
    }
    agir(() => activerConnecteur(c.id), `${c.nom} activé.`);
  };

  return (
    <li className="carte-co" data-statut={c.statut} data-risque={c.risque || undefined}>
      <div className="carte-co-tete">
        <h4 className="carte-co-nom">{c.nom}</h4>
        <span className="badge-co" data-ton={statut.ton}>
          {statut.texte}
        </span>
        {c.risque && (
          <span className="badge-co" data-ton="risque" title="Les conditions du fournisseur interdisent peut-être cet usage">
            Risque
          </span>
        )}
      </div>
      <p className="carte-co-detail">
        {c.detail}
        {c.modeles.length > 0 && ` · ${String(c.modeles.length)} modèle${c.modeles.length > 1 ? "s" : ""}`}
        {c.externe ? "" : " · données sur ce PC"}
      </p>

      {c.cle && (
        <form
          className="carte-co-cle"
          onSubmit={(e) => {
            e.preventDefault();
            const valeur = cle.trim();
            setCle("");
            agir(() => enregistrerCleApi(c.id, valeur), `Clé de ${c.nom} enregistrée dans le coffre.`);
          }}
        >
          <label className="visuellement-cache" htmlFor={`cle-${c.id}`}>
            Clé d'API {c.nom}
          </label>
          <input
            id={`cle-${c.id}`}
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={cle}
            placeholder={c.cle.enregistree ? `Enregistrée (${c.cle.apercu ?? "••••"})` : "Coller la clé d'API"}
            onChange={(e) => {
              setCle(e.target.value);
            }}
          />
          <button type="submit" className="btn btn-mini" disabled={occupe || cle.trim().length < 8}>
            Enregistrer
          </button>
          {c.cle.enregistree && (
            <button
              type="button"
              className="btn btn-discret btn-mini"
              disabled={occupe}
              onClick={() => {
                agir(() => supprimerCleApi(c.id), "Clé supprimée du coffre.");
              }}
            >
              Supprimer
            </button>
          )}
        </form>
      )}

      {avertissement && c.conditions && (
        <div className="carte-co-avertissement" data-risque={c.risque || undefined} role="alertdialog" aria-labelledby={`av-${c.id}`}>
          <p id={`av-${c.id}`} className="carte-co-avertissement-titre">
            Avant d'activer ce connecteur
          </p>
          <p>{c.conditions.texte}</p>
          <a href={c.conditions.url} target="_blank" rel="noopener noreferrer">
            Lire les conditions d'utilisation
          </a>
          <label className="carte-co-case">
            <input
              type="checkbox"
              checked={coche}
              onChange={(e) => {
                setCoche(e.target.checked);
              }}
            />
            {c.risque
              ? "J'ai lu cet avertissement et j'accepte ce risque pour mon compte."
              : "J'ai lu cet avertissement ; j'utilise ce connecteur pour mon usage personnel."}
          </label>
          <div className="carte-co-actions">
            <button
              type="button"
              className="btn btn-discret btn-mini"
              onClick={() => {
                setAvertissement(false);
                setCoche(false);
              }}
            >
              Annuler
            </button>
            <button
              type="button"
              className={c.risque ? "btn btn-rouge btn-mini" : "btn btn-principal btn-mini"}
              disabled={!coche || occupe}
              onClick={() => {
                const version = c.conditions?.version;
                agir(async () => {
                  await activerConnecteur(c.id, true, version);
                  setAvertissement(false);
                }, c.risque ? `${c.nom} activé, à vos risques.` : `${c.nom} activé.`);
              }}
            >
              {c.risque ? "Activer quand même" : "Activer"}
            </button>
          </div>
        </div>
      )}

      {message && (
        <p className="carte-co-message" role="status">
          {message}
        </p>
      )}

      <div className="carte-co-actions">
        {!c.installe && c.installation_url && (
          <a className="btn btn-discret btn-mini" href={c.installation_url} target="_blank" rel="noopener noreferrer">
            Comment installer
          </a>
        )}
        {c.cle?.url && !c.cle.enregistree && (
          <a className="btn btn-discret btn-mini" href={c.cle.url} target="_blank" rel="noopener noreferrer">
            Créer une clé
          </a>
        )}
        {c.installe && (
          <button
            type="button"
            className="btn btn-discret btn-mini"
            disabled={occupe}
            onClick={() => {
              setOccupe(true);
              testerConnecteur(c.id)
                .then((r) => {
                  setMessage(r.disponible ? `OK : ${r.detail} (${String(r.modeles)} modèle${r.modeles > 1 ? "s" : ""}).` : `Indisponible : ${r.detail}.`);
                })
                .catch((e: unknown) => {
                  setMessage(e instanceof Error ? e.message : "Test impossible.");
                })
                .finally(() => {
                  setOccupe(false);
                });
            }}
          >
            Tester
          </button>
        )}
        {c.actif && c.disponible && (
          <label className="carte-co-case carte-co-case--ligne">
            <input
              type="checkbox"
              checked={c.dans_conseil}
              onChange={(e) => {
                const inclus = e.target.checked;
                agir(() => inclureAuConseil(c.id, inclus));
              }}
            />
            Dans le conseil
          </label>
        )}
        {c.actif && c.installe ? (
          <button
            type="button"
            className="btn btn-discret btn-mini"
            disabled={occupe}
            onClick={() => {
              agir(() => desactiverConnecteur(c.id), `${c.nom} désactivé.`);
            }}
          >
            Désactiver
          </button>
        ) : (
          c.installe && (
            <button type="button" className={c.risque ? "btn btn-rouge btn-mini" : "btn btn-mini"} disabled={occupe} onClick={activer}>
              Activer
            </button>
          )
        )}
      </div>
    </li>
  );
}

function Recommandations({ m }: { m: Materiel }) {
  return (
    <div className="materiel">
      <p className="sec-texte">
        Ce PC : {m.ram_go ? `${String(m.ram_go)} Go de mémoire` : "mémoire inconnue"}
        {m.vram_go ? ` · ${m.carte ?? "carte graphique"} (${String(m.vram_go)} Go)` : " · pas de carte graphique adaptée détectée"}
      </p>
      <ul className="materiel-liste">
        {m.recommandations.map((r) => (
          <li key={r.taille}>
            <b>{r.taille}</b> sur {r.ou} — {r.raison} (ex. {r.exemples.join(", ")})
          </li>
        ))}
      </ul>
    </div>
  );
}

export function VueConnecteurs({ surChangement, familles }: { surChangement: (message?: string) => void; familles?: Connecteur["famille"][] }) {
  const [liste, setListe] = useState<Connecteur[] | null>(null);
  const [materiel, setMateriel] = useState<Materiel | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  const charger = useCallback(() => {
    listerConnecteurs()
      .then((r) => {
        setListe(r.connecteurs);
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Lecture impossible.");
      });
  }, []);

  useEffect(() => {
    charger();
    lireMateriel()
      .then(setMateriel)
      .catch(() => {
        setMateriel(null);
      });
  }, [charger]);

  const apres = (message?: string) => {
    surChangement(message);
    charger();
  };

  if (erreur) return <p className="securite-erreur">{erreur}</p>;
  if (!liste) {
    return (
      <div className="connecteurs" aria-busy="true">
        <div className="squelette" />
        <div className="squelette" />
      </div>
    );
  }
  return (
    <div className="connecteurs">
      {FAMILLES.filter((f) => !familles || familles.includes(f.id)).map((f) => (
        <section key={f.id} className="famille-co" aria-labelledby={`famille-${f.id}`}>
          <h3 className="sec-titre" id={`famille-${f.id}`}>
            {f.titre}
          </h3>
          <p className="sec-texte">{f.texte}</p>
          {f.id === "local" && materiel && <Recommandations m={materiel} />}
          <ul className="cartes-co">
            {liste
              .filter((c) => c.famille === f.id)
              .map((c) => (
                <Carte key={c.id} c={c} surChangement={apres} />
              ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
