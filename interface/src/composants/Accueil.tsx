import { useCallback, useEffect, useRef, useState } from "react";

import { creerJumelage, lireDiagnostic, lireTailscale, reparer, terminerAccueil } from "../api";
import type { EtatTailscale, Jumelage, Verification } from "../types";
import { VueConnecteurs } from "./Connecteurs";

const ETAPES = [
  { id: "verifications", nom: "Vérifications" },
  { id: "cerveau", nom: "Cerveau" },
  { id: "telephone", nom: "Téléphone" },
  { id: "pret", nom: "Prêt" },
] as const;
type Etape = (typeof ETAPES)[number]["id"];

const TONS: Record<Verification["statut"], { ok: boolean | undefined; texte: string }> = {
  ok: { ok: true, texte: "OK" },
  info: { ok: undefined, texte: "Info" },
  attention: { ok: false, texte: "À faire" },
  erreur: { ok: false, texte: "Erreur" },
};
const HEURE = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });

function Aide({ aide }: { aide: string }) {
  if (/^https:\/\//.test(aide)) {
    return (
      <a className="verif-aide" href={aide} target="_blank" rel="noopener noreferrer">
        Comment faire
      </a>
    );
  }
  if (/^(jarvis2|tailscale|cd |npm)\b/.test(aide)) return <code className="verif-commande">{aide}</code>;
  return <span className="verif-aide">{aide}</span>;
}

function Verifications({ surChangement }: { surChangement: (message?: string) => void }) {
  const [liste, setListe] = useState<Verification[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [occupe, setOccupe] = useState<string | null>(null);

  const charger = useCallback(() => {
    lireDiagnostic()
      .then((r) => {
        setListe(r.verifications);
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Diagnostic impossible.");
      });
  }, []);
  useEffect(charger, [charger]);

  // Téléchargement du modèle en cours : on relit l'état toutes les 3 s jusqu'à la fin
  const enCours = liste?.some((v) => v.id === "modele" && v.statut === "info") ?? false;
  useEffect(() => {
    if (!enCours) return;
    const minuterie = window.setInterval(charger, 3000);
    return () => {
      window.clearInterval(minuterie);
    };
  }, [enCours, charger]);

  const lancer = (reparation: string) => {
    setOccupe(reparation);
    setErreur(null);
    reparer(reparation)
      .then((r) => {
        setListe(r.verifications);
        surChangement();
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Réparation impossible.");
      })
      .finally(() => {
        setOccupe(null);
      });
  };

  if (!liste) return erreur ? <p className="securite-erreur">{erreur}</p> : <div className="squelette squelette--ligne" aria-busy="true" />;
  return (
    <>
      {erreur && (
        <p className="securite-erreur" role="alert">
          {erreur}
        </p>
      )}
      <ul className="verif-liste">
        {liste.map((v) => (
          <li key={v.id} className="verif" data-statut={v.statut}>
            <span className="point-etat" data-ok={TONS[v.statut].ok} aria-hidden="true" />
            <span className="verif-titre">{v.titre}</span>
            <span className="badge-co" data-ton={v.statut === "ok" ? "ok" : v.statut === "info" ? undefined : v.statut === "erreur" ? "risque" : "attention"}>
              {TONS[v.statut].texte}
            </span>
            <span className="verif-detail">{v.detail}</span>
            {(v.reparation ?? v.aide) && (
              <span className="verif-suite">
                {v.reparation && (
                  <button
                    type="button"
                    className="btn btn-mini"
                    disabled={occupe !== null}
                    onClick={() => {
                      lancer(v.reparation ?? "");
                    }}
                  >
                    {occupe === v.reparation ? "En cours…" : "Réparer"}
                  </button>
                )}
                {v.aide && <Aide aide={v.aide} />}
              </span>
            )}
          </li>
        ))}
      </ul>
      <button type="button" className="btn btn-discret btn-mini" onClick={charger}>
        Revérifier
      </button>
    </>
  );
}

function Telephone() {
  const [ts, setTs] = useState<EtatTailscale | null>(null);
  const [qr, setQr] = useState<Jumelage | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [lecture, setLecture] = useState(false);

  const relire = useCallback(() => {
    setLecture(true);
    lireTailscale()
      .then(setTs)
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Lecture impossible.");
      })
      .finally(() => {
        setLecture(false);
      });
  }, []);
  useEffect(relire, [relire]);

  const associer = () => {
    setErreur(null);
    creerJumelage("telephone")
      .then(setQr)
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Jumelage impossible.");
      });
  };

  return (
    <div className="sec-bloc">
      <p className="sec-texte">
        JARVIS n'écoute que sur ce PC. Pour l'utiliser depuis votre téléphone, même hors de chez vous, installez Tailscale sur le PC et sur le
        téléphone, avec le même compte : vos appareils se joignent par un réseau privé chiffré, sans ouvrir de port.
      </p>
      {erreur && (
        <p className="securite-erreur" role="alert">
          {erreur}
        </p>
      )}
      {!ts ? (
        <div className="squelette squelette--ligne" aria-busy="true" />
      ) : !ts.installe ? (
        <p className="sec-texte">
          Tailscale n'est pas installé sur ce PC.{" "}
          <a href={ts.aide} target="_blank" rel="noopener noreferrer">
            Télécharger Tailscale
          </a>
        </p>
      ) : !ts.connecte ? (
        <p className="sec-texte">
          Tailscale est installé mais pas connecté : ouvrez-le et connectez-vous, ou lancez <code className="verif-commande">tailscale up</code>.
        </p>
      ) : !ts.serve_actif ? (
        <p className="sec-texte">
          Tailscale est connecté ({ts.nom}). Publiez JARVIS sur votre réseau privé, une seule fois, dans un terminal du PC :{" "}
          <code className="verif-commande">{ts.commande}</code>
        </p>
      ) : (
        <p className="sec-texte" data-etat="ok">
          JARVIS est joignable depuis vos appareils : {ts.adresse}
        </p>
      )}
      <div className="carte-co-actions">
        <button type="button" className="btn btn-discret btn-mini" disabled={lecture} onClick={relire}>
          {lecture ? "Lecture…" : "Revérifier"}
        </button>
        <button type="button" className={ts?.serve_actif ? "btn btn-principal btn-mini" : "btn btn-mini"} onClick={associer}>
          Associer un téléphone
        </button>
      </div>
      {qr && (
        <div className="sec-qr">
          <img src={qr.qr} alt="QR de jumelage du téléphone" width={176} height={176} />
          <p className="sec-texte">
            Scannez ce code avec l'appareil photo du téléphone (une seule fois, avant {HEURE.format(new Date(qr.expire_le))}), puis « Ajouter à
            l'écran d'accueil » pour installer JARVIS comme une application.
            {!qr.tailscale && " Ce lien vise ce PC (localhost) : il ne fonctionnera sur le téléphone qu'une fois JARVIS publié par Tailscale."}
          </p>
        </div>
      )}
    </div>
  );
}

interface Props {
  surChangement: (message?: string) => void;
  surTermine: () => void;
}

/** Assistant de premier lancement : vérifications (avec réparations), cerveau, téléphone. */
export function VueAccueil({ surChangement, surTermine }: Props) {
  const [etape, setEtape] = useState<Etape>("verifications");
  const [occupe, setOccupe] = useState(false);
  const titre = useRef<HTMLHeadingElement>(null);
  const indice = ETAPES.findIndex((e) => e.id === etape);

  useEffect(() => {
    titre.current?.focus();
  }, [etape]);

  const aller = (pas: number) => {
    const suivante = ETAPES[indice + pas];
    if (suivante) setEtape(suivante.id);
  };

  const terminer = () => {
    setOccupe(true);
    terminerAccueil()
      .then(() => {
        surTermine();
      })
      .catch((e: unknown) => {
        surChangement(e instanceof Error ? e.message : "Impossible.");
      })
      .finally(() => {
        setOccupe(false);
      });
  };

  return (
    <div className="installation">
      <ol className="etapes" aria-label="Étapes de l'installation">
        {ETAPES.map((e, i) => (
          <li key={e.id} className="etape" aria-current={e.id === etape ? "step" : undefined} data-faite={i < indice || undefined}>
            <button
              type="button"
              className="etape-btn"
              onClick={() => {
                setEtape(e.id);
              }}
            >
              <span className="etape-num" aria-hidden="true">
                {i + 1}
              </span>
              {e.nom}
            </button>
          </li>
        ))}
      </ol>

      <section className="installation-corps" aria-labelledby="installation-titre">
        <h3 className="installation-titre" id="installation-titre" tabIndex={-1} ref={titre}>
          {etape === "verifications" && "Vérifions l'installation"}
          {etape === "cerveau" && "Choisissez vos IA"}
          {etape === "telephone" && "JARVIS sur votre téléphone"}
          {etape === "pret" && "Tout est prêt"}
        </h3>
        {etape === "verifications" && (
          <>
            <p className="sec-texte">Ce que JARVIS voit sur ce PC. Les points à faire se réparent d'un clic quand c'est sans risque.</p>
            <Verifications surChangement={surChangement} />
          </>
        )}
        {etape === "cerveau" && (
          <>
            <p className="sec-texte">
              Au moins une IA est nécessaire. Votre compte Claude passe par le programme officiel Claude Code ; une clé d'API ou un modèle local
              conviennent aussi. Tout se change plus tard dans Connecteurs.
            </p>
            <VueConnecteurs surChangement={surChangement} />
          </>
        )}
        {etape === "telephone" && <Telephone />}
        {etape === "pret" && (
          <p className="sec-texte">
            Parlez à JARVIS depuis le dialogue. Pour approuver les actions sensibles, enregistrez une clé d'accès (empreinte, visage ou code de
            l'appareil) dans l'onglet Sécurité. Ce diagnostic reste accessible depuis le panneau État.
          </p>
        )}
      </section>

      <div className="installation-nav">
        {indice > 0 && (
          <button
            type="button"
            className="btn btn-discret btn-mini"
            onClick={() => {
              aller(-1);
            }}
          >
            Précédent
          </button>
        )}
        {etape === "pret" ? (
          <button type="button" className="btn btn-principal" disabled={occupe} onClick={terminer}>
            Commencer
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-principal btn-mini"
            onClick={() => {
              aller(1);
            }}
          >
            {etape === "telephone" ? "Suivant (ou plus tard)" : "Suivant"}
          </button>
        )}
      </div>
    </div>
  );
}
