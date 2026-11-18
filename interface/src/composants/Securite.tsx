import { useCallback, useEffect, useState } from "react";

import { creerJumelage, enregistrerCle, lireAudit, listerAppareils, optionsCle, revoquerAppareil } from "../api";
import type { Appareil, EntreeAudit } from "../types";
import { clesDisponibles, creerCle } from "../webauthn";

const DATE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const NIVEAU = { vert: "🟢", jaune: "🟡", rouge: "🔴" } as const;

type AppareilListe = Appareil & { courant: boolean; cles: number };

interface Props {
  nbCles: number;
  surChangement: (message?: string) => void;
}

export function PanneauSecurite({ nbCles, surChangement }: Props) {
  const [liste, setListe] = useState<AppareilListe[] | null>(null);
  const [audit, setAudit] = useState<{ entrees: EntreeAudit[]; rompue_a: number | null } | null>(null);
  const [qr, setQr] = useState<{ qr: string; url: string; expire_le: string; local: boolean } | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  const charger = useCallback(() => {
    Promise.all([listerAppareils(), lireAudit()])
      .then(([a, j]) => {
        setListe(a.appareils);
        setAudit(j);
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Lecture impossible.");
      });
  }, []);

  useEffect(charger, [charger]);

  const agir = (appel: () => Promise<unknown>, message: string) => {
    setErreur(null);
    appel()
      .then(() => {
        surChangement(message);
        charger();
      })
      .catch((e: unknown) => {
        const texte = e instanceof Error ? e.message : "Échec.";
        setErreur(texte.includes("NotAllowedError") ? "Opération annulée." : texte);
      });
  };

  const ajouterCle = () => {
    agir(async () => {
      if (!clesDisponibles()) throw new Error("Clés d'accès indisponibles ici : ouvrez JARVIS par http://localhost.");
      const options = await optionsCle();
      await enregistrerCle(await creerCle(options), "Clé de cet appareil");
    }, "Clé d'accès enregistrée.");
  };

  return (
    <div className="securite">
      {erreur && (
        <p className="securite-erreur" role="alert">
          {erreur}
        </p>
      )}

      <section className="sec-bloc" aria-labelledby="sec-cles">
        <h3 className="sec-titre" id="sec-cles">
          Clés d'accès
        </h3>
        <p className="sec-texte">
          {nbCles
            ? `${String(nbCles)} clé${nbCles > 1 ? "s" : ""} enregistrée${nbCles > 1 ? "s" : ""} : elles approuvent les actions 🔴.`
            : "Aucune clé : les actions 🔴 ne peuvent pas être approuvées. Enregistrez l'empreinte, le visage ou le code de cet appareil."}
        </p>
        <button type="button" className="btn btn-mini" onClick={ajouterCle}>
          Enregistrer une clé sur cet appareil
        </button>
      </section>

      <section className="sec-bloc" aria-labelledby="sec-appareils">
        <h3 className="sec-titre" id="sec-appareils">
          Appareils autorisés
        </h3>
        {!liste ? (
          <div className="squelette squelette--ligne" />
        ) : (
          <ul className="sec-liste">
            {liste.map((a) => (
              <li key={a.id} className="sec-appareil" data-revoque={a.revoque || undefined}>
                <span className="sec-appareil-nom">
                  {a.nom}
                  {a.courant && <span className="puce-courant">cet appareil</span>}
                </span>
                <span className="sec-appareil-meta">
                  {a.revoque ? "révoqué" : a.dernier_acces ? `vu ${DATE.format(new Date(a.dernier_acces))}` : "jamais vu"}
                  {a.cles ? ` · ${String(a.cles)} clé${a.cles > 1 ? "s" : ""}` : ""}
                </span>
                {!a.revoque && !a.courant && (
                  <button
                    type="button"
                    className="btn btn-discret btn-mini"
                    onClick={() => {
                      agir(() => revoquerAppareil(a.id), `Accès de « ${a.nom} » retiré.`);
                    }}
                  >
                    Révoquer
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        <button
          type="button"
          className="btn btn-mini"
          onClick={() => {
            creerJumelage("telephone")
              .then(setQr)
              .catch((e: unknown) => {
                setErreur(e instanceof Error ? e.message : "Jumelage impossible.");
              });
          }}
        >
          Associer un appareil
        </button>
        {qr && (
          <div className="sec-qr">
            <img src={qr.qr} alt="QR de jumelage" width={176} height={176} />
            <p className="sec-texte">
              Scannez ce code (valable jusqu'à {DATE.format(new Date(qr.expire_le))}, une seule fois).
              {qr.local && " Depuis un téléphone, ouvrez d'abord JARVIS par son adresse réseau (phase 6 : Tailscale)."}
            </p>
            <button
              type="button"
              className="btn btn-discret btn-mini"
              onClick={() => {
                setQr(null);
              }}
            >
              Fermer
            </button>
          </div>
        )}
      </section>

      <section className="sec-bloc" aria-labelledby="sec-audit">
        <h3 className="sec-titre" id="sec-audit">
          Journal d'audit
        </h3>
        {audit && (
          <p className="sec-texte" data-etat={audit.rompue_a === null ? "ok" : "alerte"}>
            {audit.rompue_a === null ? "Chaîne d'empreintes intacte." : `Altération détectée à l'entrée ${String(audit.rompue_a)} !`}
          </p>
        )}
        <ul className="sec-journal">
          {audit?.entrees.map((e) => (
            <li key={e.id}>
              <span className="sec-journal-heure">{DATE.format(new Date(e.horodatage))}</span>
              <span>
                {NIVEAU[e.niveau]} {e.action}
              </span>
              <span className="sec-journal-acteur">{e.acteur.replace(/^appareil:/, "")}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
