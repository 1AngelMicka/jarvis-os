import { useCallback, useEffect, useState } from "react";

import { lireVeille, reglerVeille } from "../api";
import type { EtatSessionClaude, EtatVeille, ReglagesVeille } from "../types";
import { demanderPermissionNotifications, signalerVeille } from "../veilleClaude";

const TONS: Record<EtatSessionClaude, string | undefined> = {
  travaille: "attention",
  vous_attend: "ok",
  permission: "risque",
  bloquee: "risque",
  inconnu: undefined,
};
const HEURE = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });

/** Veille des sessions Claude Code de l'utilisateur : lecture seule, désactivée par défaut. */
export function VeilleClaude() {
  const [veille, setVeille] = useState<EtatVeille | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [permission, setPermission] = useState<string>(() => ("Notification" in window ? Notification.permission : "indisponible"));

  const charger = useCallback(() => {
    lireVeille(Number.MAX_SAFE_INTEGER)
      .then((v) => {
        setErreur(null);
        setVeille(v);
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Veille illisible.");
      });
  }, []);
  useEffect(charger, [charger]);
  const actif = veille?.reglages.actif ?? false;
  useEffect(() => {
    if (!actif) return;
    const minuterie = window.setInterval(charger, 5000);
    return () => {
      window.clearInterval(minuterie);
    };
  }, [actif, charger]);

  const regler = (r: Partial<ReglagesVeille>) => {
    reglerVeille(r)
      .then(() => {
        signalerVeille();
        charger();
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Réglage impossible.");
      });
  };

  if (!veille) return erreur ? <p className="securite-erreur">{erreur}</p> : <div className="squelette squelette--ligne" />;
  const { reglages } = veille;
  return (
    <div className="veille-claude">
      <p className="sec-texte">
        JARVIS regarde, sans jamais y écrire, si vos sessions Claude Code (terminal, application de bureau) travaillent, vous attendent ou
        attendent une permission, et vous prévient. Il ne lit que leur état : ni leurs conversations, ni vos jetons ou identifiants.
      </p>
      <div className="veille-reglages">
        <label className="carte-co-case carte-co-case--ligne">
          <input
            type="checkbox"
            checked={reglages.actif}
            onChange={(e) => {
              regler({ actif: e.target.checked });
            }}
          />
          <span>Veiller sur mes sessions Claude Code</span>
        </label>
        <label className="carte-co-case carte-co-case--ligne">
          <input
            type="checkbox"
            checked={reglages.voix}
            disabled={!reglages.actif}
            onChange={(e) => {
              regler({ voix: e.target.checked });
            }}
          />
          <span>M'alerter à voix haute</span>
        </label>
        <label className="carte-co-case carte-co-case--ligne">
          <input
            type="checkbox"
            checked={reglages.notification}
            disabled={!reglages.actif}
            onChange={(e) => {
              regler({ notification: e.target.checked });
              if (e.target.checked)
                void demanderPermissionNotifications().then((p) => {
                  setPermission(p);
                });
            }}
          />
          <span>Notification sur cet appareil (téléphone compris) quand JARVIS n'est pas à l'écran</span>
        </label>
      </div>
      {reglages.actif && reglages.notification && permission === "default" && (
        <button
          type="button"
          className="btn btn-discret btn-mini veille-permission"
          onClick={() => {
            void demanderPermissionNotifications().then((p) => {
              setPermission(p);
            });
          }}
        >
          Autoriser les notifications sur cet appareil
        </button>
      )}
      {reglages.actif && reglages.notification && permission === "denied" && (
        <p className="sec-texte">Les notifications sont refusées par ce navigateur : l'alerte s'affiche seulement dans JARVIS.</p>
      )}
      {erreur && <p className="carte-co-message">{erreur}</p>}
      {reglages.actif && !veille.disponible && (
        <p className="sec-texte">Aucun dossier de sessions Claude Code sur ce PC : Claude Code n'a pas encore été lancé ici.</p>
      )}
      {reglages.actif && veille.disponible && veille.sessions.length === 0 && (
        <p className="sec-texte">Aucune session Claude Code ouverte en ce moment.</p>
      )}
      {reglages.actif && veille.sessions.length > 0 && (
        <ul className="cartes-co" aria-label="Sessions Claude Code ouvertes">
          {veille.sessions.map((s) => (
            <li key={s.id} className="carte-co">
              <div className="carte-co-tete">
                <h4 className="carte-co-nom">{s.nom}</h4>
                <span className="badge-co">{s.projet}</span>
                <span className="badge-co" data-ton={TONS[s.etat]}>
                  {s.libelle}
                </span>
              </div>
              {(s.detail ?? s.depuis) && (
                <p className="carte-co-detail">
                  {s.detail}
                  {s.detail && s.depuis ? " · " : ""}
                  {s.depuis ? `depuis ${HEURE.format(new Date(s.depuis))}` : ""}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
