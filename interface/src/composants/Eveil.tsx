import { useCallback, useEffect, useState } from "react";

import {
  type EtatEveil,
  EVENEMENT_ECOUTE_FOND,
  lireEcouteFond,
  lireEveil,
  oublierAmbiance,
  reglerEcouteFond,
  reglerEveil,
  type ReglagesEveil as Reglages,
  telechargerModeleEveil,
} from "../eveil";

const RELANCES = [4, 6, 10] as const;

function Point({ ok }: { ok: boolean }) {
  return <span className="point-etat" data-ok={ok} aria-hidden="true" />;
}

/** Réglages de l'éveil « Dis Jarvis » : écoute en fond (cet appareil), relance, mémoire d'ambiance, openWakeWord. */
export function ReglagesEveil({ surNotifier }: { surNotifier: (message: string) => void }) {
  const [etat, setEtat] = useState<EtatEveil | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [fond, setFond] = useState(lireEcouteFond);
  const micro = "mediaDevices" in navigator && typeof MediaRecorder !== "undefined";

  const charger = useCallback(() => {
    lireEveil()
      .then((e) => {
        setErreur(null);
        setEtat(e);
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Réglages de l'éveil illisibles.");
      });
  }, []);
  useEffect(charger, [charger]);

  // L'écoute en fond peut être coupée ailleurs (bouton « Mains libres ») : la case suit
  useEffect(() => {
    const suivre = (e: Event) => {
      setFond((e as CustomEvent<unknown>).detail === true);
    };
    window.addEventListener(EVENEMENT_ECOUTE_FOND, suivre);
    return () => {
      window.removeEventListener(EVENEMENT_ECOUTE_FOND, suivre);
    };
  }, []);

  // Téléchargement du modèle d'éveil en cours : progression suivie
  const telecharge = etat?.telechargement.statut === "en_cours";
  useEffect(() => {
    if (!telecharge) return;
    const minuterie = window.setInterval(charger, 2000);
    return () => {
      window.clearInterval(minuterie);
    };
  }, [telecharge, charger]);

  const appliquer = (promesse: Promise<EtatEveil>) => {
    promesse
      .then((e) => {
        setErreur(null);
        setEtat(e);
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Réglage impossible.");
      });
  };
  const regler = (r: Partial<Reglages>) => {
    appliquer(reglerEveil(r));
  };

  if (!etat) return erreur ? <p className="securite-erreur">{erreur}</p> : <div className="squelette squelette--ligne" />;
  const { reglages, acoustique, telechargement, ambiance, conversation } = etat;
  const derniere = ambiance.derniere;

  return (
    <div className="veille-claude">
      <p className="sec-texte">
        Dites « Dis Jarvis, … » ou « Jarvis, … ». Le mot d'éveil est reconnu sur le PC, même mal transcrit ; s'il y a un doute (« j'arrive », « Jarvis
        » au milieu d'une phrase), une IA locale juge si vous lui parlez, sinon la phrase est écartée. Après la réponse, la suite se dit sans « Jarvis »
        pendant quelques secondes. « Stop » arrête la réponse, « silence » coupe la voix, « c'est tout » remet en veille.
      </p>
      <ul className="reglage-lignes">
        <li className="reglage-ligne">
          <Point ok={conversation.etat === "actif"} />
          <span className="reglage-ligne-nom">Cet appareil</span>
          <span className="reglage-ligne-valeur">{conversation.etat === "actif" ? "conversation en cours" : "en veille"}</span>
        </li>
      </ul>
      <div className="veille-reglages">
        <label className="carte-co-case carte-co-case--ligne">
          <input
            type="checkbox"
            checked={fond}
            disabled={!micro}
            onChange={(e) => {
              setFond(e.target.checked);
              reglerEcouteFond(e.target.checked);
              surNotifier(e.target.checked ? "« Dis Jarvis » écouté en fond sur cet appareil." : "Écoute en fond coupée.");
            }}
          />
          <span>Écouter « Dis Jarvis » en fond sur cet appareil (dans l'application de bureau, même fenêtre fermée)</span>
        </label>
      </div>
      {!micro && <p className="sec-texte">Micro indisponible dans ce navigateur.</p>}

      <div className="segment" role="radiogroup" aria-label="Relance sans « Jarvis »">
        {RELANCES.map((s) => (
          <button
            key={s}
            type="button"
            role="radio"
            aria-checked={reglages.relance_s === s}
            className="segment-btn"
            onClick={() => {
              regler({ relance_s: s });
            }}
          >
            Relance {s} s
          </button>
        ))}
      </div>

      <h4 className="carte-co-nom">Mémoire d'ambiance</h4>
      <p className="sec-texte">
        Désactivée par défaut, locale uniquement. Les phrases entendues qui ne s'adressent pas à JARVIS restent en mémoire vive ; toutes les 10 minutes
        une IA locale n'en retient que vos idées, décisions, tâches et préférences (souvenirs privés, jamais envoyés à une IA externe), puis le texte est
        oublié. Sans IA locale, rien n'est retenu. Casque conseillé : enregistrer d'autres personnes sans leur accord est interdit.
      </p>
      <div className="veille-reglages">
        <label className="carte-co-case carte-co-case--ligne">
          <input
            type="checkbox"
            checked={reglages.ambiance}
            onChange={(e) => {
              regler({ ambiance: e.target.checked });
            }}
          />
          <span>Garder une mémoire d'ambiance</span>
        </label>
      </div>
      {reglages.ambiance && (
        <div className="carte-co-actions">
          <span className="sec-texte">
            {ambiance.phrases} phrase{ambiance.phrases > 1 ? "s" : ""} en attente
            {derniere ? ` · dernier passage : ${derniere.statut === "ok" ? `${String(derniere.ajoutes ?? 0)} souvenir(s)` : (derniere.raison ?? derniere.statut)}` : ""}
          </span>
          <button
            type="button"
            className="btn btn-discret btn-mini"
            disabled={ambiance.phrases === 0}
            onClick={() => {
              appliquer(oublierAmbiance());
            }}
          >
            Oublier maintenant
          </button>
        </div>
      )}

      <h4 className="carte-co-nom">Détecteur acoustique (openWakeWord)</h4>
      <p className="sec-texte">
        Facultatif, désactivé par défaut : un petit modèle « Dis Jarvis » écarte, en veille, les phrases sans mot d'éveil avant la transcription (moins de
        calcul). Il demande le paquet Python <code>openwakeword</code> et le modèle de JARVIS (environ 3 Mo), téléchargé seulement sur votre clic.
      </p>
      <ul className="reglage-lignes">
        <li className="reglage-ligne">
          <Point ok={acoustique.paquet} />
          <span className="reglage-ligne-nom">Paquet</span>
          <span className="reglage-ligne-valeur">{acoustique.paquet ? "installé" : "absent (uv add openwakeword)"}</span>
        </li>
        <li className="reglage-ligne">
          <Point ok={acoustique.modele} />
          <span className="reglage-ligne-nom">Modèle</span>
          <span className="reglage-ligne-valeur">
            {acoustique.modele
              ? "téléchargé"
              : telechargement.statut === "en_cours"
                ? "téléchargement…"
                : telechargement.statut === "echoue"
                  ? `échec : ${telechargement.raison ?? "inconnu"}`
                  : "non téléchargé"}
          </span>
        </li>
      </ul>
      <div className="veille-reglages">
        <label className="carte-co-case carte-co-case--ligne">
          <input
            type="checkbox"
            checked={reglages.openwakeword}
            onChange={(e) => {
              regler({ openwakeword: e.target.checked });
            }}
          />
          <span>Utiliser le détecteur acoustique {reglages.openwakeword && !acoustique.utilisee ? "(indisponible : la transcription décide)" : ""}</span>
        </label>
      </div>
      {!acoustique.modele && (
        <div className="carte-co-actions">
          <button
            type="button"
            className="btn btn-mini"
            disabled={telecharge}
            onClick={() => {
              appliquer(telechargerModeleEveil());
            }}
          >
            {telechargement.statut === "echoue" ? "Réessayer le téléchargement" : "Télécharger le modèle (≈ 3 Mo)"}
          </button>
        </div>
      )}
      {erreur && <p className="carte-co-message">{erreur}</p>}
    </div>
  );
}
