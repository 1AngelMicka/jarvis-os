import { useCallback, useEffect, useRef, useState } from "react";

import {
  activerHomeAssistant,
  ajouterProfil,
  ajouterSatellite,
  configurerHomeAssistant,
  connecterHomeAssistant,
  inscrireVoixProfil,
  lireHomeAssistant,
  lireWyoming,
  listerPieces,
  listerProfils,
  listerSatellites,
  modifierSatellite,
  oublierHomeAssistant,
  reglerWyoming,
  retirerProfil,
  retirerSatellite,
  testerHomeAssistant,
} from "../api";
import { NIVEAUX_MAISON, adresseHomeAssistantPlausible, adresseWyoming, lireClients, presence, statutHomeAssistant, transportHomeAssistant } from "../maison";
import type { CarteHomeAssistant, EtatWyoming, PieceMaison, ProfilVoix, Satellite } from "../types";
import { Enregistreur } from "../voix";

import "../styles/maison.css";

const DUREE_VOIX = 6000;
const VOLUMES = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100] as const;

function message(e: unknown, defaut: string): string {
  return e instanceof Error ? e.message : defaut;
}

/** Un geste à la fois par carte : message de résultat, bouton désactivé pendant l'appel. */
function useGeste(surFin: () => void) {
  const [texte, setTexte] = useState<string | null>(null);
  const [occupe, setOccupe] = useState(false);
  const agir = (appel: () => Promise<unknown>, ok?: string) => {
    setOccupe(true);
    setTexte(null);
    appel()
      .then(() => {
        if (ok) setTexte(ok);
        surFin();
      })
      .catch((e: unknown) => {
        setTexte(message(e, "Échec."));
      })
      .finally(() => {
        setOccupe(false);
      });
  };
  return { texte, setTexte, occupe, agir };
}

function Message({ texte }: { texte: string | null }) {
  return texte ? (
    <p className="carte-co-message" role="status">
      {texte}
    </p>
  ) : null;
}

// --- Home Assistant ----------------------------------------------------------------------------------------------

function CarteHA({ c, surChangement }: { c: CarteHomeAssistant; surChangement: (m?: string) => void }) {
  const { texte, setTexte, occupe, agir } = useGeste(() => {
    surChangement();
  });
  const [adresse, setAdresse] = useState(c.adresse ?? "");
  const [jeton, setJeton] = useState("");
  const [code, setCode] = useState("");
  const statut = statutHomeAssistant(c);
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
      <p className="carte-co-detail">Liaison : {transportHomeAssistant(c)}.</p>
      {!c.actif && (
        <>
          <form
            className="carte-co-cle"
            onSubmit={(e) => {
              e.preventDefault();
              agir(() => configurerHomeAssistant({ adresse: adresse.trim() }), "Adresse enregistrée.");
            }}
          >
            <label className="visuellement-cache" htmlFor="maison-ha-adresse">
              Adresse de Home Assistant
            </label>
            <input
              id="maison-ha-adresse"
              autoComplete="off"
              spellCheck={false}
              placeholder="http://homeassistant.local:8123"
              value={adresse}
              onChange={(e) => {
                setAdresse(e.target.value);
              }}
            />
            <button type="submit" className="btn btn-mini" disabled={occupe || !adresseHomeAssistantPlausible(adresse)}>
              Enregistrer
            </button>
          </form>
          <div className="carte-co-actions" role="group" aria-label="Liaison avec Home Assistant">
            <button
              type="button"
              className="btn btn-mini"
              disabled={occupe || !c.adresse}
              title={c.adresse ? undefined : "Enregistrez d'abord l'adresse"}
              onClick={() => {
                agir(async () => {
                  const r = await connecterHomeAssistant();
                  window.open(r.url, "_blank", "noopener,noreferrer");
                  setTexte("Acceptez dans la page de Home Assistant qui vient de s'ouvrir, puis revenez ici.");
                });
              }}
            >
              Connecter (serveur MCP)
            </button>
            <div className="segment" role="radiogroup" aria-label="Transport">
              {(["mcp", "rest"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  role="radio"
                  aria-checked={c.mode === m}
                  className="segment-btn"
                  disabled={occupe}
                  onClick={() => {
                    agir(() => configurerHomeAssistant({ mode: m }));
                  }}
                >
                  {m === "mcp" ? "MCP d'abord" : "REST seulement"}
                </button>
              ))}
            </div>
          </div>
          <form
            className="carte-co-cle"
            onSubmit={(e) => {
              e.preventDefault();
              const valeur = jeton;
              setJeton("");
              agir(() => configurerHomeAssistant({ jeton: valeur }), valeur ? "Jeton rangé dans le coffre de ce PC." : "Jeton retiré.");
            }}
          >
            <label className="visuellement-cache" htmlFor="maison-ha-jeton">
              Jeton d'accès longue durée de Home Assistant (repli REST)
            </label>
            <input
              id="maison-ha-jeton"
              type="password"
              autoComplete="off"
              value={jeton}
              placeholder={c.jeton_rest ? "Jeton enregistré (repli REST)" : "Jeton longue durée (repli REST, facultatif)"}
              onChange={(e) => {
                setJeton(e.target.value);
              }}
            />
            <button type="submit" className="btn btn-discret btn-mini" disabled={occupe || (!jeton && !c.jeton_rest)}>
              {jeton || !c.jeton_rest ? "Ranger" : "Retirer"}
            </button>
          </form>
          <form
            className="carte-co-cle"
            onSubmit={(e) => {
              e.preventDefault();
              const valeur = code;
              setCode("");
              agir(() => configurerHomeAssistant({ code_alarme: valeur }), valeur ? "Code de l'alarme rangé dans le coffre." : "Code retiré.");
            }}
          >
            <label className="visuellement-cache" htmlFor="maison-ha-code">
              Code de l'alarme (facultatif)
            </label>
            <input
              id="maison-ha-code"
              type="password"
              inputMode="numeric"
              autoComplete="off"
              value={code}
              placeholder={c.code_alarme ? "Code de l'alarme enregistré" : "Code de l'alarme (facultatif)"}
              onChange={(e) => {
                setCode(e.target.value);
              }}
            />
            <button type="submit" className="btn btn-discret btn-mini" disabled={occupe || (!code && !c.code_alarme)}>
              {code || !c.code_alarme ? "Ranger" : "Retirer"}
            </button>
          </form>
        </>
      )}
      <ul className="carte-co-detail carte-co-outils" aria-label="Commandes Home Assistant">
        {c.outils.map((o) => (
          <li key={o.nom}>
            {NIVEAUX_MAISON[o.niveau]} {o.description}
          </li>
        ))}
      </ul>
      <Message texte={texte} />
      <div className="carte-co-actions">
        {c.pret && (
          <button
            type="button"
            className="btn btn-discret btn-mini"
            disabled={occupe || !c.actif}
            title={c.actif ? undefined : "Activez d'abord le connecteur"}
            onClick={() => {
              agir(async () => {
                const r = await testerHomeAssistant();
                setTexte(r.disponible ? `OK : ${r.detail}.` : `Indisponible : ${r.detail}.`);
              });
            }}
          >
            Tester
          </button>
        )}
        {(c.pret || c.adresse) && (
          <button
            type="button"
            className="btn btn-discret btn-mini"
            disabled={occupe}
            onClick={() => {
              agir(() => oublierHomeAssistant(), "Home Assistant oublié : jetons et code retirés du coffre.");
            }}
          >
            Oublier
          </button>
        )}
        {c.pret && (
          <button
            type="button"
            className={c.actif ? "btn btn-discret btn-mini" : "btn btn-mini"}
            disabled={occupe}
            onClick={() => {
              agir(() => activerHomeAssistant(!c.actif), c.actif ? "Home Assistant désactivé." : "Home Assistant activé.");
            }}
          >
            {c.actif ? "Désactiver" : "Activer"}
          </button>
        )}
      </div>
    </li>
  );
}

// --- Wyoming -------------------------------------------------------------------------------------------------------

function CarteWyoming({ w, surChangement }: { w: EtatWyoming; surChangement: () => void }) {
  const { texte, occupe, agir } = useGeste(surChangement);
  const [clients, setClients] = useState(w.clients.join(", "));
  const reseau = w.hote !== "127.0.0.1";
  return (
    <li className="carte-co" data-statut={w.en_ecoute ? "disponible" : "desactive"}>
      <div className="carte-co-tete">
        <h4 className="carte-co-nom">Voix pour la maison (Wyoming)</h4>
        <span className="badge-co" data-ton={w.en_ecoute ? "ok" : "neutre"}>
          {w.en_ecoute ? "À l'écoute" : w.actif ? "Arrêté" : "Désactivé"}
        </span>
      </div>
      <p className="carte-co-detail">
        La transcription et la voix de JARVIS, offertes à Home Assistant (intégration Wyoming) et à vos satellites. Seul l'audio d'après le mot
        d'éveil arrive ici ; rien n'est gardé.
      </p>
      {w.actif && <p className="carte-co-detail maison-mono">Adresse à donner : {adresseWyoming(w)}</p>}
      <label className="carte-co-case carte-co-case--ligne">
        <input
          type="checkbox"
          checked={reseau}
          disabled={occupe}
          onChange={(e) => {
            agir(() => reglerWyoming({ hote: e.target.checked ? "0.0.0.0" : "127.0.0.1" }));
          }}
        />
        Écouter aussi le réseau local (sinon ce PC seulement)
      </label>
      <form
        className="carte-co-cle"
        onSubmit={(e) => {
          e.preventDefault();
          agir(() => reglerWyoming({ clients: lireClients(clients) }), "Clients autorisés enregistrés.");
        }}
      >
        <label className="visuellement-cache" htmlFor="maison-wy-clients">
          Adresses de Home Assistant autorisées
        </label>
        <input
          id="maison-wy-clients"
          autoComplete="off"
          spellCheck={false}
          inputMode="decimal"
          placeholder="Adresse IP de Home Assistant (ex. 192.168.1.30)"
          value={clients}
          onChange={(e) => {
            setClients(e.target.value);
          }}
        />
        <button type="submit" className="btn btn-discret btn-mini" disabled={occupe}>
          Autoriser
        </button>
      </form>
      <Message texte={texte} />
      <div className="carte-co-actions">
        <button
          type="button"
          className={w.actif ? "btn btn-discret btn-mini" : "btn btn-mini"}
          disabled={occupe}
          onClick={() => {
            agir(() => reglerWyoming({ actif: !w.actif }), w.actif ? "Serveur Wyoming coupé." : "Serveur Wyoming démarré.");
          }}
        >
          {w.actif ? "Couper" : "Démarrer"}
        </button>
      </div>
    </li>
  );
}

// --- Satellites et pièces ------------------------------------------------------------------------------------------

function CarteSatellites({
  satellites,
  connectes,
  pieces,
  surChangement,
}: {
  satellites: Satellite[];
  connectes: string[];
  pieces: PieceMaison[];
  surChangement: () => void;
}) {
  const { texte, occupe, agir } = useGeste(surChangement);
  const [nom, setNom] = useState("");
  const [piece, setPiece] = useState("");
  const [cle, setCle] = useState<{ id: string; cle: string } | null>(null);
  return (
    <li className="carte-co carte-co--large">
      <div className="carte-co-tete">
        <h4 className="carte-co-nom">Satellites et pièces</h4>
        <span className="badge-co" data-ton={connectes.length ? "ok" : "neutre"}>
          {connectes.length} connecté{connectes.length > 1 ? "s" : ""}
        </span>
      </div>
      <p className="carte-co-detail">
        Home Assistant Voice, ESP32-S3 sous ESPHome… Une clé par appareil, une pièce, un plafond de volume. Le satellite détecte lui-même le mot
        d'éveil ; un minuteur sonne sur le satellite qui l'a lancé.
      </p>
      {satellites.length > 0 && (
        <ul className="maison-liste" aria-label="Satellites">
          {satellites.map((s) => (
            <li key={s.id} className="maison-ligne">
              <span className="maison-ligne-nom">
                {s.nom}
                <span className="maison-ligne-sous">
                  {s.piece} · {connectes.includes(s.id) ? "connecté" : s.actif ? "hors ligne" : "coupé"}
                </span>
              </span>
              <label className="maison-volume">
                <span className="visuellement-cache">Plafond de volume de {s.nom}</span>
                <select
                  className="select"
                  value={s.volume_max}
                  disabled={occupe}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    agir(() => modifierSatellite(s.id, { volume_max: v }), `Volume de ${s.nom} : ${String(v)} % au plus.`);
                  }}
                >
                  {VOLUMES.map((v) => (
                    <option key={v} value={v}>
                      {v} % au plus
                    </option>
                  ))}
                </select>
              </label>
              <span className="maison-ligne-actions">
                <button
                  type="button"
                  className="btn btn-discret btn-mini"
                  disabled={occupe}
                  onClick={() => {
                    agir(() => modifierSatellite(s.id, { actif: !s.actif }));
                  }}
                >
                  {s.actif ? "Couper" : "Rétablir"}
                </button>
                <button
                  type="button"
                  className="btn btn-discret btn-mini"
                  disabled={occupe}
                  onClick={() => {
                    agir(() => retirerSatellite(s.id), `${s.nom} retiré : sa clé ne sert plus.`);
                  }}
                >
                  Retirer
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {cle && (
        <div className="maison-cle" role="alert">
          <p className="carte-co-detail">Clé du satellite, montrée une seule fois : recopiez-la dans l'appareil.</p>
          <code className="maison-mono">{cle.id}</code>
          <code className="maison-mono maison-cle-valeur">{cle.cle}</code>
          <button
            type="button"
            className="btn btn-discret btn-mini"
            onClick={() => {
              void navigator.clipboard.writeText(cle.cle).catch(() => undefined);
            }}
          >
            Copier la clé
          </button>
        </div>
      )}
      <form
        className="carte-co-cle"
        onSubmit={(e) => {
          e.preventDefault();
          agir(async () => {
            const r = await ajouterSatellite(nom.trim(), piece.trim(), 70);
            setCle({ id: r.satellite.id, cle: r.cle });
            setNom("");
          });
        }}
      >
        <label className="visuellement-cache" htmlFor="maison-sat-nom">
          Nom du satellite
        </label>
        <input
          id="maison-sat-nom"
          autoComplete="off"
          placeholder="Nom (ex. Voix du salon)"
          value={nom}
          maxLength={60}
          onChange={(e) => {
            setNom(e.target.value);
          }}
        />
        <label className="visuellement-cache" htmlFor="maison-sat-piece">
          Pièce du satellite
        </label>
        <input
          id="maison-sat-piece"
          autoComplete="off"
          placeholder="Pièce (ex. Salon)"
          value={piece}
          maxLength={60}
          onChange={(e) => {
            setPiece(e.target.value);
          }}
        />
        <button type="submit" className="btn btn-mini" disabled={occupe || !nom.trim() || !piece.trim()}>
          Ajouter
        </button>
      </form>
      {pieces.length > 0 && (
        <ul className="maison-liste" aria-label="Présence par pièce">
          {pieces.map((p) => (
            <li key={p.piece} className="maison-ligne">
              <span className="maison-ligne-nom">
                {p.piece}
                <span className="maison-ligne-sous">{presence(p)}</span>
              </span>
              <span className="badge-co" data-ton={p.occupee ? "ok" : "neutre"}>
                {p.occupee ? "Occupée" : "Calme"}
              </span>
            </li>
          ))}
        </ul>
      )}
      <Message texte={texte} />
    </li>
  );
}

// --- Profils ---------------------------------------------------------------------------------------------------------

function CarteProfils({
  profils,
  reconnaissance,
  surChangement,
}: {
  profils: ProfilVoix[];
  reconnaissance: { actif: boolean; disponible: boolean };
  surChangement: () => void;
}) {
  const { texte, setTexte, occupe, agir } = useGeste(surChangement);
  const [nom, setNom] = useState("");
  const [ecoute, setEcoute] = useState<string | null>(null);
  const minuterie = useRef<number | undefined>(undefined);
  useEffect(
    () => () => {
      window.clearTimeout(minuterie.current);
    },
    [],
  );
  const micro = "mediaDevices" in navigator && typeof MediaRecorder !== "undefined";
  const enregistrer = (p: ProfilVoix) => {
    const rec = new Enregistreur();
    rec
      .demarrer()
      .then(() => {
        setEcoute(p.id);
        setTexte(`${p.nom} : parlez pendant 6 secondes…`);
        minuterie.current = window.setTimeout(() => {
          void rec.arreter().then((audio) => {
            setEcoute(null);
            agir(() => inscrireVoixProfil(p.id, audio), `Voix de ${p.nom} enregistrée sur ce PC.`);
          });
        }, DUREE_VOIX);
      })
      .catch(() => {
        setTexte("Micro refusé ou indisponible.");
      });
  };
  return (
    <li className="carte-co carte-co--large">
      <div className="carte-co-tete">
        <h4 className="carte-co-nom">Profils par personne</h4>
        <span className="badge-co" data-ton={reconnaissance.actif && reconnaissance.disponible ? "ok" : "neutre"}>
          {reconnaissance.actif ? (reconnaissance.disponible ? "Voix reconnues" : "Reconnaissance indisponible") : "Reconnaissance coupée"}
        </span>
      </div>
      <p className="carte-co-detail">
        Les autres voix de la maison, reconnues par les satellites (présence, plafond de volume). Un profil n'est jamais vous : serrures, alarme
        et portail demandent toujours votre voix et votre clé d'accès. Empreintes calculées et gardées sur ce PC.
      </p>
      {profils.length > 0 && (
        <ul className="maison-liste" aria-label="Profils">
          {profils.map((p) => (
            <li key={p.id} className="maison-ligne">
              <span className="maison-ligne-nom">
                {p.nom}
                <span className="maison-ligne-sous">
                  {p.empreintes} empreinte{p.empreintes > 1 ? "s" : ""} · volume {p.volume_max} % au plus
                </span>
              </span>
              <span className="maison-ligne-actions">
                <button
                  type="button"
                  className="btn btn-discret btn-mini"
                  disabled={occupe || ecoute !== null || !micro || !reconnaissance.disponible}
                  title={reconnaissance.disponible ? undefined : "Activez d'abord la reconnaissance du propriétaire (Voix & écoute)"}
                  onClick={() => {
                    enregistrer(p);
                  }}
                >
                  {ecoute === p.id ? "J'écoute…" : "Enregistrer sa voix"}
                </button>
                <button
                  type="button"
                  className="btn btn-discret btn-mini"
                  disabled={occupe || ecoute !== null}
                  onClick={() => {
                    agir(() => retirerProfil(p.id), `Profil ${p.nom} et ses empreintes retirés.`);
                  }}
                >
                  Retirer
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      <form
        className="carte-co-cle"
        onSubmit={(e) => {
          e.preventDefault();
          agir(() => ajouterProfil(nom.trim(), 100), "Profil ajouté.");
          setNom("");
        }}
      >
        <label className="visuellement-cache" htmlFor="maison-profil-nom">
          Nom de la personne
        </label>
        <input
          id="maison-profil-nom"
          autoComplete="off"
          placeholder="Prénom de la personne"
          value={nom}
          maxLength={60}
          onChange={(e) => {
            setNom(e.target.value);
          }}
        />
        <button type="submit" className="btn btn-mini" disabled={occupe || !nom.trim()}>
          Ajouter
        </button>
      </form>
      <Message texte={texte} />
    </li>
  );
}

/** Home Assistant (le PC reste le cerveau), voix Wyoming, satellites, pièces et profils. */
export function SectionHomeAssistant({ surChangement }: { surChangement: (message?: string) => void }) {
  const [ha, setHa] = useState<CarteHomeAssistant | null>(null);
  const [wy, setWy] = useState<EtatWyoming | null>(null);
  const [sat, setSat] = useState<{ satellites: Satellite[]; connectes: string[] }>({ satellites: [], connectes: [] });
  const [pieces, setPieces] = useState<PieceMaison[]>([]);
  const [profils, setProfils] = useState<{ profils: ProfilVoix[]; reconnaissance: { actif: boolean; disponible: boolean } } | null>(null);
  const charger = useCallback(() => {
    void Promise.allSettled([lireHomeAssistant(), lireWyoming(), listerSatellites(), listerPieces(), listerProfils()]).then(([a, b, c, d, e]) => {
      if (a.status === "fulfilled") setHa(a.value);
      if (b.status === "fulfilled") setWy(b.value);
      if (c.status === "fulfilled") setSat(c.value);
      if (d.status === "fulfilled") setPieces(d.value.pieces);
      if (e.status === "fulfilled") setProfils(e.value);
    });
  }, []);
  useEffect(() => {
    charger();
  }, [charger]);
  if (!ha) return null;
  return (
    <>
      <CarteHA
        key={`${ha.adresse ?? ""}-${String(ha.actif)}`}
        c={ha}
        surChangement={(m) => {
          surChangement(m);
          charger();
        }}
      />
      {wy && <CarteWyoming key={wy.clients.join(",")} w={wy} surChangement={charger} />}
      <CarteSatellites satellites={sat.satellites} connectes={sat.connectes} pieces={pieces} surChangement={charger} />
      {profils && <CarteProfils profils={profils.profils} reconnaissance={profils.reconnaissance} surChangement={charger} />}
    </>
  );
}
