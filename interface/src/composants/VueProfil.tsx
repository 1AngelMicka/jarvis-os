import { useCallback, useEffect, useRef, useState } from "react";

import {
  lireProfil,
  lireSectionProfil,
  repondreProfil,
  retirerReponseProfil,
  transcrireAudio,
  type EtatProfil,
  type QuestionProfil,
} from "../api";
import { Enregistreur, LecteurVocal } from "../voix";
import "../styles/profil.css";

type Dictee = "repos" | "ecoute" | "transcription";

interface Entretien {
  section: string;
  titre: string;
  description: string;
  questions: QuestionProfil[];
  index: number;
}

function Jauge({ valeur, total, libelle }: { valeur: number; total: number; libelle: string }) {
  const pourcentage = total ? Math.round((100 * valeur) / total) : 0;
  return (
    <div className="progression" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={valeur} aria-label={libelle}>
      <span style={{ width: `${String(pourcentage)}%` }} />
    </div>
  );
}

/** Profil guidé : questionnaire par sections, reprise là où l'on s'est arrêté, entretien vocal (question lue à voix
 * haute, réponse dictée). Chaque réponse entre en mémoire ; une réponse privée reste sur les appareils. */
export function VueProfil({ surRetour }: { surRetour: () => void }) {
  const [etat, setEtat] = useState<EtatProfil | null>(null);
  const [entretien, setEntretien] = useState<Entretien | null>(null);
  const [brouillon, setBrouillon] = useState("");
  const [prive, setPrive] = useState(false);
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [annonce, setAnnonce] = useState("");
  const [vocal, setVocal] = useState(false);
  const [dictee, setDictee] = useState<Dictee>("repos");
  const lecteur = useRef(new LecteurVocal());
  const enregistreur = useRef<Enregistreur | null>(null);
  const champ = useRef<HTMLTextAreaElement>(null);

  const question = entretien ? entretien.questions[entretien.index] : undefined;
  const micro = typeof navigator !== "undefined" && "mediaDevices" in navigator && typeof MediaRecorder !== "undefined";

  const rafraichir = useCallback(() => {
    return lireProfil()
      .then(setEtat)
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Profil illisible.");
      });
  }, []);

  useEffect(() => {
    void rafraichir();
    const l = lecteur.current;
    return () => {
      l.arreter();
      void enregistreur.current?.arreter();
    };
  }, [rafraichir]);

  const dire = useCallback((texte: string) => {
    const l = lecteur.current;
    l.arreter();
    l.actif = true;
    l.pousser(`${texte}\n`);
    l.finir();
  }, []);

  // À chaque question : brouillon = réponse existante, confidentialité de la réponse (ou de la section), lecture
  // à voix haute en entretien vocal.
  useEffect(() => {
    if (!entretien || !question) return;
    setBrouillon(question.reponse?.texte ?? "");
    setPrive(question.reponse?.prive ?? etat?.sections.find((s) => s.id === entretien.section)?.prive ?? false);
    if (vocal) dire(question.texte);
    champ.current?.focus({ preventScroll: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- seulement au changement de question
  }, [question?.id, vocal]);

  const ouvrir = useCallback(
    (sectionId: string, questionId?: string) => {
      setErreur(null);
      setAnnonce("");
      lireSectionProfil(sectionId)
        .then((s) => {
          const libre = s.questions.findIndex((q) => !q.reponse);
          const voulu = questionId ? s.questions.findIndex((q) => q.id === questionId) : -1;
          setEntretien({
            section: s.id,
            titre: s.titre,
            description: s.description,
            questions: s.questions,
            index: voulu >= 0 ? voulu : Math.max(libre, 0),
          });
        })
        .catch((e: unknown) => {
          setErreur(e instanceof Error ? e.message : "Section illisible.");
        });
    },
    [],
  );

  const fermer = () => {
    lecteur.current.arreter();
    setEntretien(null);
    void rafraichir();
  };

  const aller = (index: number) => {
    if (!entretien) return;
    if (index < entretien.questions.length) {
      setEntretien({ ...entretien, index });
      return;
    }
    // Fin de la section : section suivante non terminée, sinon retour au sommaire
    void lireProfil().then((e) => {
      setEtat(e);
      const ordre = e.sections.map((s) => s.id);
      const suivante = e.sections.find((s, i) => i > ordre.indexOf(entretien.section) && s.repondues < s.total);
      if (suivante) {
        setAnnonce(`Section « ${entretien.titre} » terminée.`);
        ouvrir(suivante.id);
      } else {
        setEntretien(null);
        setAnnonce(e.repondues === e.total ? "Profil complet. Merci !" : `Section « ${entretien.titre} » terminée.`);
      }
    });
  };

  const enregistrer = () => {
    if (!entretien || !question) return;
    const texte = brouillon.trim();
    if (!texte) {
      aller(entretien.index + 1);
      return;
    }
    setEnvoi(true);
    setErreur(null);
    repondreProfil(question.id, texte, prive)
      .then((r) => {
        const questions = entretien.questions.map((q) => (q.id === question.id ? { ...q, reponse: r.reponse } : q));
        setEntretien({ ...entretien, questions });
        setAnnonce(r.modifiee ? (r.reponse.prive ? "Retenu, en privé." : "Retenu.") : "Inchangé.");
        if (r.modifiee) void rafraichir();
        const suite = entretien.index + 1;
        if (suite < questions.length) setEntretien({ ...entretien, questions, index: suite });
        else aller(suite);
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Réponse non enregistrée.");
      })
      .finally(() => {
        setEnvoi(false);
      });
  };

  const retirer = () => {
    if (!entretien || !question?.reponse) return;
    retirerReponseProfil(question.id)
      .then(() => {
        const questions = entretien.questions.map((q) => (q.id === question.id ? { ...q, reponse: null } : q));
        setEntretien({ ...entretien, questions });
        setBrouillon("");
        setAnnonce("Réponse retirée (gardée dans l'historique de la mémoire).");
        void rafraichir();
      })
      .catch((e: unknown) => {
        setErreur(e instanceof Error ? e.message : "Impossible de retirer la réponse.");
      });
  };

  const basculerDictee = () => {
    if (dictee === "ecoute") {
      const rec = enregistreur.current;
      enregistreur.current = null;
      setDictee("transcription");
      void (rec?.arreter() ?? Promise.resolve(new Blob()))
        .then((audio) => (audio.size ? transcrireAudio(audio) : { texte: "" }))
        .then((r) => {
          const dit = r.texte.trim();
          if (dit) setBrouillon((b) => (b.trim() ? `${b.trimEnd()} ${dit}` : dit));
          else setAnnonce("Rien entendu : réessayez.");
        })
        .catch((e: unknown) => {
          setErreur(e instanceof Error ? e.message : "Transcription impossible.");
        })
        .finally(() => {
          setDictee("repos");
          champ.current?.focus();
        });
      return;
    }
    lecteur.current.arreter();
    const rec = new Enregistreur();
    rec
      .demarrer()
      .then(() => {
        enregistreur.current = rec;
        setDictee("ecoute");
      })
      .catch(() => {
        setErreur("Micro inaccessible : autorisez-le dans le navigateur.");
      });
  };

  const entete = (
    <div className="profil-tete">
      <div className="profil-tete-texte">
        <h2 className="profil-titre">Profil guidé</h2>
        <p className="profil-sous-titre">
          {etat ? (
            <>
              <strong>{etat.repondues}</strong> réponse{etat.repondues > 1 ? "s" : ""} sur {etat.total} · {etat.pourcentage} %
              {etat.heritees > 0 && <> · {etat.heritees} héritée{etat.heritees > 1 ? "s" : ""} de JARVIS v1</>}
            </>
          ) : (
            "Chargement…"
          )}
        </p>
        {etat && <Jauge valeur={etat.repondues} total={etat.total} libelle="Progression du profil" />}
      </div>
      <div className="profil-tete-actions">
        <button
          type="button"
          className="btn btn-mini"
          aria-pressed={vocal}
          title="Chaque question est lue à voix haute (voix locale du système)"
          onClick={() => {
            setVocal((v) => {
              if (v) lecteur.current.arreter();
              return !v;
            });
          }}
        >
          Entretien vocal {vocal ? "activé" : "désactivé"}
        </button>
        <button type="button" className="btn btn-mini btn-discret" onClick={surRetour}>
          Retour à la mémoire
        </button>
      </div>
    </div>
  );

  return (
    <div className="profil-vue">
      {entete}
      <p className="visuellement-cache" role="status" aria-live="polite">
        {annonce}
      </p>
      {annonce && !entretien && <p className="profil-annonce">{annonce}</p>}
      {erreur && (
        <p className="securite-erreur" role="alert">
          {erreur}
        </p>
      )}

      {!entretien ? (
        <>
          {etat?.reprise && (
            <button
              type="button"
              className="btn btn-principal profil-reprendre"
              onClick={() => {
                if (etat.reprise) ouvrir(etat.reprise.section, etat.reprise.question);
              }}
            >
              {etat.repondues ? "Reprendre là où vous vous êtes arrêté" : "Commencer le questionnaire"}
            </button>
          )}
          <ul className="profil-sections">
            {etat?.sections.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  className="profil-section"
                  data-complete={s.repondues === s.total ? "" : undefined}
                  onClick={() => {
                    ouvrir(s.id);
                  }}
                >
                  <span className="profil-section-tete">
                    <span className="profil-section-titre">{s.titre}</span>
                    {s.prive && (
                      <span className="badge-co" data-ton="attention" title="Réponses privées par défaut">
                        privé
                      </span>
                    )}
                    <span className="profil-section-compte">
                      {s.repondues}/{s.total}
                    </span>
                  </span>
                  <span className="profil-section-description">{s.description}</span>
                  <Jauge valeur={s.repondues} total={s.total} libelle={`Progression : ${s.titre}`} />
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : (
        question && (
          <section className="profil-entretien" aria-labelledby="profil-question">
            <div className="profil-entretien-tete">
              <button type="button" className="lien-btn" onClick={fermer}>
                Toutes les sections
              </button>
              <h3 className="profil-entretien-section">{entretien.titre}</h3>
              <p className="profil-entretien-description">{entretien.description}</p>
              <ol className="profil-etapes" aria-label="Questions de la section">
                {entretien.questions.map((q, i) => (
                  <li key={q.id}>
                    <button
                      type="button"
                      className="profil-etape"
                      aria-current={i === entretien.index ? "step" : undefined}
                      data-repondue={q.reponse ? "" : undefined}
                      aria-label={`Question ${String(i + 1)}${q.reponse ? " (répondue)" : ""}`}
                      onClick={() => {
                        aller(i);
                      }}
                    />
                  </li>
                ))}
              </ol>
            </div>

            <div className="profil-carte">
              <p className="profil-compteur">
                Question {entretien.index + 1} sur {entretien.questions.length}
              </p>
              <h4 id="profil-question" className="profil-question">
                {question.texte}
              </h4>
              {question.aide && <p className="profil-aide">{question.aide}</p>}
              <label className="visuellement-cache" htmlFor="profil-reponse">
                Votre réponse
              </label>
              <textarea
                id="profil-reponse"
                ref={champ}
                className="profil-reponse"
                value={brouillon}
                rows={4}
                maxLength={4000}
                placeholder={dictee === "ecoute" ? "Parlez, puis touchez « Terminer la dictée »…" : "Votre réponse (Ctrl+Entrée pour valider)"}
                onChange={(e) => {
                  setBrouillon(e.target.value);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault();
                    enregistrer();
                  }
                }}
              />
              <div className="profil-options">
                <label className="profil-prive">
                  <input
                    type="checkbox"
                    checked={prive}
                    onChange={(e) => {
                      setPrive(e.target.checked);
                    }}
                  />
                  Privée : ne part jamais vers une IA externe
                </label>
                <div className="profil-voix">
                  <button
                    type="button"
                    className="btn btn-mini btn-discret"
                    onClick={() => {
                      dire(question.texte);
                    }}
                  >
                    Lire la question
                  </button>
                  {micro && (
                    <button
                      type="button"
                      className={`btn btn-mini${dictee === "ecoute" ? " btn-ambre" : ""}`}
                      aria-pressed={dictee === "ecoute"}
                      disabled={dictee === "transcription"}
                      onClick={basculerDictee}
                    >
                      {dictee === "ecoute" ? "Terminer la dictée" : dictee === "transcription" ? "Transcription…" : "Dicter"}
                    </button>
                  )}
                </div>
              </div>
              <div className="profil-actions">
                {question.reponse && (
                  <button type="button" className="lien-btn profil-retirer" onClick={retirer}>
                    Retirer la réponse
                  </button>
                )}
                <button
                  type="button"
                  className="btn btn-discret"
                  disabled={entretien.index === 0}
                  onClick={() => {
                    aller(entretien.index - 1);
                  }}
                >
                  Précédente
                </button>
                <button
                  type="button"
                  className="btn btn-discret"
                  onClick={() => {
                    aller(entretien.index + 1);
                  }}
                >
                  Passer
                </button>
                <button type="button" className="btn btn-principal" disabled={envoi || dictee !== "repos"} onClick={enregistrer}>
                  {envoi ? "Enregistrement…" : brouillon.trim() ? "Enregistrer" : "Suivante"}
                </button>
              </div>
              {annonce && <p className="profil-annonce profil-annonce--discret">{annonce}</p>}
            </div>
          </section>
        )
      )}
    </div>
  );
}
