import type { ReactNode } from "react";

interface Props {
  titre: string;
  meta?: ReactNode;
  actions?: ReactNode;
  className?: string;
  ordre?: number;
  children: ReactNode;
  id?: string;
}

/** Panneau de verre à coins lumineux, avec en-tête technique. */
export function Panneau({ titre, meta, actions, className, ordre = 0, children, id }: Props) {
  return (
    <section className={`panneau ${className ?? ""}`} style={{ "--ordre": ordre } as React.CSSProperties} aria-labelledby={id ? `${id}-titre` : undefined} id={id}>
      <header className="panneau-tete">
        <h2 className="panneau-titre" id={id ? `${id}-titre` : undefined}>
          {titre}
        </h2>
        <div className="panneau-meta">{meta}</div>
        {actions}
      </header>
      {children}
    </section>
  );
}
