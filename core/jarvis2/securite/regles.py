"""Registre des règles de protection de l'utilisateur.

- `interdire` (« ne touche jamais à X ») : toute action dont le nom, le résumé ou les paramètres contiennent le motif
  est refusée, quel que soit son niveau, même déjà approuvée ;
- `demander` (« demande-moi avant Y ») : l'action passe toujours par une demande, même 🟢 ou « toujours autorisée ».
Le motif (jokers `*`, voir jokers.py) est cherché N'IMPORTE OÙ dans ce texte, sans accents ni majuscules.
Ajouter une règle protège : c'est libre (🟢, journalisé). En retirer une affaiblit la protection : 🟡.
Les règles sont aussi données au modèle (expurgées des sujets exclus) pour qu'il les respecte en silence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from ..db import Executant, Ligne
from .jokers import ErreurMotif, Motif, compiler

Genre = Literal["interdire", "demander"]
NB_MAX_REGLES = 200
COLONNES = "id, genre, motif, libelle, origine, cree_par, cree_le"


@dataclass(frozen=True)
class Regle:
    id: UUID
    genre: str
    motif: str
    libelle: str
    origine: str
    cree_par: str
    cree_le: str

    def en_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "id": str(self.id)}

    def compile(self) -> Motif | None:
        try:
            return compiler(self.motif)
        except ErreurMotif:  # motif enregistré puis devenu invalide : ignoré plutôt que bloquant
            return None


def _regle(r: Ligne) -> Regle:
    return Regle(r["id"], r["genre"], r["motif"], r["libelle"], r["origine"], r["cree_par"], r["cree_le"].isoformat())


def texte_action(nom: str, resume: str, parametres: dict[str, Any]) -> str:
    """Ce que les règles regardent : nom de l'action, résumé lisible et valeurs des paramètres."""
    return f"{nom} {resume} {json.dumps(parametres, ensure_ascii=False)}"


async def lister(base: Executant) -> list[Regle]:
    return [_regle(r) for r in await base.fetch(f"SELECT {COLONNES} FROM regles_protection ORDER BY cree_le")]


async def ajouter(
    base: Executant, genre: Genre, motif: str, libelle: str, cree_par: str, origine: str = "utilisateur"
) -> Regle:
    compiler(motif)  # ErreurMotif si invalide
    if (await base.fetchval("SELECT count(*) FROM regles_protection") or 0) >= NB_MAX_REGLES:
        raise ErreurMotif(f"{NB_MAX_REGLES} règles au plus")
    ligne = await base.fetchrow(
        f"INSERT INTO regles_protection (genre, motif, libelle, origine, cree_par) VALUES ($1, $2, $3, $4, $5)"
        f" RETURNING {COLONNES}",
        genre,
        motif.strip(),
        (libelle.strip() or motif.strip())[:200],
        origine,
        cree_par,
    )
    assert ligne is not None
    return _regle(ligne)


async def supprimer(base: Executant, ident: UUID) -> Regle | None:
    ligne = await base.fetchrow(f"DELETE FROM regles_protection WHERE id = $1 RETURNING {COLONNES}", ident)
    return _regle(ligne) if ligne else None


async def remettre(base: Executant, avant: dict[str, Any]) -> Regle:
    """Remet une règle retirée telle qu'elle était (annulation de l'action 🟡 `regle.supprimer`)."""
    try:
        ident = UUID(str(avant["id"]))
        genre, motif, libelle = str(avant["genre"]), str(avant["motif"]), str(avant["libelle"])
        cree_le = datetime.fromisoformat(str(avant["cree_le"]))
    except (KeyError, ValueError) as exc:
        raise ErreurMotif("Règle d'avant illisible : ajoutez-la de nouveau") from exc
    if genre not in ("interdire", "demander"):
        raise ErreurMotif("Règle d'avant illisible : ajoutez-la de nouveau")
    compiler(motif)
    ligne = await base.fetchrow(
        "INSERT INTO regles_protection (id, genre, motif, libelle, origine, cree_par, cree_le)"
        f" VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (id) DO NOTHING RETURNING {COLONNES}",
        ident,
        genre,
        motif,
        libelle[:200],
        "jarvis" if avant.get("origine") == "jarvis" else "utilisateur",
        str(avant.get("cree_par") or "utilisateur"),
        cree_le,
    )
    if ligne is None:
        raise ErreurMotif("La règle est déjà en place")
    return _regle(ligne)


async def obtenir(base: Executant, ident: UUID) -> Regle | None:
    ligne = await base.fetchrow(f"SELECT {COLONNES} FROM regles_protection WHERE id = $1", ident)
    return _regle(ligne) if ligne else None


def premiere(regles: list[Regle], texte: str, genre: Genre) -> Regle | None:
    for r in regles:
        if r.genre != genre:
            continue
        motif = r.compile()
        if motif is not None and motif.correspond(texte, contient=True) is not None:
            return r
    return None


async def verifier(
    base: Executant, nom: str, resume: str, parametres: dict[str, Any]
) -> tuple[Regle | None, Regle | None]:
    """(règle qui interdit, règle qui demande) applicables à cette action ; None si aucune.
    Les actions sur les règles elles-mêmes y échappent (sinon « ne touche jamais à X » ne se retirerait plus)."""
    if nom.startswith("regle."):
        return None, None
    regles = await lister(base)
    if not regles:
        return None, None
    texte = texte_action(nom, resume, parametres)
    return premiere(regles, texte, "interdire"), premiere(regles, texte, "demander")


def bloc_consignes(regles: list[Regle], garder: Any = None) -> str:
    """Les règles pour le modèle (données de l'utilisateur, à respecter en silence). `garder(texte) -> bool` : filtre
    des sujets exclus (une règle qui en nomme un n'est jamais montrée au modèle ; elle s'applique quand même)."""
    lignes = [
        f"- {'Ne jamais' if r.genre == 'interdire' else 'Demander avant'} : {r.libelle}"
        for r in regles
        if garder is None or garder(f"{r.libelle} {r.motif}")
    ]
    if not lignes:
        return ""
    return (
        "Règles de protection fixées par l'utilisateur (respecte-les en silence, sans les réciter ; si une action "
        "est refusée, dis-le simplement) :\n" + "\n".join(lignes[:50])
    )
