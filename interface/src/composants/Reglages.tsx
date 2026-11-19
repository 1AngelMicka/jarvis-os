// Vue Réglages (phase 13, lot G) : tous les réglages, rangés par catégories, avec une recherche et des adresses
// directes (`#reglages/<catégorie ou section>`). Aucune logique dupliquée : chaque section reprend le composant qui
// gère déjà ce réglage ailleurs (connecteurs, coûts, accueil du matin, mémoire, sécurité…).

import { type ReactNode, useEffect, useId, useRef, useState } from "react";

import "../styles/reglages.css";

import { choisirAnimations, CHOIX_ANIMATIONS, type ChoixAnimations, estChoixAnimations, EVENEMENT_ANIMATIONS, lireAnimations } from "../animations";
import { RACCOURCIS } from "../commandes";
import { choisirFondEcran, EVENEMENT_FOND, lireFondEcran } from "../presence";
import { EVENEMENT_THEME, lireTheme } from "../theme";
import {
  CATEGORIES,
  categorie as infoCategorie,
  chercherSections,
  type Cible,
  ecrireDerniereCategorie,
  type IdCategorie,
  lireDerniereCategorie,
  sectionsDe,
  type Section,
} from "../reglages";
import type { Etat } from "../types";
import { EVENEMENT_SILENCE, EVENEMENT_VOIX, type LecteurVocal, reglerVoix, voixLocales } from "../voix";
import { Telephone, Verifications } from "./Accueil";
import { EnvoisTelephone, NotificationsTelephone, PartagesRecus } from "./Bureau";
import { VueConnecteurs } from "./Connecteurs";
import { VueCouts } from "./Couts";
import { ReglagesEveil } from "./Eveil";
import { FluxDonnees } from "./FluxDonnees";
import { ReglagesMatin } from "./Matin";
import { SectionMemoire } from "./Memoire";
import { ControlePC, ModeJeuPC, RessourcesDuPC } from "./PC";
import { AutorisationsPermanentes, CommandesRapides, ReglagePilotage, ReglesProtection } from "./Pilotage";
import { ReglageSynthese } from "./ReglageSynthese";
import { EtatTranscriptionVoix, ReglageDictee, ReglageProprietaire } from "./ReglagesVoix";
import { PanneauSecurite } from "./Securite";
import { SelecteurTheme } from "./SelecteurTheme";
import { VeilleClaude } from "./VeilleClaude";
import { VueProfil } from "./VueProfil";

interface Props {
  etat: Etat | null;
  lecteur: LecteurVocal;
  /** Où aller (adresse directe, palette, « /reglages mots ») ; `jeton` change à chaque demande, même vers la même cible. */
  cible: DemandeReglages | null;
  /** La catégorie ou la section affichée a changé : l'adresse de la page suit. */
  surPosition: (c: Cible) => void;
  surChangement: (message?: string) => void;
  surNotifier: (message: string) => void;
  surRejouerMatin: () => void;
  surInstallation: () => void;
  surAide: () => void;
  surPalette: () => void;
  surDemandes: () => void;
  surUrgence: () => void;
  surLeverUrgence: () => void;
}

export interface DemandeReglages extends Partial<Cible> {
  jeton: number;
  /** Texte à chercher (« /reglages plafond » quand le mot ne désigne pas une section). */
  recherche?: string;
}

/** Choix exclusif en pastilles (même composant visuel que la console et l'accueil du matin). */
function Segment<T extends string>({ libelle, options, valeur, surChoix }: { libelle: string; options: readonly { id: T; nom: string }[]; valeur: T; surChoix: (v: T) => void }) {
  return (
    <div className="segment" role="radiogroup" aria-label={libelle}>
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          role="radio"
          aria-checked={valeur === o.id}
          className="segment-btn"
          onClick={() => {
            surChoix(o.id);
          }}
        >
          {o.nom}
        </button>
      ))}
    </div>
  );
}

const VOIX = [
  { id: "oui", nom: "Activée" },
  { id: "non", nom: "Coupée" },
] as const;

/** Lecture des réponses à voix haute : suit Ctrl+M, « /silence » et le bouton de la console. */
function ChoixVoix({ lecteur }: { lecteur: LecteurVocal }) {
  const [actif, setActif] = useState(lecteur.actif);
  useEffect(() => {
    const couper = () => {
      setActif(false);
    };
    const allumer = () => {
      setActif(true);
    };
    window.addEventListener(EVENEMENT_SILENCE, couper);
    window.addEventListener(EVENEMENT_VOIX, allumer);
    return () => {
      window.removeEventListener(EVENEMENT_SILENCE, couper);
      window.removeEventListener(EVENEMENT_VOIX, allumer);
    };
  }, []);
  return (
    <Segment
      libelle="Lecture à voix haute"
      options={VOIX}
      valeur={actif ? "oui" : "non"}
      surChoix={(v) => {
        reglerVoix(lecteur, v === "oui");
      }}
    />
  );
}

function ChoixAnimationsAppareil() {
  const [choix, setChoix] = useState<ChoixAnimations>(lireAnimations);
  useEffect(() => {
    const suivre = (e: Event) => {
      const v = (e as CustomEvent<unknown>).detail;
      if (estChoixAnimations(v)) setChoix(v);
    };
    window.addEventListener(EVENEMENT_ANIMATIONS, suivre);
    return () => {
      window.removeEventListener(EVENEMENT_ANIMATIONS, suivre);
    };
  }, []);
  return <Segment libelle="Animations" options={CHOIX_ANIMATIONS} valeur={choix} surChoix={choisirAnimations} />;
}

const PLACES_ORBE = [
  { id: "panneau", nom: "Dans le panneau Noyau" },
  { id: "fond", nom: "HUD en fond d'écran" },
] as const;

/** Thème Présence : l'orbe reste dans le panneau Noyau ou passe derrière tout le HUD. */
function ChoixPresence() {
  const [fond, setFond] = useState(lireFondEcran);
  const [theme, setTheme] = useState(lireTheme);
  useEffect(() => {
    const surFond = (e: Event) => {
      setFond((e as CustomEvent<unknown>).detail === true);
    };
    const surTheme = () => {
      setTheme(lireTheme());
    };
    window.addEventListener(EVENEMENT_FOND, surFond);
    window.addEventListener(EVENEMENT_THEME, surTheme);
    return () => {
      window.removeEventListener(EVENEMENT_FOND, surFond);
      window.removeEventListener(EVENEMENT_THEME, surTheme);
    };
  }, []);
  return (
    <>
      <Segment
        libelle="Place de l'orbe"
        options={PLACES_ORBE}
        valeur={fond ? "fond" : "panneau"}
        surChoix={(v) => {
          choisirFondEcran(v === "fond");
        }}
      />
      <p className="sec-texte">
        {theme === "presence"
          ? "L'orbe suit JARVIS : veille, écoute, réflexion, réponse et compactage (résumé en mémoire). La jauge sous l'orbe montre le niveau du micro quand il est ouvert."
          : "Choisissez d'abord le thème « Présence » (section Thème) : ce réglage est gardé pour lui."}
      </p>
    </>
  );
}

/** Une ligne « nom · valeur » d'un réglage simple. */
function Ligne({ nom, children, ok }: { nom: string; children: ReactNode; ok?: boolean | undefined }) {
  return (
    <li className="reglage-ligne">
      <span className="point-etat" data-ok={ok} aria-hidden="true" />
      <span className="reglage-ligne-nom">{nom}</span>
      <span className="reglage-ligne-valeur">{children}</span>
    </li>
  );
}

function VoixInstallees() {
  const [voix, setVoix] = useState(voixLocales);
  useEffect(() => {
    if (!("speechSynthesis" in window)) return;
    const relire = () => {
      setVoix(voixLocales());
    };
    window.speechSynthesis.addEventListener("voiceschanged", relire);
    return () => {
      window.speechSynthesis.removeEventListener("voiceschanged", relire);
    };
  }, []);
  if (!("speechSynthesis" in window)) return <p className="sec-texte">Ce navigateur ne sait pas lire à voix haute.</p>;
  if (!voix.length)
    return (
      <p className="sec-texte" data-etat="alerte">
        Aucune voix française locale sur cet appareil : JARVIS lit avec Piper s'il est prêt, sinon il reste muet plutôt que d'envoyer le texte à
        un service en ligne. Ajoutez une voix française dans les réglages de langue du système.
      </p>
    );
  return (
    <p className="sec-texte">
      Voix française de cet appareil : <b>{(voix.find((v) => v.defaut) ?? voix[0])?.nom}</b>
      {voix.length > 1 ? ` (${String(voix.length)} installées)` : ""}. Elle est locale : rien ne part en ligne.
    </p>
  );
}

const INSTALLEE = typeof window.matchMedia === "function" && window.matchMedia("(display-mode: standalone)").matches;

export function VueReglages(p: Props) {
  const [categorie, setCategorie] = useState<IdCategorie>(() => p.cible?.categorie ?? lireDerniereCategorie());
  // Téléphone : la liste des catégories, puis la page choisie (« Réglages » pour revenir). Adresse directe : la page.
  const [page, setPage] = useState(Boolean(p.cible?.categorie));
  const [recherche, setRecherche] = useState("");
  const [profil, setProfil] = useState(false);
  const corps = useRef<HTMLDivElement>(null);
  const idRecherche = useId();
  const resultats = chercherSections(recherche);
  const { surPosition } = p;

  const aller = (c: Cible, focus = true) => {
    setCategorie(c.categorie);
    setPage(true);
    setRecherche("");
    setProfil(false);
    ecrireDerniereCategorie(c.categorie);
    surPosition(c);
    // Après le rendu : la section (ou le haut de la catégorie) défile en vue et reçoit le focus ; elle reste ancrée
    // pendant que les sections au-dessus finissent de charger (sinon elles la repoussent hors de vue).
    ancre.current = c.section ? { id: `reglage-${c.section}`, jusqua: performance.now() + 8000 } : null;
    window.setTimeout(() => {
      const el = document.getElementById(c.section ? `reglage-${c.section}` : `reglages-${c.categorie}`);
      if (c.section) ancrer();
      else corps.current?.scrollTo({ top: 0 });
      if (focus) el?.querySelector<HTMLElement>("[data-titre]")?.focus({ preventScroll: true });
    }, 0);
  };
  const allerRef = useRef(aller);
  allerRef.current = aller;

  // Défile le corps (lui seul, pas la page) jusqu'à la section ancrée
  const ancre = useRef<{ id: string; jusqua: number } | null>(null);
  const ancrer = () => {
    const a = ancre.current;
    const boite = corps.current;
    const el = a && document.getElementById(a.id);
    if (!a || !boite || !el) return;
    if (performance.now() > a.jusqua) {
      ancre.current = null;
      return;
    }
    const marge = parseFloat(getComputedStyle(el).scrollMarginTop) || 0;
    boite.scrollTo({ top: boite.scrollTop + el.getBoundingClientRect().top - boite.getBoundingClientRect().top - marge });
  };
  const ancrerRef = useRef(ancrer);
  ancrerRef.current = ancrer;
  useEffect(() => {
    const boite = corps.current;
    if (!boite || typeof ResizeObserver === "undefined") return;
    const observateur = new ResizeObserver(() => {
      ancrerRef.current();
    });
    for (const enfant of Array.from(boite.children)) observateur.observe(enfant);
    // Dès que l'utilisateur fait défiler lui-même, l'ancre lâche
    const lacher = () => {
      ancre.current = null;
    };
    boite.addEventListener("wheel", lacher, { passive: true });
    boite.addEventListener("touchmove", lacher, { passive: true });
    boite.addEventListener("keydown", lacher);
    boite.addEventListener("pointerdown", lacher);
    return () => {
      observateur.disconnect();
      boite.removeEventListener("wheel", lacher);
      boite.removeEventListener("touchmove", lacher);
      boite.removeEventListener("keydown", lacher);
      boite.removeEventListener("pointerdown", lacher);
    };
  }, [categorie, recherche, profil, page]);

  const jeton = p.cible?.jeton;
  useEffect(() => {
    const c = p.cible;
    if (c?.categorie) allerRef.current({ categorie: c.categorie, ...(c.section ? { section: c.section } : {}) }, Boolean(c.section));
    else {
      surPosition({ categorie }); // dernière catégorie ouverte : l'adresse la donne aussi
      if (c?.recherche) {
        setRecherche(c.recherche);
        window.setTimeout(() => document.getElementById(idRecherche)?.focus(), 0);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- seul un nouveau jeton (nouvelle demande) déplace la vue
  }, [jeton]);

  const urgence = p.etat?.urgence.actif ?? false;
  const nbDemandes = p.etat?.demandes.length ?? 0;

  const contenu = (s: Section): ReactNode => {
    switch (s.id) {
      case "apercu": {
        const e = p.etat;
        if (!e) return <div className="squelette squelette--ligne" aria-busy="true" />;
        return (
          <ul className="reglage-lignes">
            <Ligne nom="JARVIS-Core" ok={!urgence}>
              {urgence ? "arrêt d'urgence" : "en ligne"} · v{e.version}
            </Ligne>
            <Ligne nom="Mémoire" ok={e.memoire.total > 0}>
              {e.memoire.total.toLocaleString("fr-FR")} souvenirs, dont {e.memoire.local_uniquement.toLocaleString("fr-FR")} privés
            </Ligne>
            {e.moteurs.map((m) => (
              <Ligne key={m.id} nom={m.nom} ok={m.disponible}>
                {m.disponible ? `${String(m.modeles.length)} modèle${m.modeles.length > 1 ? "s" : ""}` : "indisponible"}
              </Ligne>
            ))}
            <Ligne nom="Clés d'accès" ok={e.cles_acces > 0}>
              {e.cles_acces ? String(e.cles_acces) : "aucune : les actions 🔴 ne peuvent pas être approuvées"}
            </Ligne>
            <Ligne nom="Demandes" ok={nbDemandes === 0}>
              {nbDemandes ? (
                <button type="button" className="etat-lien" onClick={p.surDemandes}>
                  {nbDemandes} en attente de votre accord
                </button>
              ) : (
                "aucune en attente"
              )}
            </Ligne>
          </ul>
        );
      }
      case "rapides":
        return (
          <div className="reglage-controles">
            <div className="reglage-controle">
              <span className="reglage-controle-nom">Voix</span>
              <ChoixVoix lecteur={p.lecteur} />
            </div>
            <div className="reglage-controle">
              <span className="reglage-controle-nom">Animations</span>
              <ChoixAnimationsAppareil />
            </div>
            <div className="reglage-controle">
              <SelecteurTheme libelleVisible className="reglage-theme" />
            </div>
          </div>
        );
      case "themes":
        return (
          <>
            <SelecteurTheme libelleVisible className="reglage-theme" />
            <p className="sec-texte">Gardé sur cet appareil. Aussi : « /theme clair », ou la palette (Ctrl+K).</p>
          </>
        );
      case "presence":
        return <ChoixPresence />;
      case "animations":
        return (
          <>
            <ChoixAnimationsAppareil />
            <p className="sec-texte">« Selon le système » suit le réglage d'accessibilité « réduire les animations » de l'appareil.</p>
          </>
        );
      case "clavier":
        return (
          <>
            <dl className="reglage-raccourcis">
              {RACCOURCIS.map((r) => (
                <div key={r.touches} className="reglage-raccourci">
                  <dt>
                    <kbd>{r.touches}</kbd>
                  </dt>
                  <dd>{r.effet}</dd>
                </div>
              ))}
            </dl>
            <div className="carte-co-actions">
              <button type="button" className="btn btn-mini" onClick={p.surPalette}>
                Ouvrir la palette
              </button>
              <button type="button" className="btn btn-discret btn-mini" onClick={p.surAide}>
                Toutes les commandes « / »
              </button>
            </div>
          </>
        );
      case "pilotage":
        return <ReglagePilotage surNotifier={p.surNotifier} />;
      case "commandes-rapides":
        return <CommandesRapides surNotifier={p.surNotifier} />;
      case "lecture":
        return (
          <>
            <ChoixVoix lecteur={p.lecteur} />
            <ReglageSynthese lecteur={p.lecteur} surNotifier={p.surNotifier} />
            <VoixInstallees />
            <p className="sec-texte">Ctrl+M ou « /silence » coupe la voix tout de suite.</p>
          </>
        );
      case "ecoute": {
        const micro = "mediaDevices" in navigator && typeof MediaRecorder !== "undefined";
        const partage = "mediaDevices" in navigator && "getDisplayMedia" in navigator.mediaDevices;
        return (
          <>
            <ul className="reglage-lignes">
              <Ligne nom="Micro" ok={micro}>
                {micro ? "disponible (dictée et mains libres dans la console)" : "indisponible dans ce navigateur"}
              </Ligne>
              <Ligne nom="Partage d'écran" ok={partage}>
                {partage ? "disponible (« Écran » dans la console, sur demande seulement)" : "indisponible dans ce navigateur"}
              </Ligne>
            </ul>
            <p className="sec-texte">
              La parole est transcrite sur le PC (faster-whisper) ; en mains libres, dites « Jarvis, … ». Le modèle de transcription se choisit
              dans la configuration locale (<code>JARVIS2_MODELE_VOIX</code>).
            </p>
          </>
        );
      }
      case "eveil":
        return <ReglagesEveil surNotifier={p.surNotifier} />;
      case "transcription":
        return <EtatTranscriptionVoix />;
      case "proprietaire":
        return <ReglageProprietaire />;
      case "dictee":
        return <ReglageDictee />;
      case "connecteurs":
        return <VueConnecteurs surChangement={p.surChangement} />;
      case "couts":
        return <VueCouts />;
      case "accueil-matin":
        return <ReglagesMatin surRejouer={p.surRejouerMatin} surNotifier={p.surNotifier} />;
      case "installation":
        return (
          <>
            <Verifications surChangement={p.surChangement} />
            <button type="button" className="btn btn-mini" onClick={p.surInstallation}>
              Rouvrir l'assistant d'installation
            </button>
          </>
        );
      case "blocs-memoire":
        return <SectionMemoire surChangement={p.surChangement} />;
      case "profil":
        return (
          <button
            type="button"
            className="btn btn-mini"
            onClick={() => {
              setProfil(true);
            }}
          >
            Ouvrir le profil
          </button>
        );
      case "urgence":
        return urgence ? (
          <>
            <p className="sec-texte" data-etat="alerte">
              L'arrêt d'urgence est actif : plus aucune action n'est acceptée.
            </p>
            <button type="button" className="btn btn-mini" onClick={p.surLeverUrgence}>
              Lever l'arrêt (clé d'accès)
            </button>
          </>
        ) : (
          <>
            <p className="sec-texte">Arrête tout de suite les réponses, les missions et les actions. Aussi : « /urgence ».</p>
            <button type="button" className="btn btn-rouge btn-mini" onClick={p.surUrgence}>
              Arrêt d'urgence
            </button>
          </>
        );
      case "cles-acces":
        return <PanneauSecurite nbCles={p.etat?.cles_acces ?? 0} surChangement={p.surChangement} blocs={["cles"]} />;
      case "donnees":
        return <FluxDonnees surNotifier={p.surNotifier} />;
      case "audit":
        return <PanneauSecurite nbCles={p.etat?.cles_acces ?? 0} surChangement={p.surChangement} blocs={["audit"]} />;
      case "regles-protection":
        return <ReglesProtection surChangement={p.surChangement} />;
      case "autorisations":
        return <AutorisationsPermanentes surNotifier={p.surNotifier} />;
      case "appareils":
        return <PanneauSecurite nbCles={p.etat?.cles_acces ?? 0} surChangement={p.surChangement} blocs={["appareils"]} />;
      case "telephone":
        return <Telephone />;
      case "notifications":
        return <NotificationsTelephone />;
      case "envois":
        return <EnvoisTelephone />;
      case "partages":
        return <PartagesRecus />;
      case "bureau":
        return (
          <ul className="reglage-lignes">
            <Ligne nom="Montrer JARVIS">Ctrl+Maj+J (sinon Ctrl+Alt+J)</Ligne>
            <Ligne nom="Parler (micro)">Ctrl+Maj+Espace (sinon Ctrl+Alt+Espace)</Ligne>
            <Ligne nom="Regarder l'écran">Ctrl+Maj+Impr (sinon Ctrl+Alt+Impr)</Ligne>
            <Ligne nom="Gadget de bureau">Icône de notification › Gadget de bureau</Ligne>
            <Ligne nom="Liens jarvis://">ouvrir/&lt;vue&gt;, nouvelle, ecouter, ecran, dire?texte=…, conversation/&lt;id&gt;</Ligne>
          </ul>
        );
      case "veille-claude":
        return <VeilleClaude />;
      case "ressources-pc":
        return <RessourcesDuPC surNotifier={p.surNotifier} surChangement={p.surChangement} surDemandes={p.surDemandes} />;
      case "mode-jeu":
        return <ModeJeuPC surNotifier={p.surNotifier} surChangement={p.surChangement} surDemandes={p.surDemandes} />;
      case "controle-pc":
        return <ControlePC surNotifier={p.surNotifier} surChangement={p.surChangement} surDemandes={p.surDemandes} />;
      case "version":
        return (
          <ul className="reglage-lignes">
            <Ligne nom="JARVIS-Core">{p.etat ? `v${p.etat.version}` : "…"}</Ligne>
            <Ligne nom="Cet appareil">{INSTALLEE ? "application installée" : "dans le navigateur"}</Ligne>
          </ul>
        );
      default:
        return null;
    }
  };

  const nav = (
    <nav className="reglages-nav" aria-label="Catégories de réglages">
      <ul>
        {CATEGORIES.map((c) => (
          <li key={c.id}>
            <button
              type="button"
              className="reglages-categorie"
              aria-current={c.id === categorie && !recherche ? "page" : undefined}
              onClick={() => {
                aller({ categorie: c.id });
              }}
            >
              <span className="reglages-categorie-nom">{c.nom}</span>
              <span className="reglages-categorie-desc">{c.description}</span>
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );

  const info = infoCategorie(categorie);
  return (
    <div className="reglages" data-page={page || recherche ? "" : undefined}>
      <form
        className="reglages-recherche"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          const premier = resultats[0];
          if (premier) aller({ categorie: premier.categorie, section: premier.id });
        }}
      >
        <label htmlFor={idRecherche} className="visuellement-cache">
          Chercher un réglage
        </label>
        <input
          id={idRecherche}
          type="search"
          className="reglages-champ"
          placeholder="Chercher un réglage (voix, plafond, météo…)"
          value={recherche}
          autoComplete="off"
          onChange={(e) => {
            setRecherche(e.target.value);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape" && recherche) {
              e.stopPropagation();
              setRecherche("");
            }
          }}
        />
      </form>

      {nav}

      <div className="reglages-corps" ref={corps}>
        {recherche.trim() ? (
          <section className="reglages-resultats" aria-label="Résultats de la recherche">
            <p className="sec-texte" role="status">
              {resultats.length ? `${String(resultats.length)} réglage${resultats.length > 1 ? "s" : ""}` : "Aucun réglage ne correspond. Essayez un autre mot."}
            </p>
            <ul className="reglages-liste-resultats">
              {resultats.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    className="reglages-resultat"
                    onClick={() => {
                      aller({ categorie: s.categorie, section: s.id });
                    }}
                  >
                    <span className="reglages-resultat-titre">{s.titre}</span>
                    <span className="reglages-resultat-chemin">{infoCategorie(s.categorie).nom}</span>
                    <span className="reglages-resultat-desc">{s.description}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ) : profil ? (
          <VueProfil
            surRetour={() => {
              setProfil(false);
            }}
          />
        ) : (
          <div className="reglages-page" id={`reglages-${categorie}`}>
            <header className="reglages-page-tete">
              <button
                type="button"
                className="btn btn-discret btn-mini reglages-retour"
                onClick={() => {
                  setPage(false);
                }}
              >
                <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M15 6l-6 6 6 6" />
                </svg>
                Réglages
              </button>
              <h3 className="reglages-page-titre" tabIndex={-1} data-titre="">
                {info.nom}
              </h3>
              <p className="reglages-page-desc">{info.description}</p>
            </header>
            {sectionsDe(categorie).map((s) => (
              <section key={s.id} className="reglage" id={`reglage-${s.id}`} aria-labelledby={`reglage-${s.id}-titre`}>
                <div className="reglage-tete">
                  <h4 className="reglage-titre" id={`reglage-${s.id}-titre`} tabIndex={-1} data-titre="">
                    {s.titre}
                  </h4>
                  <p className="reglage-desc">{s.description}</p>
                </div>
                <div className="reglage-corps">{contenu(s)}</div>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
