"""Coûts et transparence : dépenses par connecteur (jour, mois), plafonds, jauges d'abonnement Claude Code.

Source des dépenses : la table `telemetrie`, qui reçoit une mesure par appel de moteur (dialogue, titres, conseil,
missions) ; `messages.meta` en garde une copie par réponse pour le pied affiché sous chaque message.
Les jours et les mois suivent l'heure locale du PC.

Jauges 5 h / 7 jours : lues uniquement dans les événements `rate_limit_event` du flux stream-json de NOS appels à
la CLI `claude`. « inconnu » tant que rien n'est mesuré (jamais 0), périmées 30 min après la mesure.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .db import Executant
from .moteurs.claude_code import Jauge, MoteurClaudeCode

if TYPE_CHECKING:
    from .connecteurs import Connecteurs

SEUIL_ALERTE = 0.8
PERIME_APRES = timedelta(minutes=30)
JOURS_HISTORIQUE = 30
JAUGES = {"five_hour": "5 heures", "seven_day": "7 jours"}  # toujours affichées, même inconnues
NOMS_JAUGES = {**JAUGES, "seven_day_opus": "7 jours (Opus)", "seven_day_sonnet": "7 jours (Sonnet)"}


def local(maintenant: datetime | None = None) -> datetime:
    return (maintenant or datetime.now(UTC)).astimezone()


def debut_jour(maintenant: datetime | None = None) -> datetime:
    return local(maintenant).replace(hour=0, minute=0, second=0, microsecond=0)


def debut_mois(maintenant: datetime | None = None) -> datetime:
    return debut_jour(maintenant).replace(day=1)


async def depense(pool: Executant, moteur: str, depuis: datetime) -> float:
    valeur = await pool.fetchval(
        "SELECT coalesce(sum(cout_usd), 0) FROM telemetrie WHERE moteur = $1 AND cree_le >= $2",
        moteur,
        depuis.astimezone(UTC),
    )
    return float(valeur or 0)


def etat_plafond(depense_mois: float, plafond: float | None) -> dict[str, Any] | None:
    """None sans plafond ; sinon dépense, part (0..), alerte (≥ 80 %), atteint (≥ 100 %)."""
    if plafond is None:
        return None
    part = depense_mois / plafond if plafond > 0 else 1.0
    return {
        "plafond_usd": plafond,
        "depense_usd": round(depense_mois, 6),
        "part": round(part, 4),
        "alerte": part >= SEUIL_ALERTE,
        "atteint": depense_mois >= plafond,
    }


def _meta(valeur: Any) -> dict[str, Any]:
    if isinstance(valeur, dict):
        return valeur
    if isinstance(valeur, str):
        try:
            charge = json.loads(valeur)
        except ValueError:
            return {}
        return charge if isinstance(charge, dict) else {}
    return {}


def _vide() -> dict[str, Any]:
    return {"cout_usd": 0.0, "appels": 0, "erreurs": 0, "jetons_entree": 0, "jetons_sortie": 0}


def _ajouter(cumul: dict[str, Any], ligne: Mapping[str, Any]) -> None:
    cumul["cout_usd"] += float(ligne["cout_usd"] or 0)
    cumul["appels"] += 1
    cumul["erreurs"] += ligne["statut"] == "erreur"
    cumul["jetons_entree"] += int(ligne["jetons_entree"] or 0)
    cumul["jetons_sortie"] += int(ligne["jetons_sortie"] or 0)


def _arrondir(cumul: dict[str, Any]) -> dict[str, Any]:
    return {**cumul, "cout_usd": round(cumul["cout_usd"], 6)}


def decrire_jauges(mesures: Iterable[Jauge], maintenant: datetime | None = None) -> list[dict[str, Any]]:
    """La mesure la plus récente par type ; 5 h et 7 jours toujours présentes (« inconnu » sans mesure)."""
    maintenant = maintenant or datetime.now(UTC)
    dernieres: dict[str, Jauge] = {}
    for j in mesures:
        if j.type not in dernieres or j.mesure_le > dernieres[j.type].mesure_le:
            dernieres[j.type] = j
    sorties: list[dict[str, Any]] = []
    for genre in [*JAUGES, *sorted(t for t in dernieres if t not in JAUGES)]:
        mesure = dernieres.get(genre)
        if mesure is None:
            sorties.append({"type": genre, "nom": NOMS_JAUGES.get(genre, genre), "etat": "inconnu"})
            continue
        perimee = maintenant - mesure.mesure_le > PERIME_APRES or (
            mesure.reinitialisation is not None and mesure.reinitialisation <= maintenant
        )
        sorties.append(
            {
                **mesure.en_dict(),
                "nom": NOMS_JAUGES.get(genre, genre),
                "etat": "perime" if perimee else "mesure",
                "age_s": max(0, round((maintenant - mesure.mesure_le).total_seconds())),
            }
        )
    return sorties


async def jauges_claude(connecteurs: Connecteurs, maintenant: datetime | None = None) -> list[dict[str, Any]]:
    """Mesures en mémoire du moteur, complétées par celles gardées dans la télémétrie (redémarrage du Core)."""
    maintenant = maintenant or datetime.now(UTC)
    mesures: list[Jauge] = []
    d = connecteurs.definitions.get("claude_code")
    if d is not None and isinstance(d.moteur.interne, MoteurClaudeCode):
        mesures.extend(d.moteur.interne.jauges.values())
    lignes = await connecteurs.pool.fetch(
        "SELECT meta FROM telemetrie WHERE moteur = 'claude_code' AND cree_le >= $1 ORDER BY cree_le DESC LIMIT 20",
        (maintenant - PERIME_APRES * 2).astimezone(UTC),
    )
    for ligne in lignes:
        for brut in _meta(ligne["meta"]).get("limites") or []:
            if isinstance(brut, dict) and (j := Jauge.depuis_dict(brut)) is not None:
                mesures.append(j)
    return decrire_jauges(mesures, maintenant)


async def resume(connecteurs: Connecteurs, maintenant: datetime | None = None) -> dict[str, Any]:
    """Vue « Coûts » : totaux du jour et du mois, détail par connecteur, 30 derniers jours, jauges."""
    maintenant = maintenant or datetime.now(UTC)
    jour, mois = debut_jour(maintenant), debut_mois(maintenant)
    premier_jour = min(mois, jour - timedelta(days=JOURS_HISTORIQUE - 1))
    lignes = await connecteurs.pool.fetch(
        "SELECT moteur, statut, jetons_entree, jetons_sortie, cout_usd, meta, cree_le FROM telemetrie"
        " WHERE cree_le >= $1 AND operation <> 'retour'",  # avis de l'utilisateur (routage.py) : pas des appels
        premier_jour.astimezone(UTC),
    )
    par_jour: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    cumul_jour: dict[str, dict[str, Any]] = defaultdict(_vide)
    cumul_mois: dict[str, dict[str, Any]] = defaultdict(_vide)
    details: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"estime": False, "cout_inconnu": 0, "equivalent_api_usd": 0.0}
    )
    for ligne in lignes:
        moment = ligne["cree_le"]
        if isinstance(moment, str):
            moment = datetime.fromisoformat(moment)
        moment = local(moment)
        ident = str(ligne["moteur"])
        par_jour[moment.date().isoformat()][ident] += float(ligne["cout_usd"] or 0)
        if moment >= jour:
            _ajouter(cumul_jour[ident], ligne)
        if moment >= mois:
            _ajouter(cumul_mois[ident], ligne)
            meta = _meta(ligne["meta"])
            d = details[ident]
            d["estime"] = d["estime"] or bool(meta.get("cout_estime"))
            d["cout_inconnu"] += bool(meta.get("cout_inconnu"))
            if isinstance(meta.get("cout_equivalent_api_usd"), int | float):
                d["equivalent_api_usd"] += float(meta["cout_equivalent_api_usd"])
    cartes = []
    for ident, definition in connecteurs.definitions.items():
        m = definition.moteur.interne
        payant = m.famille == "api"
        if not payant and ident not in cumul_mois and not connecteurs.actif(ident):
            continue  # connecteur jamais utilisé ce mois-ci, ni actif : rien à montrer
        plafond = connecteurs.plafond(ident)
        cartes.append(
            {
                "id": ident,
                "nom": m.nom,
                "famille": m.famille,
                "payant": payant,
                "actif": connecteurs.actif(ident),
                "jour": _arrondir(cumul_jour[ident]),
                "mois": _arrondir(cumul_mois[ident]),
                "estime": details[ident]["estime"],
                "cout_inconnu": details[ident]["cout_inconnu"],
                "equivalent_api_usd": round(details[ident]["equivalent_api_usd"], 6) or None,
                "plafond": etat_plafond(cumul_mois[ident]["cout_usd"], plafond) if payant else None,
            }
        )
    cartes.sort(key=lambda c: (-c["mois"]["cout_usd"], not c["payant"], c["nom"]))
    jours = []
    for i in range(JOURS_HISTORIQUE):
        cle = (jour - timedelta(days=JOURS_HISTORIQUE - 1 - i)).date().isoformat()
        valeurs = par_jour.get(cle, {})
        jours.append(
            {
                "jour": cle,
                "cout_usd": round(sum(valeurs.values()), 6),
                "par_connecteur": {k: round(v, 6) for k, v in valeurs.items() if v},
            }
        )
    return {
        "maintenant": maintenant.isoformat(),
        "jour": jour.date().isoformat(),
        "mois": mois.strftime("%Y-%m"),
        "total_jour_usd": round(sum(c["cout_usd"] for c in cumul_jour.values()), 6),
        "total_mois_usd": round(sum(c["cout_usd"] for c in cumul_mois.values()), 6),
        "seuil_alerte": SEUIL_ALERTE,
        "connecteurs": cartes,
        "jours": jours,
        "jauges": await jauges_claude(connecteurs, maintenant),
    }
