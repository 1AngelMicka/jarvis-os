// Accès à l'API du Core. Une seule requête par ressource à la fois (dédoublonnage) : le démarrage de
// l'interface fait UN appel (/v1/etat), même quand React rejoue les effets en mode strict.

import { LecteurSSE } from "./sse";
import type { DemandeDialogue, DetailConversation, Etat, EvenementDialogue } from "./types";

export class ErreurApi extends Error {
  constructor(message: string, readonly statut: number) {
    super(message);
  }
}

const enCours = new Map<string, Promise<unknown>>();

/** Partage la même promesse entre appels simultanés pour une même clé. */
export function unSeul<T>(cle: string, appel: () => Promise<T>): Promise<T> {
  const existant = enCours.get(cle);
  if (existant) return existant as Promise<T>;
  const promesse = appel().finally(() => enCours.delete(cle));
  enCours.set(cle, promesse);
  return promesse;
}

const MESSAGES_STATUT: Record<number, string> = {
  403: "Accès refusé par le Core.",
  404: "Introuvable : la conversation a peut-être été supprimée.",
  422: "Demande invalide.",
  429: "Trop de demandes : réessayez dans un instant.",
};

async function lireErreur(rep: Response): Promise<ErreurApi> {
  let detail = "";
  try {
    const corps = (await rep.json()) as { detail?: unknown };
    if (typeof corps.detail === "string") detail = corps.detail;
  } catch {
    /* corps non JSON */
  }
  const base = MESSAGES_STATUT[rep.status] ?? (rep.status >= 500 ? "Le Core a rencontré une erreur." : "Erreur.");
  return new ErreurApi(detail ? `${base} ${detail}` : base, rep.status);
}

async function lireJson<T>(chemin: string): Promise<T> {
  let rep: Response;
  try {
    rep = await fetch(chemin, { headers: { Accept: "application/json" } });
  } catch {
    throw new ErreurApi("Core injoignable : vérifiez qu'il tourne (python -m jarvis2 serveur).", 0);
  }
  if (!rep.ok) throw await lireErreur(rep);
  return (await rep.json()) as T;
}

export function lireEtat(): Promise<Etat> {
  return unSeul("etat", () => lireJson<Etat>("/v1/etat"));
}

export function lireConversation(id: string): Promise<DetailConversation> {
  return unSeul(`conversation:${id}`, () => lireJson<DetailConversation>(`/v1/conversations/${encodeURIComponent(id)}`));
}

/** Envoie un message et transmet chaque événement du flux à `surEvenement`. */
export async function dialoguer(
  demande: DemandeDialogue,
  surEvenement: (ev: EvenementDialogue) => void,
  signal: AbortSignal,
): Promise<void> {
  let rep: Response;
  try {
    rep = await fetch("/v1/dialogue", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(demande),
      signal,
    });
  } catch (e) {
    if (signal.aborted) return;
    throw e instanceof Error && e.name === "AbortError"
      ? e
      : new ErreurApi("Core injoignable : vérifiez qu'il tourne (python -m jarvis2 serveur).", 0);
  }
  if (!rep.ok || !rep.body) throw await lireErreur(rep);
  const lecteur = rep.body.pipeThrough(new TextDecoderStream()).getReader();
  const sse = new LecteurSSE();
  try {
    for (;;) {
      const { value, done } = await lecteur.read();
      if (done) break;
      for (const ev of sse.pousser(value)) {
        surEvenement({ type: ev.evenement, donnees: JSON.parse(ev.donnees) as unknown } as EvenementDialogue);
      }
    }
  } catch (e) {
    if (signal.aborted) return;
    throw e;
  } finally {
    lecteur.releaseLock();
  }
}
