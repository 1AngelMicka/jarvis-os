// Coûts et transparence : types de `/v1/couts`, mise en forme des montants, des durées et des jauges.

export interface EtatPlafond {
  plafond_usd: number;
  depense_usd: number;
  part: number;
  alerte: boolean;
  atteint: boolean;
}

export interface Cumul {
  cout_usd: number;
  appels: number;
  erreurs: number;
  jetons_entree: number;
  jetons_sortie: number;
}

export interface CoutConnecteur {
  id: string;
  nom: string;
  famille: "cli" | "api" | "local";
  payant: boolean;
  actif: boolean;
  jour: Cumul;
  mois: Cumul;
  estime: boolean;
  cout_inconnu: number;
  equivalent_api_usd: number | null;
  plafond: EtatPlafond | null;
}

export interface JaugeAbonnement {
  type: string;
  nom: string;
  etat: "inconnu" | "mesure" | "perime";
  statut?: string;
  utilisation?: number | null;
  reinitialisation?: string | null;
  mesure_le?: string;
  age_s?: number;
}

export interface ResumeCouts {
  maintenant: string;
  jour: string;
  mois: string;
  total_jour_usd: number;
  total_mois_usd: number;
  seuil_alerte: number;
  connecteurs: CoutConnecteur[];
  jours: { jour: string; cout_usd: number; par_connecteur: Record<string, number> }[];
  jauges: JaugeAbonnement[];
}

/** Montant en dollars : 4 décimales sous 1 cent, 2 au-delà ; « 0 $ » pour rien. */
export function dollars(v: number | null | undefined): string {
  if (!v) return "0 $";
  const decimales = Math.abs(v) < 0.01 ? 4 : 2;
  return `${v.toLocaleString("fr-FR", { minimumFractionDigits: decimales, maximumFractionDigits: decimales })} $`;
}

export function duree(ms: number | null | undefined): string {
  if (ms == null) return "";
  if (ms < 1000) return `${String(ms)} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} s`;
  return `${String(Math.floor(s / 60))} min ${String(Math.round(s % 60)).padStart(2, "0")} s`;
}

export function nombre(v: number | null | undefined): string {
  return (v ?? 0).toLocaleString("fr-FR");
}

export function pourcent(part: number): string {
  return `${Math.round(part * 100).toLocaleString("fr-FR")} %`;
}

export function ilYa(secondes: number): string {
  if (secondes < 60) return "à l'instant";
  const min = Math.round(secondes / 60);
  if (min < 60) return `il y a ${String(min)} min`;
  return `il y a ${String(Math.round(min / 60))} h`;
}

/** Texte d'une jauge : jamais « 0 % » quand rien n'est mesuré. */
export function texteJauge(j: JaugeAbonnement): string {
  if (j.etat === "inconnu") return "inconnu";
  const valeur = j.utilisation == null ? (j.statut === "rejected" ? "limite atteinte" : "mesure sans pourcentage") : pourcent(j.utilisation);
  return j.etat === "perime" ? `${valeur} (périmé)` : valeur;
}

export function reinitialisation(iso: string | null | undefined, maintenant = new Date()): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const memeJour = d.toDateString() === maintenant.toDateString();
  const heure = d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  return memeJour ? `à ${heure}` : `le ${d.toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" })} à ${heure}`;
}

/** Ton d'un plafond : ok, attention (≥ 80 %), danger (atteint). */
export function tonPlafond(p: EtatPlafond | null | undefined): "ok" | "attention" | "danger" {
  if (!p) return "ok";
  return p.atteint ? "danger" : p.alerte ? "attention" : "ok";
}
