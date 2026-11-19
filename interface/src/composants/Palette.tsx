import { useEffect, useId, useMemo, useRef, useState } from "react";

import { chercherConversations } from "../api";
import { type Commande, COMMANDES, filtrerCommandes, type IdCommande, normaliser, RACCOURCIS } from "../commandes";
import { THEMES, type Theme } from "../theme";
import type { ResumeConversation } from "../types";

export type ModePalette = "tout" | "conversations" | "urgence";

interface Element {
  cle: string;
  groupe: "Commandes" | "Thèmes" | "Conversations";
  libelle: string;
  detail?: string;
  raccourci?: string;
  danger?: boolean;
  executer: () => void;
}

interface PaletteProps {
  mode: ModePalette;
  requeteInitiale?: string;
  conversations: ResumeConversation[];
  urgenceActive: boolean;
  surFermer: () => void;
  surCommande: (id: IdCommande, argument?: string) => void;
  surTheme: (theme: Theme) => void;
  surOuvrirConversation: (id: string) => void;
  surUrgence: () => void;
}

/** Fenêtre modale : un champ en haut, la liste filtrée dessous (flèches, Entrée, Échap). */
function Fenetre({ etiquette, surFermer, children, className }: { etiquette: string; surFermer: () => void; children: React.ReactNode; className?: string }) {
  const fenetre = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = fenetre.current;
    const avant = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (d && !d.open) d.showModal();
    return () => {
      d?.close();
      avant?.focus(); // le focus revient où il était
    };
  }, []);
  return (
    <dialog
      ref={fenetre}
      className={["palette", className].filter(Boolean).join(" ")}
      aria-label={etiquette}
      onCancel={(e) => {
        e.preventDefault();
        surFermer();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation(); // Échap ferme la palette sans arrêter la réponse en cours
          e.preventDefault();
          surFermer();
        }
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) surFermer();
      }}
    >
      {children}
    </dialog>
  );
}

function Touches({ touches }: { touches: string }) {
  return (
    <span className="palette-touches">
      {touches.split("+").map((t) => (
        <kbd key={t}>{t}</kbd>
      ))}
    </span>
  );
}

export function Palette(p: PaletteProps) {
  const [requete, setRequete] = useState(p.requeteInitiale ?? "");
  const [actif, setActif] = useState(0);
  const [confirmer, setConfirmer] = useState(p.mode === "urgence");
  const [trouvees, setTrouvees] = useState<ResumeConversation[] | null>(null);
  const [recherche, setRecherche] = useState(false);
  const idListe = useId();
  const liste = useRef<HTMLUListElement>(null);
  const seulementConversations = p.mode === "conversations";

  // Conversations : recherche côté Core (titres et messages) dès 2 caractères, après une courte pause de frappe
  const texte = requete.trim();
  useEffect(() => {
    if (texte.length < 2) {
      setTrouvees(null);
      return;
    }
    let annule = false;
    setRecherche(true);
    const minuterie = window.setTimeout(() => {
      chercherConversations(texte)
        .then((r) => {
          if (!annule) setTrouvees(r.conversations.slice(0, 6));
        })
        .catch(() => {
          if (!annule) setTrouvees([]);
        })
        .finally(() => {
          if (!annule) setRecherche(false);
        });
    }, 220);
    return () => {
      annule = true;
      window.clearTimeout(minuterie);
    };
  }, [texte]);

  const elements = useMemo<Element[]>(() => {
    const sortie: Element[] = [];
    if (!seulementConversations) {
      for (const c of filtrerCommandes(texte, COMMANDES.filter((x) => x.id !== "palette"))) {
        sortie.push({
          cle: c.id,
          groupe: "Commandes",
          libelle: c.nom,
          detail: c.slash ? `/${c.slash}` : c.description,
          ...(c.raccourci ? { raccourci: c.raccourci } : {}),
          ...(c.danger ? { danger: true } : {}),
          executer: () => {
            if (c.id === "urgence") setConfirmer(true);
            else p.surCommande(c.id);
          },
        });
      }
      const n = normaliser(texte);
      if (n) {
        for (const t of THEMES) {
          if (`theme ${normaliser(t.nom)}`.includes(n) || normaliser(t.nom).includes(n)) {
            sortie.push({ cle: `theme:${t.id}`, groupe: "Thèmes", libelle: `Thème : ${t.nom}`, executer: () => { p.surTheme(t.id); } });
          }
        }
      }
    }
    const convs = trouvees ?? (texte ? [] : p.conversations.slice(0, seulementConversations ? 8 : 4));
    for (const c of convs) {
      sortie.push({
        cle: `conv:${c.id}`,
        groupe: "Conversations",
        libelle: c.titre,
        detail: new Date(c.maj_le).toLocaleDateString("fr-FR", { day: "numeric", month: "short" }),
        executer: () => { p.surOuvrirConversation(c.id); },
      });
    }
    return sortie;
  }, [texte, trouvees, p, seulementConversations]);

  useEffect(() => {
    setActif(0);
  }, [texte, trouvees]);

  useEffect(() => {
    liste.current?.querySelector<HTMLElement>(`[data-indice="${String(actif)}"]`)?.scrollIntoView({ block: "nearest" });
  }, [actif]);

  if (confirmer) {
    return (
      <Fenetre etiquette="Confirmer l'arrêt d'urgence" surFermer={p.surFermer} className="palette--confirmation">
        <div className="palette-confirmation" aria-labelledby={`${idListe}-titre`} aria-describedby={`${idListe}-texte`}>
          <p className="palette-confirmation-titre" id={`${idListe}-titre`}>
            {p.urgenceActive ? "L'arrêt d'urgence est déjà actif" : "Tout arrêter maintenant ?"}
          </p>
          <p className="palette-confirmation-texte" id={`${idListe}-texte`}>
            {p.urgenceActive
              ? "Plus aucune action n'est acceptée. Pour le lever, utilisez le bandeau rouge (clé d'accès)."
              : "Les réponses en cours sont interrompues et plus aucune action n'est acceptée tant que l'arrêt n'est pas levé (clé d'accès)."}
          </p>
          <div className="palette-confirmation-actions">
            <button type="button" className="btn" autoFocus onClick={p.surFermer}>
              {p.urgenceActive ? "Fermer" : "Annuler"}
            </button>
            {!p.urgenceActive && (
              <button type="button" className="btn btn-rouge" onClick={p.surUrgence}>
                Arrêter tout
              </button>
            )}
          </div>
        </div>
      </Fenetre>
    );
  }

  const choisi = elements[actif];
  return (
    <Fenetre etiquette={seulementConversations ? "Chercher une conversation" : "Palette de commandes"} surFermer={p.surFermer}>
      <div className="palette-champ">
        <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="11" cy="11" r="6" />
          <path d="M20 20l-4.5-4.5" />
        </svg>
        <input
          type="text"
          role="combobox"
          aria-expanded="true"
          aria-controls={idListe}
          aria-autocomplete="list"
          aria-activedescendant={choisi ? `${idListe}-${choisi.cle}` : undefined}
          aria-label={seulementConversations ? "Chercher dans les conversations" : "Chercher une commande ou une conversation"}
          placeholder={seulementConversations ? "Chercher dans les conversations…" : "Commande, vue, thème, conversation…"}
          autoComplete="off"
          spellCheck={false}
          autoFocus
          value={requete}
          onChange={(e) => {
            setRequete(e.target.value);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActif((i) => (elements.length ? (i + 1) % elements.length : 0));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActif((i) => (elements.length ? (i - 1 + elements.length) % elements.length : 0));
            } else if (e.key === "Home" && e.ctrlKey) {
              setActif(0);
            } else if (e.key === "End" && e.ctrlKey) {
              setActif(Math.max(0, elements.length - 1));
            } else if (e.key === "Enter" && !e.nativeEvent.isComposing) {
              e.preventDefault();
              choisi?.executer();
            }
          }}
        />
        <kbd className="palette-echap">Échap</kbd>
      </div>
      <ul className="palette-liste" role="listbox" id={idListe} ref={liste} aria-label="Résultats">
        {elements.map((el, i) => (
          <PaletteLigne key={el.cle} el={el} i={i} precedent={elements[i - 1]} actif={i === actif} idListe={idListe} surSurvol={setActif} />
        ))}
      </ul>
      {!elements.length && (
        <p className="palette-vide" role="status">
          {recherche ? "Recherche…" : texte ? `Rien ne correspond à « ${texte} ». Essayez « thème », « mémoire » ou les mots d'une conversation.` : "Aucune conversation pour l'instant."}
        </p>
      )}
      <p className="palette-pied">
        <span><kbd>↑</kbd><kbd>↓</kbd> choisir</span>
        <span><kbd>Entrée</kbd> lancer</span>
        <span>Dans la saisie : <kbd>/</kbd> commandes</span>
      </p>
    </Fenetre>
  );
}

function PaletteLigne({ el, i, precedent, actif, idListe, surSurvol }: { el: Element; i: number; precedent: Element | undefined; actif: boolean; idListe: string; surSurvol: (i: number) => void }) {
  return (
    <>
      {precedent?.groupe !== el.groupe && (
        <li className="palette-groupe" role="presentation">
          {el.groupe}
        </li>
      )}
      <li
        id={`${idListe}-${el.cle}`}
        role="option"
        aria-selected={actif}
        data-indice={i}
        data-danger={el.danger || undefined}
        className="palette-option"
        onMouseMove={() => {
          if (!actif) surSurvol(i);
        }}
        onClick={el.executer}
      >
        <span className="palette-libelle">{el.libelle}</span>
        {el.detail && <span className="palette-detail">{el.detail}</span>}
        {el.raccourci && <Touches touches={el.raccourci} />}
      </li>
    </>
  );
}

/** Aide : raccourcis clavier et commandes « / ». */
export function Aide({ surFermer }: { surFermer: () => void }) {
  const commandes: Commande[] = COMMANDES.filter((c) => c.slash);
  return (
    <Fenetre etiquette="Aide : commandes et raccourcis" surFermer={surFermer} className="palette--aide">
      <div className="aide">
        <div className="aide-tete">
          <h2 className="aide-titre">Commandes et raccourcis</h2>
          <button type="button" className="icone-btn petit" aria-label="Fermer l'aide" autoFocus onClick={surFermer}>
            <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>
        <section aria-labelledby="aide-raccourcis">
          <h3 className="aide-section" id="aide-raccourcis">
            Clavier
          </h3>
          <dl className="aide-liste">
            {RACCOURCIS.map((r) => (
              <div key={r.touches} className="aide-ligne">
                <dt>
                  <Touches touches={r.touches} />
                </dt>
                <dd>{r.effet}</dd>
              </div>
            ))}
          </dl>
        </section>
        <section aria-labelledby="aide-slash">
          <h3 className="aide-section" id="aide-slash">
            Dans la saisie
          </h3>
          <dl className="aide-liste">
            {commandes.map((c) => (
              <div key={c.id} className="aide-ligne">
                <dt>
                  <code>
                    /{c.slash}
                    {c.argument ? ` [${c.argument}]` : ""}
                  </code>
                </dt>
                <dd>{c.nom}</dd>
              </div>
            ))}
            <div className="aide-ligne">
              <dt>
                <code>//texte</code>
              </dt>
              <dd>Envoyer un message qui commence par « / »</dd>
            </div>
          </dl>
        </section>
        <p className="aide-note">Images : collez-les (Ctrl+V), glissez-les ou utilisez le trombone. 5 par message ; elles ne sont pas gardées après la réponse.</p>
      </div>
    </Fenetre>
  );
}
