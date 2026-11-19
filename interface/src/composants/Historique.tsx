import { useEffect, useRef, useState } from "react";

import { chercherConversations, modifierConversation } from "../api";
import type { ResumeConversation } from "../types";

const JOUR = 86_400_000;

function groupe(date: Date, maintenant: Date): string {
  const debutJour = new Date(maintenant.getFullYear(), maintenant.getMonth(), maintenant.getDate()).getTime();
  const t = date.getTime();
  if (t >= debutJour) return "Aujourd'hui";
  if (t >= debutJour - JOUR) return "Hier";
  if (t >= debutJour - 6 * JOUR) return "7 derniers jours";
  return "Plus ancien";
}

const HEURE = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });
const DATE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short" });

function quand(date: Date, maintenant: Date): string {
  return maintenant.getTime() - date.getTime() < JOUR && date.getDate() === maintenant.getDate()
    ? HEURE.format(date)
    : DATE.format(date);
}

interface Props {
  conversations: ResumeConversation[];
  active: string | null;
  surChoisir: (id: string) => void;
  /** Une conversation a changé (titre, épingle, restauration) : la liste de l'application suit. */
  surMiseAJour: (conversation: ResumeConversation) => void;
  surErreur: (message: string) => void;
}

/** Historique : recherche (titres et messages), renommer, épingler ; archives consultables et restaurables. */
export function ListeConversations({ conversations, active, surChoisir, surMiseAJour, surErreur }: Props) {
  const [recherche, setRecherche] = useState("");
  const [archives, setArchives] = useState(false);
  const [trouvees, setTrouvees] = useState<ResumeConversation[] | null>(null);
  const [chargement, setChargement] = useState(false);
  const [edition, setEdition] = useState<{ id: string; titre: string } | null>(null);
  const saisie = useRef<HTMLInputElement>(null);

  // Recherche côté Core (titres et contenu des messages), après une courte pause de frappe
  const texte = recherche.trim();
  useEffect(() => {
    if (!texte && !archives) {
      setTrouvees(null);
      return;
    }
    let annule = false;
    setChargement(true);
    const minuterie = window.setTimeout(() => {
      chercherConversations(texte, archives)
        .then((r) => {
          if (!annule) setTrouvees(r.conversations);
        })
        .catch((e: unknown) => {
          if (!annule) surErreur(e instanceof Error ? e.message : "Recherche impossible.");
        })
        .finally(() => {
          if (!annule) setChargement(false);
        });
    }, 250);
    return () => {
      annule = true;
      window.clearTimeout(minuterie);
    };
  }, [texte, archives, surErreur]);

  useEffect(() => {
    if (edition) saisie.current?.select();
  }, [edition]);

  const appliquer = (id: string, changement: { titre?: string; epinglee?: boolean; archivee?: false }) => {
    modifierConversation(id, changement)
      .then(({ conversation }) => {
        surMiseAJour(conversation);
        setTrouvees((liste) =>
          liste
            ?.map((c) => (c.id === id ? conversation : c))
            .filter((c) => !(archives && changement.archivee === false && c.id === id)) ?? null,
        );
      })
      .catch((e: unknown) => {
        surErreur(e instanceof Error ? e.message : "Modification impossible.");
      });
  };

  const valider = () => {
    if (!edition) return;
    const titre = edition.titre.trim();
    const avant = (trouvees ?? conversations).find((c) => c.id === edition.id)?.titre;
    setEdition(null);
    if (titre && titre !== avant) appliquer(edition.id, { titre });
  };

  const liste = trouvees ?? conversations;
  const maintenant = new Date();
  const groupes = new Map<string, ResumeConversation[]>();
  for (const c of liste) {
    const g = archives ? "Archivées" : c.epinglee ? "Épinglées" : groupe(new Date(c.maj_le), maintenant);
    groupes.set(g, [...(groupes.get(g) ?? []), c]);
  }

  return (
    <div className="hist-cadre">
      <div className="hist-outils">
        <label className="hist-recherche">
          <span className="visuellement-cache">Chercher dans les conversations</span>
          <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="11" cy="11" r="6.5" />
            <path d="m16 16 4.5 4.5" />
          </svg>
          <input
            type="search"
            value={recherche}
            placeholder={archives ? "Chercher (archives)" : "Chercher"}
            title="Cherche dans les titres et le contenu des messages"
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
        </label>
        <button
          type="button"
          className="btn btn-discret btn-mini"
          aria-pressed={archives}
          onClick={() => {
            setArchives((a) => !a);
          }}
        >
          Archives
        </button>
      </div>

      {chargement && trouvees === null ? (
        <p className="hist-etat" role="status">
          Recherche…
        </p>
      ) : !liste.length ? (
        <div className="vide vide--calme">
          <p className="vide-titre">{texte ? "Aucun résultat" : archives ? "Aucune archive" : "Aucune conversation"}</p>
          <p>
            {texte
              ? "Rien ne correspond, ni dans les titres ni dans les messages."
              : archives
                ? "Les conversations archivées restent ici, restaurables."
                : "Écrivez à JARVIS : chaque échange est gardé ici."}
          </p>
        </div>
      ) : (
        <nav className="hist" aria-label={archives ? "Conversations archivées" : "Conversations"}>
          {[...groupes].map(([nom, items]) => (
            <div className="hist-groupe" key={nom}>
              <h3 className="hist-groupe-titre">{nom}</h3>
              <ul>
                {items.map((c) => (
                  <li key={c.id} className="hist-ligne" data-active={c.id === active || undefined}>
                    {edition?.id === c.id ? (
                      <input
                        ref={saisie}
                        className="hist-edition"
                        aria-label="Nouveau titre"
                        maxLength={120}
                        value={edition.titre}
                        onChange={(e) => {
                          setEdition({ id: c.id, titre: e.target.value });
                        }}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") valider();
                          if (e.key === "Escape") {
                            e.stopPropagation();
                            setEdition(null);
                          }
                        }}
                        onBlur={valider}
                      />
                    ) : (
                      <button
                        type="button"
                        className="hist-item"
                        aria-label={`${c.titre} — ${quand(new Date(c.maj_le), maintenant)}, ${String(c.nb_messages)} message${c.nb_messages > 1 ? "s" : ""}`}
                        aria-current={c.id === active ? "true" : undefined}
                        onClick={() => {
                          surChoisir(c.id);
                        }}
                      >
                        <span className="hist-titre">
                          {c.epinglee && !archives && (
                            <svg className="ico hist-epingle" viewBox="0 0 24 24" aria-label="Épinglée">
                              <path d="M9 4h6l-1 6 3 3H7l3-3zM12 13v7" />
                            </svg>
                          )}
                          {c.titre}
                        </span>
                        <span className="hist-meta">
                          {quand(new Date(c.maj_le), maintenant)} · {c.nb_messages} message{c.nb_messages > 1 ? "s" : ""}
                          {c.titre_source === "auto" && " · titre par JARVIS"}
                        </span>
                      </button>
                    )}
                    {edition?.id !== c.id && (
                      <div className="hist-actions">
                        {archives ? (
                          <button
                            type="button"
                            className="btn btn-discret btn-mini"
                            onClick={() => {
                              appliquer(c.id, { archivee: false });
                            }}
                          >
                            Restaurer
                          </button>
                        ) : (
                          <>
                            <button
                              type="button"
                              className="icone-btn petit"
                              aria-label={`Renommer « ${c.titre} »`}
                              title="Renommer"
                              onClick={() => {
                                setEdition({ id: c.id, titre: c.titre });
                              }}
                            >
                              <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
                                <path d="M4 20h4L19 9l-4-4L4 16zM14 6l4 4" />
                              </svg>
                            </button>
                            <button
                              type="button"
                              className="icone-btn petit"
                              aria-label={c.epinglee ? `Désépingler « ${c.titre} »` : `Épingler « ${c.titre} »`}
                              aria-pressed={c.epinglee}
                              title={c.epinglee ? "Désépingler" : "Épingler en tête"}
                              onClick={() => {
                                appliquer(c.id, { epinglee: !c.epinglee });
                              }}
                            >
                              <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
                                <path d="M9 4h6l-1 6 3 3H7l3-3zM12 13v7" />
                              </svg>
                            </button>
                          </>
                        )}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
      )}
    </div>
  );
}
