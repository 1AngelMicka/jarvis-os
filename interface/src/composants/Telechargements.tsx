import { useCallback, useEffect, useState } from "react";

import { lancerTelechargement, lireTelechargements } from "../api";
import type { Telechargement } from "../types";

const MO = 1_000_000;

function taille(octets: number): string {
  return octets >= MO ? `${(octets / MO).toLocaleString("fr-FR", { maximumFractionDigits: 0 })} Mo` : `${(octets / 1000).toFixed(0)} ko`;
}

const TONS: Record<Telechargement["statut"], { texte: string; ton?: string }> = {
  absent: { texte: "À télécharger", ton: "attention" },
  en_cours: { texte: "En cours" },
  interrompu: { texte: "Interrompu", ton: "attention" },
  pret: { texte: "Prêt", ton: "ok" },
  echoue: { texte: "Échoué", ton: "risque" },
};

function detail(t: Telechargement): string {
  if (t.statut === "en_cours") {
    const part = t.total ? `${taille(t.octets)} sur ${taille(t.total)}` : taille(t.octets);
    return `${part}${t.essai && t.essai > 1 ? ` · essai ${String(t.essai)} sur 3` : ""}`;
  }
  if (t.statut === "interrompu") return `Arrêté à ${taille(t.octets)} : la reprise repart de là.`;
  if (t.statut === "echoue") return `Après ${String(t.essai ?? 3)} essais : ${t.raison ?? "raison inconnue"}.`;
  if (t.statut === "pret") return t.octets ? `${taille(t.octets)} dans le dossier des données.` : "Dans le dossier des données.";
  return "Depuis Hugging Face, une seule fois, dans le dossier des données. Rien ne part sans votre accord.";
}

/** Gros téléchargements des modèles choisis (embeddings, voix) : progression, accord explicite, réessayer. */
export function Telechargements({ ids, surMessage }: { ids?: string[]; surMessage?: (m: string) => void }) {
  const [liste, setListe] = useState<Telechargement[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [occupe, setOccupe] = useState<string | null>(null);

  const charger = useCallback(() => {
    lireTelechargements()
      .then((r) => {
        setListe(r.telechargements);
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Lecture impossible.");
      });
  }, []);
  useEffect(charger, [charger]);

  const enCours = liste?.some((t) => t.statut === "en_cours") ?? false;
  useEffect(() => {
    if (!enCours) return;
    const minuterie = window.setInterval(charger, 2000);
    return () => {
      window.clearInterval(minuterie);
    };
  }, [enCours, charger]);

  const lancer = (t: Telechargement) => {
    setOccupe(t.id);
    setErreur(null);
    lancerTelechargement(t.id)
      .then((r) => {
        setListe(r.telechargements);
        surMessage?.(`Téléchargement de ${t.nom} lancé en arrière-plan.`);
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Lancement impossible.");
      })
      .finally(() => {
        setOccupe(null);
      });
  };

  const visibles = liste?.filter((t) => !ids || ids.includes(t.id)) ?? [];
  if (!liste) return erreur ? <p className="securite-erreur">{erreur}</p> : null;
  return (
    <>
      {erreur && (
        <p className="securite-erreur" role="alert">
          {erreur}
        </p>
      )}
      <ul className="cartes-co">
        {visibles.map((t) => {
          const pourcent = t.total ? Math.min(100, Math.floor((t.octets * 100) / t.total)) : null;
          return (
            <li key={t.id} className="carte-co">
              <div className="carte-co-tete">
                <h4 className="carte-co-nom">{t.titre}</h4>
                <span className="badge-co" data-ton={TONS[t.statut].ton}>
                  {TONS[t.statut].texte}
                  {pourcent !== null && t.statut === "en_cours" ? ` · ${String(pourcent)} %` : ""}
                </span>
              </div>
              <p className="carte-co-detail">
                <code>{t.nom}</code> · {detail(t)}
              </p>
              {t.statut === "en_cours" && (
                <div
                  className="progression"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={pourcent ?? undefined}
                  aria-label={`Téléchargement de ${t.nom}`}
                >
                  <span style={{ width: `${String(pourcent ?? 0)}%` }} />
                </div>
              )}
              {t.statut !== "pret" && t.statut !== "en_cours" && (
                <div className="carte-co-actions">
                  <button
                    type="button"
                    className="btn btn-mini"
                    disabled={occupe !== null}
                    onClick={() => {
                      lancer(t);
                    }}
                  >
                    {occupe === t.id ? "Lancement…" : t.statut === "absent" ? "Télécharger" : t.statut === "interrompu" ? "Reprendre" : "Réessayer"}
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </>
  );
}
