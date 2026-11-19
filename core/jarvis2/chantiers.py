"""Chantiers : tâches suivies dans la durée (progression, étapes, « C'est fait »), SANS DOUBLON.

- Deux chantiers ont « le même sens » quand leurs titres ont les mêmes mots significatifs, sans tenir compte de
  l'ordre, des accents, de la casse, des pluriels simples ni des mots vides (« Réparer le vélo » = « vélos : réparer »).
- À la création, un chantier encore ouvert du même sens est renvoyé au lieu d'en créer un second.
- Quand un chantier est terminé, ses jumeaux encore ouverts sont abandonnés (« Doublon de … »).
- Les étapes sont rangées sous une forme unique `{"titre": str, "fait": bool}` (les chantiers importés de JARVIS v1
  peuvent en avoir d'autres : elles sont lues avec tolérance).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any
from uuid import UUID

from .db import Base, Executant

OUVERTS = ("propose", "a_faire", "en_cours", "en_attente_utilisateur", "bloque")
STATUTS = (*OUVERTS, "termine", "abandonne")
# Statuts qu'une simple modification peut poser (terminer et abandonner ont leur propre chemin)
STATUTS_MODIFIABLES = OUVERTS
COLONNES = (
    "id, titre, description, categorie, statut, progression, etape_courante, etapes, responsable,"
    " action_utilisateur, priorite, cree_par, origine, motif, cree_le, maj_le, termine_le"
)
VERROU = 0x4A4348  # sérialise la création (pas de doublon même avec deux demandes simultanées)

MOTS_VIDES = frozenset(
    """a au aux avec ce ces cet cette d de des du en et l la le les leur leurs ma mes mon nos notre par pour sa
    ses son sur ta tes ton un une vos votre y à qu que qui dans faire est il elle on se sans ou""".split()  # noqa: SIM905  (plus lisible)
)


class ErreurChantier(Exception):
    """Demande impossible (chantier introuvable, déjà clos…)."""


def _sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texte) if not unicodedata.combining(c))


def signature(titre: str) -> str:
    """Empreinte de sens d'un titre : mots significatifs normalisés, triés, sans répétition."""
    mots = set()
    for mot in re.findall(r"[a-z0-9]+", _sans_accents(titre.lower().replace("’", "'"))):
        if mot in MOTS_VIDES or (len(mot) < 2 and not mot.isdigit()):
            continue
        if len(mot) > 3 and mot[-1] in "sx" and not mot.isdigit():
            mot = mot[:-1]  # pluriel simple : « vélos » = « vélo », « travaux » ≈ « travau »
        mots.add(mot)
    return " ".join(sorted(mots))


def lire_etapes(brut: Any) -> list[dict[str, Any]]:
    """Étapes sous la forme `{"titre", "fait"}`, quelle que soit leur forme d'origine (JARVIS v1 compris)."""
    if not isinstance(brut, list):
        return []
    etapes: list[dict[str, Any]] = []
    for e in brut:
        if isinstance(e, str) and e.strip():
            etapes.append({"titre": e.strip()[:300], "fait": False})
        elif isinstance(e, dict):
            titre = next((e[c] for c in ("titre", "nom", "label", "texte", "description") if e.get(c)), "")
            statut = str(e.get("statut", "")).lower()
            fait = bool(e.get("fait") or e.get("done") or e.get("faite") or statut in ("termine", "fait", "done"))
            if str(titre).strip():
                etapes.append({"titre": str(titre).strip()[:300], "fait": fait})
    return etapes[:100]


def progression_des_etapes(etapes: list[dict[str, Any]]) -> int:
    return round(100 * sum(1 for e in etapes if e["fait"]) / len(etapes)) if etapes else 0


def _propre(ligne: Any) -> dict[str, Any]:
    d = dict(ligne)
    d["etapes"] = lire_etapes(d.get("etapes"))
    return {k: v.isoformat() if isinstance(v, datetime) else str(v) if isinstance(v, UUID) else v for k, v in d.items()}


async def obtenir(conn: Executant, ident: UUID) -> dict[str, Any] | None:
    ligne = await conn.fetchrow(f"SELECT {COLONNES} FROM chantiers WHERE id = $1", ident)  # noqa: S608
    return _propre(ligne) if ligne else None


async def _exiger(conn: Executant, ident: UUID) -> dict[str, Any]:
    chantier = await obtenir(conn, ident)
    if chantier is None:
        raise ErreurChantier("Chantier introuvable")
    return chantier


async def lister(conn: Executant, statut: str = "ouverts", limite: int = 100) -> list[dict[str, Any]]:
    """`ouverts` (défaut), `termines`, `abandonnes`, `tous`, ou un statut précis. Ouverts : priorité puis récence."""
    limite = max(1, min(limite, 500))
    args: tuple[str, ...] = ()
    if statut == "ouverts":
        filtre = "statut IN ('propose', 'a_faire', 'en_cours', 'en_attente_utilisateur', 'bloque')"
    elif statut == "tous":
        filtre = "1 = 1"
    else:
        voulu = {"termines": "termine", "abandonnes": "abandonne"}.get(statut, statut)
        if voulu not in STATUTS:
            raise ErreurChantier(f"Statut inconnu : {statut}")
        filtre, args = "statut = $2", (voulu,)
    ordre = "priorite, maj_le DESC" if statut == "ouverts" else "coalesce(termine_le, maj_le) DESC"
    lignes = await conn.fetch(
        f"SELECT {COLONNES} FROM chantiers WHERE {filtre} ORDER BY {ordre} LIMIT $1",  # noqa: S608
        limite,
        *args,
    )
    return [_propre(r) for r in lignes]


async def jumeaux(conn: Executant, titre: str, sauf: UUID | None = None) -> list[dict[str, Any]]:
    """Chantiers ouverts dont le titre a le même sens (filtrage en Python : la normalisation n'existe pas en SQL)."""
    cible = signature(titre)
    if not cible:
        return []
    lignes = await conn.fetch(
        f"SELECT {COLONNES} FROM chantiers WHERE statut IN"  # noqa: S608
        " ('propose', 'a_faire', 'en_cours', 'en_attente_utilisateur', 'bloque') ORDER BY cree_le"
    )
    return [_propre(r) for r in lignes if signature(r["titre"]) == cible and (sauf is None or r["id"] != sauf)]


async def creer(
    base: Base,
    titre: str,
    acteur: str,
    *,
    description: str | None = None,
    categorie: str = "general",
    etapes: list[Any] | None = None,
    priorite: int = 2,
    origine: str = "utilisateur",
) -> tuple[dict[str, Any], bool]:
    """Crée un chantier, ou renvoie le jumeau ouvert existant. Renvoie (chantier, cree)."""
    titre = " ".join(titre.split())[:300]
    if not titre:
        raise ErreurChantier("Titre vide")
    liste = lire_etapes(etapes or [])
    async with base.acquire() as conn, conn.transaction():
        await conn.verrouiller(VERROU)
        existants = await jumeaux(conn, titre)
        if existants:
            return existants[0], False
        ident: UUID = await conn.fetchval(
            "INSERT INTO chantiers (titre, description, categorie, statut, progression, etape_courante, etapes,"
            " responsable, priorite, cree_par, origine) VALUES ($1, $2, $3, 'a_faire', $4, $5, $6, $7, $8, $9, $10)"
            " RETURNING id",
            titre,
            (description or "").strip()[:4000] or None,
            categorie.strip()[:60] or "general",
            progression_des_etapes(liste),
            _prochaine(liste),
            liste,
            "utilisateur" if origine == "utilisateur" else "jarvis",
            min(3, max(1, priorite)),
            acteur,
            origine,
        )
        return await _exiger(conn, ident), True


def _prochaine(etapes: list[dict[str, Any]]) -> str | None:
    return next((e["titre"] for e in etapes if not e["fait"]), None)


async def modifier(
    base: Base,
    ident: UUID,
    *,
    titre: str | None = None,
    description: str | None = None,
    progression: int | None = None,
    etapes: list[Any] | None = None,
    statut: str | None = None,
    priorite: int | None = None,
) -> dict[str, Any]:
    """Modifie un chantier ouvert. Des étapes sans progression donnée recalculent la progression (étapes faites)."""
    async with base.acquire() as conn, conn.transaction():
        await conn.verrouiller(VERROU)
        actuel = await _exiger(conn, ident)
        if actuel["statut"] not in OUVERTS:
            raise ErreurChantier("Chantier clos : rouvrez-le d'abord")
        if statut is not None and statut not in STATUTS_MODIFIABLES:
            raise ErreurChantier(f"Statut non modifiable ici : {statut}")
        nouveau_titre = " ".join(titre.split())[:300] if titre is not None else actuel["titre"]
        if not nouveau_titre:
            raise ErreurChantier("Titre vide")
        if titre is not None and await jumeaux(conn, nouveau_titre, sauf=ident):
            raise ErreurChantier("Un autre chantier ouvert porte déjà ce titre")
        liste = lire_etapes(etapes) if etapes is not None else actuel["etapes"]
        if progression is None:
            progression = progression_des_etapes(liste) if etapes is not None and liste else actuel["progression"]
        progression = min(100, max(0, progression))
        nouveau_statut = statut or actuel["statut"]
        if statut is None and nouveau_statut in ("a_faire", "propose") and progression > 0:
            nouveau_statut = "en_cours"  # du travail a commencé
        await conn.execute(
            "UPDATE chantiers SET titre = $2, description = $3, progression = $4, etapes = $5, etape_courante = $6,"
            " statut = $7, priorite = $8, maj_le = now() WHERE id = $1",
            ident,
            nouveau_titre,
            (description.strip()[:4000] or None) if description is not None else actuel["description"],
            progression,
            liste,
            _prochaine(liste),
            nouveau_statut,
            min(3, max(1, priorite)) if priorite is not None else actuel["priorite"],
        )
        return await _exiger(conn, ident)


async def terminer(base: Base, ident: UUID) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """« C'est fait » : chantier terminé (100 %, étapes cochées) ; ses jumeaux ouverts sont abandonnés."""
    async with base.acquire() as conn, conn.transaction():
        await conn.verrouiller(VERROU)
        actuel = await _exiger(conn, ident)
        if actuel["statut"] == "termine":
            return actuel, []
        if actuel["statut"] == "abandonne":
            raise ErreurChantier("Chantier abandonné : rouvrez-le d'abord")
        etapes = [{**e, "fait": True} for e in actuel["etapes"]]
        await conn.execute(
            "UPDATE chantiers SET statut = 'termine', progression = 100, etapes = $2, etape_courante = NULL,"
            " termine_le = now(), maj_le = now() WHERE id = $1",
            ident,
            etapes,
        )
        doublons = await jumeaux(conn, actuel["titre"], sauf=ident)
        for d in doublons:
            await _abandonner(conn, UUID(d["id"]), f"Doublon de « {actuel['titre']} »")
        return await _exiger(conn, ident), doublons


async def _abandonner(conn: Executant, ident: UUID, motif: str) -> None:
    await conn.execute(
        "UPDATE chantiers SET statut = 'abandonne', motif = $2, termine_le = now(), maj_le = now() WHERE id = $1",
        ident,
        motif[:500],
    )


async def abandonner(conn: Executant, ident: UUID, motif: str | None = None) -> dict[str, Any]:
    """Abandon (réversible : « Rouvrir ») ; passe par l'action 🟡 `chantier.abandonner`."""
    actuel = await _exiger(conn, ident)
    if actuel["statut"] not in OUVERTS:
        raise ErreurChantier("Chantier déjà clos")
    await _abandonner(conn, ident, (motif or "").strip() or "Abandonné par l'utilisateur")
    return await _exiger(conn, ident)


async def rouvrir(base: Base, ident: UUID) -> dict[str, Any]:
    """Remet un chantier clos en cours, sauf si un jumeau ouvert existe déjà (pas de doublon)."""
    async with base.acquire() as conn, conn.transaction():
        await conn.verrouiller(VERROU)
        actuel = await _exiger(conn, ident)
        if actuel["statut"] in OUVERTS:
            return actuel
        if await jumeaux(conn, actuel["titre"], sauf=ident):
            raise ErreurChantier("Un chantier ouvert du même sens existe déjà")
        statut = "en_cours" if 0 < actuel["progression"] < 100 else "a_faire"
        await conn.execute(
            "UPDATE chantiers SET statut = $2, motif = NULL, termine_le = NULL,"
            " progression = CASE WHEN progression = 100 THEN 0 ELSE progression END, maj_le = now() WHERE id = $1",
            ident,
            statut,
        )
        return await _exiger(conn, ident)


async def supprimer(conn: Executant, ident: UUID) -> dict[str, Any]:
    """Suppression définitive ; passe par l'action 🔴 `chantier.supprimer`."""
    actuel = await _exiger(conn, ident)
    await conn.execute("DELETE FROM chantiers WHERE id = $1", ident)
    return {"chantier_id": str(ident), "titre": actuel["titre"]}
