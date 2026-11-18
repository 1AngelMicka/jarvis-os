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
}

export function ListeConversations({ conversations, active, surChoisir }: Props) {
  if (!conversations.length) {
    return (
      <div className="vide vide--calme">
        <p className="vide-titre">Aucune conversation</p>
        <p>Écrivez à JARVIS : chaque échange est gardé ici.</p>
      </div>
    );
  }
  const maintenant = new Date();
  const groupes = new Map<string, ResumeConversation[]>();
  for (const c of conversations) {
    const g = c.epinglee ? "Épinglées" : groupe(new Date(c.maj_le), maintenant);
    groupes.set(g, [...(groupes.get(g) ?? []), c]);
  }
  return (
    <nav className="hist" aria-label="Conversations">
      {[...groupes].map(([nom, liste]) => (
        <div className="hist-groupe" key={nom}>
          <h3 className="hist-groupe-titre">{nom}</h3>
          <ul>
            {liste.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  className="hist-item"
                  aria-label={`${c.titre} — ${quand(new Date(c.maj_le), maintenant)}, ${String(c.nb_messages)} message${c.nb_messages > 1 ? "s" : ""}`}
                  aria-current={c.id === active ? "true" : undefined}
                  onClick={() => {
                    surChoisir(c.id);
                  }}
                >
                  <span className="hist-titre">{c.titre}</span>
                  <span className="hist-meta">
                    {quand(new Date(c.maj_le), maintenant)} · {c.nb_messages} message{c.nb_messages > 1 ? "s" : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}
