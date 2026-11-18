// Le noyau (réacteur) : seule pièce spectaculaire du HUD. Couches SVG tournantes, composition GPU
// (transform/opacity uniquement). États : repos (respiration), reflexion, parole, alerte.

export type EtatNoyau = "repos" | "reflexion" | "parole" | "alerte";

const LIBELLES: Record<EtatNoyau, string> = {
  repos: "Prêt",
  reflexion: "Réflexion",
  parole: "Réponse",
  alerte: "Alerte",
};

function graduations(n: number, r1: number, r2: number) {
  return Array.from({ length: n }, (_, i) => {
    const a = (i / n) * Math.PI * 2;
    const x1 = 100 + Math.cos(a) * r1;
    const y1 = 100 + Math.sin(a) * r1;
    const x2 = 100 + Math.cos(a) * r2;
    const y2 = 100 + Math.sin(a) * r2;
    return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} />;
  });
}

export function Reacteur({ etat, compact = false }: { etat: EtatNoyau; compact?: boolean }) {
  return (
    <div className="noyau" data-etat={etat} data-compact={compact || undefined} role="img" aria-label={`JARVIS : ${LIBELLES[etat]}`}>
      <div className="noyau-halo" aria-hidden="true" />
      <svg className="noyau-couche noyau-c1" viewBox="0 0 200 200" aria-hidden="true">
        <g className="noyau-trait-fin">{graduations(72, 92, 96)}</g>
      </svg>
      <svg className="noyau-couche noyau-c2" viewBox="0 0 200 200" aria-hidden="true">
        <circle cx="100" cy="100" r="84" className="noyau-arc" strokeDasharray="120 28 44 28" />
      </svg>
      <svg className="noyau-couche noyau-c3" viewBox="0 0 200 200" aria-hidden="true">
        <circle cx="100" cy="100" r="72" className="noyau-arc noyau-arc--fin" strokeDasharray="2 6" />
        <circle cx="100" cy="100" r="64" className="noyau-arc" strokeDasharray="60 340" />
      </svg>
      <svg className="noyau-couche noyau-c4" viewBox="0 0 200 200" aria-hidden="true">
        <g className="noyau-trait">{graduations(12, 50, 58)}</g>
        <circle cx="100" cy="100" r="46" className="noyau-arc noyau-arc--fin" />
      </svg>
      <div className="noyau-coeur" aria-hidden="true" />
      {!compact && <span className="noyau-etat">{LIBELLES[etat]}</span>}
    </div>
  );
}
