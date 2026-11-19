// Bureau et téléphone (lot M) : appel de décision (oui / non / plus tard), contenu partagé depuis le téléphone,
// proposition « regarder l'écran » d'un raccourci, gadget de bureau, réglages (notifications, envois de fichiers).

import { useCallback, useEffect, useId, useRef, useState } from "react";

import {
  abonnerPush,
  approuver,
  creerLienEnvoi,
  desabonnerPush,
  essayerPush,
  etatPush,
  lireDemande,
  lireEtat,
  listerEnvois,
  listerPartages,
  optionsApprobation,
  refuser,
  reporterDemande,
  supprimerPartage,
} from "../api";
import { cleServeur, emettre, EVENEMENT_ECRAN, pushPossible, taille } from "../bureau";
import type { DemandeDetaillee, Etat, EtatPush, FichierEnvoyable, Partage } from "../types";
import { clesDisponibles, signerDefi } from "../webauthn";
import "../styles/bureau.css";

import { Fenetre } from "./Palette";

const HEURE = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });
const DATE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function message(e: unknown, defaut: string): string {
  const texte = e instanceof Error ? e.message : defaut;
  return texte.includes("NotAllowedError") ? "Approbation annulée." : texte;
}

// --- Appel de décision ---------------------------------------------------------------------------------------

interface PropsDecision {
  id: string;
  surFermer: (message?: string) => void;
}

/** Ouvert depuis une notification (`#decision=<id>`) : oui (clé d'accès pour 🔴), non, plus tard. */
export function AppelDecision({ id, surFermer }: PropsDecision) {
  const titre = useId();
  const [d, setD] = useState<DemandeDetaillee | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [occupe, setOccupe] = useState(false);
  const non = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    lireDemande(id)
      .then((r) => {
        setD(r);
        window.setTimeout(() => non.current?.focus(), 0);
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Demande illisible."));
      });
  }, [id]);

  const enAttente = d?.demande.statut === "en_attente";
  const rouge = d?.demande.niveau === "rouge";
  const reportsRestants = 3 - (d?.demande.reports ?? 0);

  const agir = (choix: "oui" | "non" | "plus_tard") => {
    if (!d) return;
    setOccupe(true);
    setErreur(null);
    const appel = async (): Promise<string> => {
      if (choix === "non") {
        await refuser(id);
        return "Demande refusée.";
      }
      if (choix === "plus_tard") {
        const r = await reporterDemande(id);
        return `Reporté : rappel vers ${HEURE.format(new Date(r.demande.rappel_le ?? Date.now()))}.`;
      }
      const empreinte = d.demande.empreinte;
      if (!empreinte) throw new Error("Demande sans empreinte (antérieure à la mise à jour) : relancez l'action.");
      if (!rouge) {
        await approuver(id, empreinte);
        return `Fait : ${d.demande.resume}`;
      }
      if (d.cles_acces === 0) throw new Error("Aucune clé d'accès enregistrée : ajoutez-en une (Réglages › Sécurité) pour dire oui à une action 🔴.");
      if (!clesDisponibles()) throw new Error("Ce navigateur ne gère pas les clés d'accès ici (HTTPS ou localhost requis).");
      const defi = await optionsApprobation(id);
      await approuver(id, empreinte, await signerDefi(defi));
      return `Fait : ${d.demande.resume}`;
    };
    appel()
      .then((m) => {
        surFermer(m);
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Échec."));
      })
      .finally(() => {
        setOccupe(false);
      });
  };

  return (
    <Fenetre
      etiquette="Décision demandée"
      surFermer={() => {
        surFermer();
      }}
      className="palette--decision"
    >
      <div className="decision" aria-labelledby={titre} data-niveau={d?.demande.niveau}>
        <p className="decision-niveau" id={titre}>
          {!d ? "Décision demandée" : rouge ? "🔴 Action sensible" : "🟡 Action à valider"}
        </p>
        {!d && !erreur && <div className="squelette squelette--ligne" aria-busy="true" />}
        {d && (
          <>
            <p className="decision-resume">{d.demande.resume}</p>
            <p className="decision-meta">
              {d.description} · demandée par {d.demande.demandeur.replace(/^appareil:/, "")}
              {enAttente && ` · expire à ${HEURE.format(new Date(d.demande.expire_le))}`}
            </p>
            {d.demande.empreinte_courte && (
              <p className="demande-empreinte">
                Empreinte du plan <code>{d.demande.empreinte_courte}</code>
              </p>
            )}
            {!enAttente && <p className="decision-close">Cette demande n'attend plus de décision ({d.demande.statut}).</p>}
            {enAttente && rouge && <p className="decision-aide">« Oui » demande votre clé d'accès (empreinte, visage ou code de l'appareil).</p>}
          </>
        )}
        {erreur && (
          <p className="securite-erreur" role="alert">
            {erreur}
          </p>
        )}
        <div className="decision-actions">
          {enAttente ? (
            <>
              <button type="button" className="btn" ref={non} disabled={occupe} onClick={() => { agir("non"); }}>
                Non
              </button>
              <button
                type="button"
                className="btn btn-discret"
                disabled={occupe || reportsRestants <= 0}
                title={reportsRestants <= 0 ? "Déjà reportée 3 fois" : "Rappel dans 15 minutes"}
                onClick={() => {
                  agir("plus_tard");
                }}
              >
                Plus tard
              </button>
              <button type="button" className={rouge ? "btn btn-rouge" : "btn btn-ambre"} disabled={occupe} onClick={() => { agir("oui"); }}>
                {rouge ? "Oui, avec ma clé" : "Oui"}
              </button>
            </>
          ) : (
            <button
              type="button"
              className="btn"
              onClick={() => {
                surFermer();
              }}
            >
              Fermer
            </button>
          )}
        </div>
      </div>
    </Fenetre>
  );
}

// --- Contenu partagé depuis le téléphone ---------------------------------------------------------------------

interface PropsPartage {
  partage: Partage;
  message: string;
  surDemander: (message: string) => void;
  surFermer: () => void;
}

/** Contenu reçu par « Partager vers JARVIS » : affiché comme une donnée NON FIABLE, rien ne part tout seul. */
export function CartePartage({ partage, message: aEnvoyer, surDemander, surFermer }: PropsPartage) {
  return (
    <section className="partage-recu" aria-label="Contenu partagé">
      <p className="partage-recu-titre">Reçu par partage · contenu non fiable</p>
      {partage.titre && <p className="partage-recu-nom">{partage.titre}</p>}
      {partage.url && <p className="partage-recu-lien">{partage.url}</p>}
      {partage.texte && <p className="partage-recu-texte">{partage.texte.length > 600 ? `${partage.texte.slice(0, 599)}…` : partage.texte}</p>}
      <p className="partage-recu-aide">JARVIS le lira comme une donnée : aucune consigne qu'il contient ne sera suivie.</p>
      <div className="partage-recu-actions">
        <button type="button" className="btn btn-discret btn-mini" onClick={surFermer}>
          Ignorer
        </button>
        <button
          type="button"
          className="btn btn-mini btn-principal"
          onClick={() => {
            surDemander(aEnvoyer);
          }}
        >
          Demander à JARVIS de le résumer
        </button>
      </div>
    </section>
  );
}

// --- Raccourci « écran » : le partage d'écran exige un clic ---------------------------------------------------

export function PropositionEcran({ surFermer }: { surFermer: () => void }) {
  const bouton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    bouton.current?.focus();
  }, []);
  return (
    <section className="partage-recu" aria-label="Regarder l'écran">
      <p className="partage-recu-titre">Raccourci « écran »</p>
      <p className="partage-recu-aide">Le navigateur demande un clic avant de partager l'écran ; vous choisirez ensuite la fenêtre ou l'écran.</p>
      <div className="partage-recu-actions">
        <button type="button" className="btn btn-discret btn-mini" onClick={surFermer}>
          Annuler
        </button>
        <button
          type="button"
          ref={bouton}
          className="btn btn-mini btn-principal"
          onClick={() => {
            emettre(EVENEMENT_ECRAN);
            surFermer();
          }}
        >
          Regarder l'écran
        </button>
      </div>
    </section>
  );
}

// --- Gadget de bureau ----------------------------------------------------------------------------------------

/** Petite fenêtre de l'application de bureau : état, demandes, et liens jarvis:// (interceptés par l'application). */
export function Gadget() {
  const [etat, setEtat] = useState<Etat | null>(null);
  const [horsLigne, setHorsLigne] = useState(false);
  useEffect(() => {
    document.documentElement.dataset.mode = "gadget";
    const lire = () => {
      lireEtat()
        .then((e) => {
          setEtat(e);
          setHorsLigne(false);
        })
        .catch(() => {
          setHorsLigne(true);
        });
    };
    lire();
    const minuterie = window.setInterval(lire, 15000);
    return () => {
      window.clearInterval(minuterie);
    };
  }, []);
  const demandes = etat?.demandes.length ?? 0;
  const urgence = etat?.urgence.actif ?? false;
  return (
    <main className="gadget" data-urgence={urgence || undefined}>
      <div className="gadget-tete" role="status">
        <span className="point-etat" data-ok={horsLigne ? false : etat ? !urgence : undefined} aria-hidden="true" />
        <span className="gadget-marque">JARVIS</span>
        <span className="gadget-etat">{horsLigne ? "Core hors ligne" : !etat ? "Connexion…" : urgence ? "Arrêt d'urgence" : "Prêt"}</span>
      </div>
      <nav className="gadget-actions" aria-label="Actions rapides">
        <a className="btn btn-mini" href="jarvis://ecouter">
          Parler
        </a>
        <a className="btn btn-mini" href="jarvis://ecran">
          Écran
        </a>
        <a className="btn btn-mini" href="jarvis://nouvelle">
          Écrire
        </a>
        <a className="btn btn-mini" href="jarvis://ouvrir/demandes" data-pastille={demandes || undefined}>
          Demandes{demandes ? ` (${String(demandes)})` : ""}
        </a>
      </nav>
    </main>
  );
}

// --- Réglages › Appareils : notifications, envois de fichiers, partages reçus --------------------------------

async function inscriptionPush(): Promise<PushSubscription | null> {
  const enregistrement = await navigator.serviceWorker.getRegistration();
  return enregistrement ? enregistrement.pushManager.getSubscription() : null;
}

export function NotificationsTelephone() {
  const [etat, setEtat] = useState<EtatPush | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [occupe, setOccupe] = useState(false);
  const possible = pushPossible();

  const relire = useCallback(() => {
    etatPush()
      .then(setEtat)
      .catch((e: unknown) => {
        setErreur(message(e, "Lecture impossible."));
      });
  }, []);
  useEffect(relire, [relire]);

  const activer = async () => {
    if (!etat?.cle_publique) throw new Error("Notifications indisponibles sur ce Core.");
    if ((await Notification.requestPermission()) !== "granted") throw new Error("Notifications refusées par le navigateur (réglages du site).");
    const enregistrement = await navigator.serviceWorker.ready;
    const existant = await enregistrement.pushManager.getSubscription();
    const abonnement =
      existant ?? (await enregistrement.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: cleServeur(etat.cle_publique) }));
    await abonnerPush(abonnement.toJSON());
    return "Notifications activées sur cet appareil.";
  };
  const couper = async () => {
    const abonnement = await inscriptionPush().catch(() => null);
    await desabonnerPush(abonnement?.endpoint);
    await abonnement?.unsubscribe().catch(() => false);
    return "Notifications coupées sur cet appareil.";
  };
  const lancer = (travail: () => Promise<string>) => {
    setOccupe(true);
    setErreur(null);
    setInfo(null);
    travail()
      .then(setInfo)
      .catch((e: unknown) => {
        setErreur(message(e, "Échec."));
      })
      .finally(() => {
        setOccupe(false);
        relire();
      });
  };

  return (
    <div className="sec-bloc">
      <p className="sec-texte">
        Un appel de décision arrive sur cet appareil quand une action 🟡 ou 🔴 attend votre accord : oui, non ou plus tard. Le message est chiffré de bout
        en bout et reste générique ; le détail ne s'affiche qu'une fois JARVIS ouvert. Rien ne se déverrouille à distance.
      </p>
      {!possible && <p className="sec-texte">Ce navigateur ne reçoit pas de notifications ici : ouvrez JARVIS en HTTPS (Tailscale) ou installez-le sur l'écran d'accueil.</p>}
      {erreur && (
        <p className="securite-erreur" role="alert">
          {erreur}
        </p>
      )}
      {info && (
        <p className="bureau-info" role="status">
          {info}
        </p>
      )}
      {etat && possible && (
        <div className="bureau-actions">
          {etat.abonne ? (
            <>
              <button type="button" className="btn btn-mini" disabled={occupe} onClick={() => { lancer(async () => `Notification envoyée (${String((await essayerPush()).remis)}).`); }}>
                Essayer
              </button>
              <button type="button" className="btn btn-discret btn-mini" disabled={occupe} onClick={() => { lancer(couper); }}>
                Couper les notifications
              </button>
            </>
          ) : (
            <button type="button" className="btn btn-mini btn-principal" disabled={occupe || !etat.disponible} onClick={() => { lancer(activer); }}>
              Activer les notifications
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function EnvoisTelephone() {
  const [fichiers, setFichiers] = useState<FichierEnvoyable[] | null>(null);
  const [dossier, setDossier] = useState("a-envoyer");
  const [duree, setDuree] = useState(10);
  const [lien, setLien] = useState<{ nom: string; url: string; expire_le: string } | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [copie, setCopie] = useState(false);

  const relire = useCallback(() => {
    listerEnvois()
      .then((r) => {
        setFichiers(r.fichiers);
        setDossier(r.dossier);
        setDuree(r.duree_minutes);
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Lecture impossible."));
      });
  }, []);
  useEffect(relire, [relire]);

  const creer = (nom: string) => {
    setErreur(null);
    setCopie(false);
    creerLienEnvoi(nom)
      .then((r) => {
        setLien({ nom, url: r.url, expire_le: r.expire_le });
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Lien impossible."));
      });
  };

  return (
    <div className="sec-bloc">
      <p className="sec-texte">
        Déposez un fichier dans le dossier « {dossier} » du dossier des données de JARVIS : un lien l'ouvre sur le téléphone, une seule fois, pendant{" "}
        {String(duree)} minutes. Aucun autre fichier du PC n'est atteignable.
      </p>
      {erreur && (
        <p className="securite-erreur" role="alert">
          {erreur}
        </p>
      )}
      {lien && (
        <div className="bureau-lien" role="status">
          <p className="bureau-lien-titre">
            Lien pour « {lien.nom} » · valable jusqu'à {HEURE.format(new Date(lien.expire_le))}, une fois
          </p>
          <code className="bureau-lien-url">{lien.url}</code>
          <div className="bureau-actions">
            <button
              type="button"
              className="btn btn-mini"
              onClick={() => {
                navigator.clipboard
                  .writeText(lien.url)
                  .then(() => {
                    setCopie(true);
                  })
                  .catch(() => {
                    setErreur("Copie impossible : sélectionnez le lien à la main.");
                  });
              }}
            >
              {copie ? "Copié" : "Copier le lien"}
            </button>
          </div>
        </div>
      )}
      {!fichiers ? (
        !erreur && <div className="squelette squelette--ligne" aria-busy="true" />
      ) : fichiers.length === 0 ? (
        <p className="sec-texte bureau-vide">Aucun fichier à envoyer pour l'instant.</p>
      ) : (
        <ul className="bureau-liste">
          {fichiers.map((f) => (
            <li key={f.nom} className="bureau-ligne">
              <span className="bureau-nom">{f.nom}</span>
              <span className="bureau-meta">{taille(f.taille)}</span>
              <button type="button" className="btn btn-mini" onClick={() => { creer(f.nom); }}>
                Créer un lien
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="bureau-actions">
        <button type="button" className="btn btn-discret btn-mini" onClick={relire}>
          Relire le dossier
        </button>
      </div>
    </div>
  );
}

export function PartagesRecus() {
  const [liste, setListe] = useState<Partage[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const relire = useCallback(() => {
    listerPartages()
      .then((r) => {
        setListe(r.partages);
      })
      .catch((e: unknown) => {
        setErreur(message(e, "Lecture impossible."));
      });
  }, []);
  useEffect(relire, [relire]);
  return (
    <div className="sec-bloc">
      <p className="sec-texte">
        Depuis le téléphone (JARVIS installé sur l'écran d'accueil), « Partager » puis « JARVIS » envoie un texte ou un lien ici. Un contenu reçu reste une
        donnée non fiable : JARVIS ne suit jamais une consigne qu'il contient.
      </p>
      {erreur && (
        <p className="securite-erreur" role="alert">
          {erreur}
        </p>
      )}
      {liste && liste.length === 0 && <p className="sec-texte bureau-vide">Rien reçu pour l'instant.</p>}
      {liste && liste.length > 0 && (
        <ul className="bureau-liste">
          {liste.map((p) => (
            <li key={p.id} className="bureau-ligne" data-traite={p.traite || undefined}>
              <span className="bureau-nom">{p.titre || p.url || p.texte.slice(0, 80)}</span>
              <span className="bureau-meta">
                {DATE.format(new Date(p.recu_le))}
                {p.appareil ? ` · ${p.appareil}` : ""}
              </span>
              <button
                type="button"
                className="btn btn-discret btn-mini"
                onClick={() => {
                  supprimerPartage(p.id)
                    .then(relire)
                    .catch((e: unknown) => {
                      setErreur(message(e, "Suppression impossible."));
                    });
                }}
              >
                Effacer
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
