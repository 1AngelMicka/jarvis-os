// Ressources et contrôle du PC (phase 13, lot J), dans Réglages › PC & mode jeu.
// Lecture libre (CPU, RAM, GPU, VRAM, Ollama, état du PC) ; toute action passe par /v1/actions, donc par la file
// d'approbations (🟡 un clic, 🔴 clé d'accès), le journal d'audit et l'arrêt d'urgence. Chaque action relue par le
// Core revient « vérifiée » ou « non vérifiée ».

import { useCallback, useEffect, useState } from "react";

import "../styles/pc.css";

import { demanderAction, lireControlePC, lireRessourcesPC } from "../api";
import type {
  EtatControlePC,
  FenetrePC,
  PointCourbePC,
  ReglageJeu,
  ReponseAction,
  RessourcesPC,
} from "../types";

const INTERVALLE_MS = 5000;

export interface PropsPC {
  surNotifier: (message: string) => void;
  surChangement: (message?: string) => void;
  surDemandes: () => void;
}

/** Message d'une action : en attente (file d'approbations) ou faite, vérifiée ou non. */
export function messageAction(r: ReponseAction, fait: string): string {
  if (r.statut === "en_attente") {
    return r.demande.niveau === "rouge"
      ? "Action 🔴 : approuvez-la avec votre clé d'accès."
      : "Action 🟡 en attente de votre accord.";
  }
  if (r.statut === "refusee") return "Demande refusée.";
  const v = r.resultat.verifiee;
  if (v === false) {
    const detail =
      typeof r.resultat.detail === "string" ? ` (${r.resultat.detail})` : "";
    return `${fait} — non vérifiée${detail}`;
  }
  return v === true ? `${fait} — vérifiée` : fait;
}

function useAgir(p: PropsPC, apres?: () => void) {
  return useCallback(
    (action: string, parametres: Record<string, unknown>, fait: string) => {
      demanderAction({ action, parametres })
        .then((r) => {
          if (r.statut === "en_attente") {
            p.surChangement(messageAction(r, fait));
            p.surDemandes();
          } else p.surNotifier(messageAction(r, fait));
          apres?.();
        })
        .catch((e: unknown) => {
          p.surNotifier(e instanceof Error ? e.message : "Action impossible.");
        });
    },
    [p, apres],
  );
}

function pourcent(v: number | null): string {
  return v === null ? "—" : `${String(Math.round(v))} %`;
}

function go(v: number | null): string {
  return v === null
    ? "?"
    : v.toLocaleString("fr-FR", { maximumFractionDigits: 1 });
}

function ton(v: number | null, seuil: number): string | undefined {
  if (v === null) return undefined;
  return v >= seuil ? "danger" : v >= seuil - 15 ? "attention" : undefined;
}

/** Courbe des 10 dernières minutes (une ligne par ressource, sans valeur inventée pour les trous). */
function Courbe({
  points,
  cle,
  nom,
}: {
  points: PointCourbePC[];
  cle: "cpu" | "ram" | "gpu" | "vram";
  nom: string;
}) {
  const valeurs = points.filter((x) => x[cle] !== null);
  if (valeurs.length < 2) return null;
  const debut = valeurs[0]?.t ?? 0;
  const fin = valeurs[valeurs.length - 1]?.t ?? 1;
  const largeur = Math.max(1, fin - debut);
  const tracé = valeurs
    .map(
      (x) =>
        `${String(((x.t - debut) / largeur) * 100)},${String(30 - ((x[cle] ?? 0) / 100) * 30)}`,
    )
    .join(" ");
  return (
    <svg
      className="pc-courbe"
      viewBox="0 0 100 30"
      preserveAspectRatio="none"
      role="img"
      aria-label={`${nom} sur les 10 dernières minutes`}
    >
      <polyline points={tracé} />
    </svg>
  );
}

function Jauge({
  nom,
  valeur,
  detail,
  seuil,
  points,
  cle,
}: {
  nom: string;
  valeur: number | null;
  detail: string;
  seuil: number;
  points: PointCourbePC[];
  cle: "cpu" | "ram" | "gpu" | "vram";
}) {
  return (
    <li
      className="jauge pc-jauge"
      data-etat={valeur === null ? "inconnu" : undefined}
      data-ton={ton(valeur, seuil)}
    >
      <div className="jauge-tete">
        <span className="jauge-nom">{nom}</span>
        <span className="jauge-valeur">{pourcent(valeur)}</span>
      </div>
      <div
        className="jauge-barre"
        role="meter"
        aria-label={nom}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={valeur ?? undefined}
      >
        <span
          className="jauge-remplie"
          style={
            { "--part": String((valeur ?? 0) / 100) } as React.CSSProperties
          }
        />
      </div>
      <Courbe points={points} cle={cle} nom={nom} />
      <p className="jauge-detail">{detail}</p>
    </li>
  );
}

function useRessources() {
  const [r, setR] = useState<RessourcesPC | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const relire = useCallback(() => {
    lireRessourcesPC()
      .then((x) => {
        setR(x);
        setErreur(null);
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Ressources illisibles.");
      });
  }, []);
  useEffect(() => {
    relire();
    const minuteur = window.setInterval(() => {
      if (document.visibilityState === "visible") relire();
    }, INTERVALLE_MS);
    return () => {
      window.clearInterval(minuteur);
    };
  }, [relire]);
  return { r, erreur, relire };
}

/** CPU, RAM, GPU, VRAM en direct, et les modèles Ollama chargés. */
export function RessourcesDuPC(p: PropsPC) {
  const { r, erreur, relire } = useRessources();
  const agir = useAgir(p, relire);
  if (erreur && !r)
    return (
      <p className="sec-texte" role="alert">
        {erreur}
      </p>
    );
  if (!r)
    return <div className="squelette squelette--ligne" aria-busy="true" />;
  const a = r.actuel;
  const o = r.ollama;
  const seuil = r.seuil_alerte;
  return (
    <div className="pc">
      <ul className="jauges pc-jauges">
        <Jauge
          nom="Processeur"
          valeur={a.cpu}
          detail="toutes les unités"
          seuil={seuil}
          points={r.courbe}
          cle="cpu"
        />
        <Jauge
          nom="Mémoire vive"
          valeur={a.ram}
          detail={`${go(a.ram_utilisee_go)} / ${go(a.ram_totale_go)} Go`}
          seuil={seuil}
          points={r.courbe}
          cle="ram"
        />
        <Jauge
          nom="Carte graphique"
          valeur={a.gpu}
          detail={a.gpu === null ? "non mesurable ici" : "moteur 3D"}
          seuil={seuil}
          points={r.courbe}
          cle="gpu"
        />
        <Jauge
          nom="Mémoire vidéo"
          valeur={a.vram}
          detail={`${go(a.vram_utilisee_go)} / ${go(a.vram_totale_go)} Go`}
          seuil={seuil}
          points={r.courbe}
          cle="vram"
        />
      </ul>
      {r.alertes.length > 0 && (
        <p className="pc-alerte" role="status">
          Au-delà de {seuil} % : {r.alertes.join(", ")}.
        </p>
      )}
      <div className="pc-bloc">
        <h3 className="pc-sous-titre">Ollama (IA locales)</h3>
        <p className="sec-texte" data-etat={o.joignable ? "ok" : undefined}>
          {!o.installe && !o.joignable
            ? "Ollama n'est pas installé sur ce PC."
            : !o.joignable
              ? "Arrêté. JARVIS ne le démarre jamais seul : seulement quand vous le demandez."
              : o.lance_par_jarvis
                ? `Démarré par JARVIS à votre demande${o.arret_dans_s !== null ? ` · arrêt automatique dans ${String(Math.ceil(o.arret_dans_s / 60))} min sans modèle chargé` : ` · arrêt après ${String(o.inactivite_min)} min sans modèle chargé`}.`
                : "Démarré hors de JARVIS : JARVIS peut décharger ses modèles, jamais l'arrêter."}
        </p>
        {o.modeles_charges.length > 0 ? (
          <ul className="reglage-lignes">
            {o.modeles_charges.map((m) => (
              <li key={m.nom} className="reglage-ligne pc-modele">
                <span
                  className="point-etat"
                  data-ok="true"
                  aria-hidden="true"
                />
                <span className="reglage-ligne-nom">{m.nom}</span>
                <span className="reglage-ligne-valeur">
                  {go(m.vram_go)} Go en VRAM
                </span>
                <button
                  type="button"
                  className="btn btn-discret btn-mini"
                  onClick={() => {
                    agir(
                      "ollama.decharger",
                      { modele: m.nom },
                      `${m.nom} déchargé`,
                    );
                  }}
                >
                  Décharger
                </button>
              </li>
            ))}
          </ul>
        ) : (
          o.joignable && (
            <p className="sec-texte">Aucun modèle chargé en mémoire.</p>
          )
        )}
        <div className="pc-boutons">
          {!o.joignable && o.installe && (
            <button
              type="button"
              className="btn btn-mini"
              title="Démarre Ollama après votre accord (🟡), jamais tout seul"
              onClick={() => {
                agir("ollama.demarrer", {}, "Ollama démarré");
              }}
            >
              Démarrer Ollama (🟡)
            </button>
          )}
          {o.joignable && o.modeles_charges.length > 1 && (
            <button
              type="button"
              className="btn btn-discret btn-mini"
              onClick={() => {
                agir("ollama.decharger", {}, "Modèles déchargés");
              }}
            >
              Tout décharger
            </button>
          )}
          {o.lance_par_jarvis && (
            <button
              type="button"
              className="btn btn-discret btn-mini"
              onClick={() => {
                agir("ollama.arreter", {}, "Ollama arrêté");
              }}
            >
              Arrêter Ollama (🟡)
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

const REGLAGES_JEU: readonly { id: ReglageJeu; nom: string }[] = [
  { id: "automatique", nom: "Automatique" },
  { id: "force", nom: "Veille forcée" },
  { id: "jamais", nom: "Jamais" },
];

/** Mode jeu = veille stricte : automatique quand un jeu est au premier plan, forcée, ou jamais. */
export function ModeJeuPC(p: PropsPC) {
  const { r, relire } = useRessources();
  const agir = useAgir(p, relire);
  if (!r)
    return <div className="squelette squelette--ligne" aria-busy="true" />;
  const j = r.jeu;
  return (
    <div className="reglage-controles">
      <div className="segment" role="radiogroup" aria-label="Mode jeu">
        {REGLAGES_JEU.map((o) => (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={j.reglage === o.id}
            className="segment-btn"
            onClick={() => {
              agir(
                "pc.jeu",
                { reglage: o.id },
                `Mode jeu : ${o.nom.toLowerCase()}`,
              );
            }}
          >
            {o.nom}
          </button>
        ))}
      </div>
      <p
        className="sec-texte"
        role="status"
        data-etat={j.en_veille ? undefined : "ok"}
      >
        {j.en_veille
          ? `En veille${j.jeu ? ` (jeu : ${j.jeu})` : ""} : modèles déchargés, Ollama arrêté, recettes en attente, ni son ni notification.`
          : j.reglage === "automatique"
            ? j.detection
              ? "Éveillé. Veille 5 s après le lancement d'un jeu, réveil 20 s après la fin."
              : "Éveillé. Détection des jeux indisponible ici (mode sans écran ou autre système)."
            : "Éveillé : la veille ne se déclenche jamais."}
      </p>
    </div>
  );
}

/** Contrôle du PC : volume, luminosité, média, fenêtres, verrouillage, extinction, modes de Windows. */
export function ControlePC(p: PropsPC) {
  const [e, setE] = useState<EtatControlePC | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [volume, setVolume] = useState<number | null>(null);
  const [luminosite, setLuminosite] = useState<number | null>(null);
  const relire = useCallback(() => {
    lireControlePC()
      .then((x) => {
        setE(x);
        setVolume(x.volume?.niveau ?? null);
        setLuminosite(x.luminosite);
        setErreur(null);
      })
      .catch((err: unknown) => {
        setErreur(err instanceof Error ? err.message : "État du PC illisible.");
      });
  }, []);
  useEffect(relire, [relire]);
  const agir = useAgir(p, relire);
  if (erreur)
    return (
      <p className="sec-texte" role="alert">
        {erreur}
      </p>
    );
  if (!e)
    return <div className="squelette squelette--ligne" aria-busy="true" />;
  const fenetre = (
    f: FenetrePC,
    action: "activer" | "minimiser" | "restaurer" | "fermer",
    libelle: string,
    fait: string,
  ) => (
    <button
      type="button"
      className={
        action === "fermer"
          ? "btn btn-discret btn-danger btn-mini"
          : "btn btn-discret btn-mini"
      }
      onClick={() => {
        agir(`pc.fenetre.${action}`, { id: f.id, titre: f.titre }, fait);
      }}
    >
      {libelle}
    </button>
  );
  return (
    <div className="pc">
      <div className="reglage-controles">
        <div className="reglage-controle">
          <label className="reglage-controle-nom" htmlFor="pc-volume">
            Volume
          </label>
          {e.volume ? (
            <>
              <input
                id="pc-volume"
                className="pc-curseur"
                type="range"
                min={0}
                max={100}
                step={1}
                value={volume ?? 0}
                onChange={(x) => {
                  setVolume(Number(x.target.value));
                }}
              />
              <span className="pc-valeur">{String(volume ?? 0)} %</span>
              <button
                type="button"
                className="btn btn-mini"
                disabled={volume === e.volume.niveau}
                onClick={() => {
                  agir(
                    "pc.volume",
                    { niveau: volume },
                    `Volume à ${String(volume)} %`,
                  );
                }}
              >
                Appliquer (🟡)
              </button>
              <button
                type="button"
                className="btn btn-discret btn-mini"
                aria-pressed={e.volume.muet}
                onClick={() => {
                  agir(
                    "pc.sourdine",
                    { muet: !e.volume?.muet },
                    e.volume?.muet ? "Son remis" : "Son coupé",
                  );
                }}
              >
                {e.volume.muet ? "Remettre le son" : "Couper le son"}
              </button>
            </>
          ) : (
            <span className="sec-texte">illisible sur ce PC</span>
          )}
        </div>
        <div className="reglage-controle">
          <label className="reglage-controle-nom" htmlFor="pc-luminosite">
            Luminosité
          </label>
          {e.luminosite !== null ? (
            <>
              <input
                id="pc-luminosite"
                className="pc-curseur"
                type="range"
                min={0}
                max={100}
                step={5}
                value={luminosite ?? 0}
                onChange={(x) => {
                  setLuminosite(Number(x.target.value));
                }}
              />
              <span className="pc-valeur">{String(luminosite ?? 0)} %</span>
              <button
                type="button"
                className="btn btn-mini"
                disabled={luminosite === e.luminosite}
                onClick={() => {
                  agir(
                    "pc.luminosite",
                    { niveau: luminosite },
                    `Luminosité à ${String(luminosite)} %`,
                  );
                }}
              >
                Appliquer (🟡)
              </button>
            </>
          ) : (
            <span className="sec-texte">
              non réglable sur cet écran (ni DDC/CI ni écran de portable)
            </span>
          )}
        </div>
      </div>

      <div className="pc-bloc">
        <h3 className="pc-sous-titre">Média en cours</h3>
        {e.media?.statut ? (
          <div className="reglage-controle">
            <span className="pc-media">
              <span className="pc-media-titre">
                {e.media.titre ?? "Sans titre"}
              </span>
              {e.media.artiste && (
                <span className="pc-media-artiste"> · {e.media.artiste}</span>
              )}
              <span className="pc-media-etat">
                {" "}
                ·{" "}
                {e.media.statut === "lecture"
                  ? "en lecture"
                  : e.media.statut === "pause"
                    ? "en pause"
                    : "arrêté"}
              </span>
            </span>
            <div className="pc-boutons">
              <button
                type="button"
                className="btn btn-discret btn-mini"
                onClick={() => {
                  agir(
                    "pc.media",
                    { commande: "precedent" },
                    "Morceau précédent",
                  );
                }}
              >
                Précédent
              </button>
              <button
                type="button"
                className="btn btn-mini"
                onClick={() => {
                  agir(
                    "pc.media",
                    { commande: "bascule" },
                    e.media?.statut === "lecture" ? "Pause" : "Lecture",
                  );
                }}
              >
                {e.media.statut === "lecture" ? "Pause" : "Lecture"}
              </button>
              <button
                type="button"
                className="btn btn-discret btn-mini"
                onClick={() => {
                  agir("pc.media", { commande: "suivant" }, "Morceau suivant");
                }}
              >
                Suivant
              </button>
            </div>
          </div>
        ) : (
          <p className="sec-texte">Aucun média en cours.</p>
        )}
      </div>

      <div className="pc-bloc">
        <h3 className="pc-sous-titre">Fenêtres ouvertes</h3>
        {e.fenetres && e.fenetres.length > 0 ? (
          <ul className="pc-fenetres">
            {e.fenetres.map((f) => (
              <li
                key={f.id}
                className="pc-fenetre"
                data-active={f.active || undefined}
              >
                <span className="pc-fenetre-titre" title={f.titre}>
                  {f.titre}
                </span>
                <span className="pc-fenetre-prog">
                  {f.programme}
                  {f.active
                    ? " · au premier plan"
                    : f.reduite
                      ? " · réduite"
                      : ""}
                </span>
                <span className="pc-boutons">
                  {!f.active &&
                    fenetre(
                      f,
                      "activer",
                      "Premier plan",
                      "Fenêtre au premier plan",
                    )}
                  {f.reduite
                    ? fenetre(f, "restaurer", "Restaurer", "Fenêtre restaurée")
                    : fenetre(f, "minimiser", "Réduire", "Fenêtre réduite")}
                  {fenetre(f, "fermer", "Fermer", "Fenêtre fermée")}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="sec-texte">Aucune fenêtre lisible.</p>
        )}
      </div>

      <div className="pc-bloc">
        <h3 className="pc-sous-titre">Modes de Windows</h3>
        <ul className="pc-modes">
          {e.modes.map((m) => (
            <li
              key={m.id}
              className="pc-mode"
              data-actif={e.mode === m.id || undefined}
            >
              <span className="pc-mode-nom">
                {m.titre}
                {e.mode === m.id ? " · actif" : ""}
              </span>
              <span className="pc-mode-desc">{m.description}</span>
              {e.mode !== m.id && (
                <button
                  type="button"
                  className="btn btn-mini"
                  onClick={() => {
                    agir(
                      "pc.mode",
                      { mode: m.id },
                      `Mode ${m.titre.toLowerCase()} appliqué`,
                    );
                  }}
                >
                  Appliquer (🟡)
                </button>
              )}
            </li>
          ))}
        </ul>
        <p className="sec-texte">
          {e.plan_alimentation
            ? `Plan d'alimentation : ${e.plan_alimentation.nom ?? e.plan_alimentation.actif}`
            : "Plan d'alimentation illisible"}{" "}
          · bannières de notification{" "}
          {e.notifications === null
            ? "?"
            : e.notifications
              ? "affichées"
              : "coupées"}{" "}
          · thème{" "}
          {e.theme_sombre === null ? "?" : e.theme_sombre ? "sombre" : "clair"}
        </p>
      </div>

      <div className="pc-bloc">
        <h3 className="pc-sous-titre">Session</h3>
        <div className="pc-boutons">
          <button
            type="button"
            className="btn btn-discret btn-mini"
            onClick={() => {
              agir("pc.verrouiller", {}, "PC verrouillé");
            }}
          >
            Verrouiller (🟡)
          </button>
          {e.extinction_dans_s !== null ? (
            <button
              type="button"
              className="btn btn-mini"
              onClick={() => {
                agir("pc.extinction.annuler", {}, "Extinction annulée");
              }}
            >
              Annuler l'extinction ({String(e.extinction_dans_s)} s)
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-discret btn-danger btn-mini"
              title="Après votre clé d'accès ; annulable jusqu'au bout"
              onClick={() => {
                agir("pc.eteindre", { delai_s: 60 }, "Extinction planifiée");
              }}
            >
              Éteindre dans 60 s (🔴)
            </button>
          )}
          <button
            type="button"
            className="btn btn-discret btn-mini"
            onClick={relire}
          >
            Relire l'état
          </button>
        </div>
      </div>
    </div>
  );
}
