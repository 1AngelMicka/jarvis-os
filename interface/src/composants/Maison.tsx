import { useCallback, useEffect, useState } from "react";

import { activerMaison, appairerHue, configurerObs, decouvrirHue, listerMaison, oublierMaison, testerMaison } from "../api";
import type { ConnecteurMaison } from "../types";
import { SectionHomeAssistant } from "./MaisonHA";

const NIVEAUX = { vert: "🟢", jaune: "🟡", rouge: "🔴" } as const;

function useAction(surChangement: (message?: string) => void) {
  const [message, setMessage] = useState<string | null>(null);
  const [occupe, setOccupe] = useState(false);
  const agir = (appel: () => Promise<unknown>, ok?: string) => {
    setOccupe(true);
    setMessage(null);
    appel()
      .then(() => {
        if (ok) setMessage(ok);
        surChangement(ok);
      })
      .catch((e: unknown) => {
        setMessage(e instanceof Error ? e.message : "Échec.");
      })
      .finally(() => {
        setOccupe(false);
      });
  };
  return { message, setMessage, occupe, setOccupe, agir };
}

function ReglagesHue({ c, agir, occupe, setMessage }: { c: ConnecteurMaison; agir: ReturnType<typeof useAction>["agir"]; occupe: boolean; setMessage: (m: string | null) => void }) {
  const [adresse, setAdresse] = useState(c.adresse ?? "");
  const [enLigne, setEnLigne] = useState(false);
  const [ponts, setPonts] = useState<string[] | null>(null);
  return (
    <>
      <div className="carte-co-actions">
        <button
          type="button"
          className="btn btn-discret btn-mini"
          disabled={occupe}
          onClick={() => {
            agir(async () => {
              const r = await decouvrirHue(enLigne);
              setPonts(r.ponts);
              if (r.ponts.length === 1) setAdresse(r.ponts[0] ?? "");
              setMessage(r.ponts.length ? `${String(r.ponts.length)} pont(s) trouvé(s).` : "Aucun pont trouvé : saisissez son adresse.");
            });
          }}
        >
          Chercher le pont
        </button>
        <label className="carte-co-case carte-co-case--ligne">
          <input
            type="checkbox"
            checked={enLigne}
            onChange={(e) => {
              setEnLigne(e.target.checked);
            }}
          />
          Si besoin, demander au service en ligne de Philips
        </label>
      </div>
      {ponts && ponts.length > 1 && (
        <div className="carte-co-actions" role="group" aria-label="Ponts trouvés">
          {ponts.map((p) => (
            <button
              key={p}
              type="button"
              className="btn btn-discret btn-mini"
              aria-pressed={adresse === p}
              onClick={() => {
                setAdresse(p);
              }}
            >
              {p}
            </button>
          ))}
        </div>
      )}
      <form
        className="carte-co-cle"
        onSubmit={(e) => {
          e.preventDefault();
          agir(() => appairerHue(adresse.trim()), "Pont appairé : sa clé est dans le coffre de ce PC.");
        }}
      >
        <label className="visuellement-cache" htmlFor="maison-hue-adresse">
          Adresse du pont Hue
        </label>
        <input
          id="maison-hue-adresse"
          inputMode="decimal"
          autoComplete="off"
          spellCheck={false}
          placeholder="ex. 192.168.1.20"
          value={adresse}
          onChange={(e) => {
            setAdresse(e.target.value);
          }}
        />
        <button type="submit" className="btn btn-mini" disabled={occupe || adresse.trim().length < 7}>
          Appairer
        </button>
      </form>
      <p className="carte-co-detail">Appuyez d'abord sur le bouton rond du pont, puis sur « Appairer » dans les 30 secondes.</p>
    </>
  );
}

function ReglagesObs({ c, agir, occupe }: { c: ConnecteurMaison; agir: ReturnType<typeof useAction>["agir"]; occupe: boolean }) {
  const [adresse, setAdresse] = useState(c.adresse ?? "127.0.0.1:4455");
  const [motDePasse, setMotDePasse] = useState("");
  return (
    <form
      className="carte-co-cle"
      onSubmit={(e) => {
        e.preventDefault();
        const mdp = motDePasse;
        setMotDePasse("");
        agir(() => configurerObs(adresse.trim(), mdp || undefined), "Réglages d'OBS enregistrés.");
      }}
    >
      <label className="visuellement-cache" htmlFor="maison-obs-adresse">
        Adresse du serveur WebSocket d'OBS
      </label>
      <input
        id="maison-obs-adresse"
        autoComplete="off"
        spellCheck={false}
        placeholder="127.0.0.1:4455"
        value={adresse}
        onChange={(e) => {
          setAdresse(e.target.value);
        }}
      />
      <label className="visuellement-cache" htmlFor="maison-obs-mdp">
        Mot de passe du serveur WebSocket d'OBS
      </label>
      <input
        id="maison-obs-mdp"
        type="password"
        autoComplete="off"
        value={motDePasse}
        placeholder={c.secret_enregistre ? "Mot de passe enregistré" : "Mot de passe (facultatif)"}
        onChange={(e) => {
          setMotDePasse(e.target.value);
        }}
      />
      <button type="submit" className="btn btn-mini" disabled={occupe || adresse.trim().length < 3}>
        Enregistrer
      </button>
    </form>
  );
}

function CarteMaison({ c, surChangement }: { c: ConnecteurMaison; surChangement: (message?: string) => void }) {
  const { message, setMessage, occupe, setOccupe, agir } = useAction(surChangement);
  const pret = c.id === "hue" ? c.secret_enregistre && c.adresse !== null : c.adresse !== null;
  const statut = c.actif ? { texte: "Activé", ton: "ok" } : pret ? { texte: "Désactivé", ton: "neutre" } : { texte: "À configurer", ton: "neutre" };
  return (
    <li className="carte-co" data-statut={c.actif ? "disponible" : "desactive"}>
      <div className="carte-co-tete">
        <h4 className="carte-co-nom">{c.nom}</h4>
        <span className="badge-co" data-ton={statut.ton}>
          {statut.texte}
        </span>
      </div>
      <p className="carte-co-detail">
        {c.description}
        {c.adresse ? ` · ${c.adresse}` : ""}
      </p>
      {!c.actif && (c.id === "hue" ? <ReglagesHue c={c} agir={agir} occupe={occupe} setMessage={setMessage} /> : <ReglagesObs c={c} agir={agir} occupe={occupe} />)}
      {c.actif && (
        <ul className="carte-co-detail carte-co-outils" aria-label={`Commandes ${c.nom}`}>
          {c.outils.map((o) => (
            <li key={o.nom}>
              {NIVEAUX[o.niveau]} {o.description}
            </li>
          ))}
        </ul>
      )}
      {message && (
        <p className="carte-co-message" role="status">
          {message}
        </p>
      )}
      <div className="carte-co-actions">
        {pret && (
          <button
            type="button"
            className="btn btn-discret btn-mini"
            disabled={occupe || !c.actif}
            title={c.actif ? undefined : "Activez d'abord le connecteur"}
            onClick={() => {
              setOccupe(true);
              testerMaison(c.id)
                .then((r) => {
                  setMessage(r.disponible ? `OK : ${r.detail}.` : `Indisponible : ${r.detail}.`);
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
        {pret && (
          <button
            type="button"
            className="btn btn-discret btn-mini"
            disabled={occupe}
            onClick={() => {
              agir(() => oublierMaison(c.id), `${c.nom} oublié : secret retiré du coffre.`);
            }}
          >
            Oublier
          </button>
        )}
        {pret && (
          <button
            type="button"
            className={c.actif ? "btn btn-discret btn-mini" : "btn btn-mini"}
            disabled={occupe}
            onClick={() => {
              agir(() => activerMaison(c.id, !c.actif), c.actif ? `${c.nom} désactivé.` : `${c.nom} activé.`);
            }}
          >
            {c.actif ? "Désactiver" : "Activer"}
          </button>
        )}
      </div>
    </li>
  );
}

/** Connecteurs maison facultatifs : désactivés par défaut ; chaque commande passe par la file d'approbations. */
export function SectionMaison({ surChangement }: { surChangement: (message?: string) => void }) {
  const [liste, setListe] = useState<ConnecteurMaison[] | null>(null);
  const charger = useCallback(() => {
    listerMaison()
      .then((r) => {
        setListe(r.connecteurs);
      })
      .catch(() => {
        setListe(null);
      });
  }, []);
  useEffect(() => {
    charger();
  }, [charger]);
  if (!liste) return null;
  return (
    <section className="famille-co" aria-labelledby="famille-maison">
      <h3 className="sec-titre" id="famille-maison">
        Maison
      </h3>
      <p className="sec-texte">
        Facultatifs, sur le réseau local, et le PC reste le cerveau. Lire l'état est libre ; chaque commande attend votre accord ; démarrer un
        direct demande votre clé d'accès, et ouvrir une serrure, l'alarme ou le portail demande votre clé d'accès et votre voix.
      </p>
      <ul className="cartes-co">
        {liste.map((c) => (
          <CarteMaison
            key={c.id}
            c={c}
            surChangement={(m) => {
              surChangement(m);
              charger();
            }}
          />
        ))}
        <SectionHomeAssistant surChangement={surChangement} />
      </ul>
    </section>
  );
}
