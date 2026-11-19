"""Blocs de mémoire éditables (à la Letta) : textes courts toujours injectés, tenus par l'utilisateur et JARVIS.

Chaque modification crée une version (table `memory_block_versions`) : l'historique est complet, rien n'est perdu.
Niveaux : vers une IA externe, seuls les blocs « public » partent (`memoire.VERS_EXTERNE["blocs"]`) ; un bloc
« prive » (≡ « local_uniquement ») n'est jamais envoyé. Niveau et confidentialité restent synchronisés.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from .db import Base, Connexion, Executant
from .memoire import (
    NIVEAU_DEFAUT_BLOC,
    NIVEAUX,
    TAG_NOYAU,
    VERS_EXTERNE,
    condition_niveaux,
    confidentialite_de,
    lire_noyau,
    niveau_de,
)

LABEL = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")
LIMITE_DEFAUT = 2000
LIMITE_MAX = 20_000


class ErreurBloc(ValueError):
    pass


@dataclass(frozen=True)
class Bloc:
    label: str
    content: str
    version: int
    char_limit: int
    confidentialite: str
    maj_le: datetime
    niveau: str = NIVEAU_DEFAUT_BLOC

    def en_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "content": self.content,
            "version": self.version,
            "char_limit": self.char_limit,
            "confidentialite": self.confidentialite,
            "niveau": self.niveau,
            "maj_le": self.maj_le.isoformat(),
        }


def _bloc(r: Any) -> Bloc:
    return Bloc(r["label"], r["content"], r["version"], r["char_limit"], r["confidentialite"], r["maj_le"], r["niveau"])


COLONNES_BLOC = "label, content, version, char_limit, confidentialite, maj_le, niveau"


async def lister(conn: Executant, exclure_local: bool = False, vides: bool = False) -> list[Bloc]:
    """`exclure_local` (moteur externe) : seulement les blocs « public »."""
    lignes = await conn.fetch(
        f"SELECT {COLONNES_BLOC} FROM memory_blocks WHERE ($2 OR content <> '')"  # noqa: S608 — constantes
        f" AND (NOT $1 OR (confidentialite <> 'local_uniquement' AND {condition_niveaux(conn, '$3')})) ORDER BY label",
        exclure_local,
        vides,
        list(VERS_EXTERNE["blocs"]),
    )
    return [_bloc(r) for r in lignes]


async def ecrire(
    base: Executant,
    label: str,
    contenu: str,
    auteur: str,
    confidentialite: str | None = None,
    char_limit: int | None = None,
    niveau: str | None = None,
) -> Bloc:
    """Crée ou modifie un bloc ; chaque écriture est une nouvelle version gardée.

    `niveau` l'emporte sur `confidentialite` ; sans l'un ni l'autre, un bloc existant garde les siens et un nouveau
    bloc est « public ». Les deux restent synchronisés (« prive » ⇔ « local_uniquement »)."""
    if not LABEL.match(label):
        raise ErreurBloc("Nom de bloc : minuscules, chiffres et . _ : - (64 caractères au plus)")
    if confidentialite not in (None, "normal", "local_uniquement"):
        raise ErreurBloc("Confidentialité : normal ou local_uniquement")
    if niveau is not None and niveau not in NIVEAUX:
        raise ErreurBloc(f"Niveau : {', '.join(NIVEAUX)}")
    if niveau is None and confidentialite is not None:
        niveau = niveau_de(confidentialite, None, NIVEAU_DEFAUT_BLOC)
    if niveau is not None:
        confidentialite = confidentialite_de(niveau)
    if hasattr(base, "acquire"):
        async with cast(Base, base).acquire() as c:
            return await ecrire(c, label, contenu, auteur, confidentialite, char_limit, niveau)
    conn = cast(Connexion, base)
    async with conn.transaction():
        actuel = await conn.fetchrow("SELECT id, version, char_limit FROM memory_blocks WHERE label = $1", label)
        limite = min(max(char_limit or (actuel["char_limit"] if actuel else LIMITE_DEFAUT), 1), LIMITE_MAX)
        if len(contenu) > limite:
            raise ErreurBloc(f"Bloc trop long : {len(contenu)} caractères pour {limite} au plus")
        if actuel is None:
            ligne = await conn.fetchrow(
                "INSERT INTO memory_blocks (label, content, char_limit, confidentialite, niveau)"
                " VALUES ($1, $2, $3, $4, $5) RETURNING id, version",
                label,
                contenu,
                limite,
                confidentialite or "normal",
                niveau or NIVEAU_DEFAUT_BLOC,
            )
        else:
            ligne = await conn.fetchrow(
                "UPDATE memory_blocks SET content = $2, char_limit = $3, version = version + 1, maj_le = now(),"
                " confidentialite = coalesce($4, confidentialite), niveau = coalesce($5, niveau)"
                " WHERE label = $1 RETURNING id, version",
                label,
                contenu,
                limite,
                confidentialite,
                niveau,
            )
        assert ligne is not None
        await conn.execute(
            "INSERT INTO memory_block_versions (block_id, version, content, auteur) VALUES ($1, $2, $3, $4)",
            ligne["id"],
            ligne["version"],
            contenu,
            auteur,
        )
        r = await conn.fetchrow(
            f"SELECT {COLONNES_BLOC} FROM memory_blocks WHERE label = $1",  # noqa: S608 — constante
            label,
        )
    return _bloc(r)


async def historique(conn: Executant, label: str) -> list[dict[str, Any]]:
    lignes = await conn.fetch(
        "SELECT v.version, v.content, v.auteur, v.cree_le FROM memory_block_versions v"
        " JOIN memory_blocks b ON b.id = v.block_id WHERE b.label = $1 ORDER BY v.version DESC",
        label,
    )
    return [{**dict(r), "cree_le": r["cree_le"].isoformat()} for r in lignes]


def texte(blocs: list[Bloc]) -> str:
    return "\n\n".join(f"### {b.label}\n{b.content.strip()}" for b in blocs)


async def noyau_en_blocs(base: Executant, auteur: str = "conversion") -> dict[str, int]:
    """Le noyau devient des blocs : « noyau » (souvenirs normaux) et « noyau-prive » (local uniquement).

    Rien n'est effacé : les souvenirs gardent leur contenu et reçoivent le tag « noyau-converti » à la place de
    « noyau » (ils ne sont donc plus injectés deux fois). Réversible en remettant le tag.
    """
    comptes = {}
    tous = await lire_noyau(base, exclure_local=False, budget=10**7, limite=10_000)
    for label, prive in (("noyau", False), ("noyau-prive", True)):
        choisis = [s for s in tous if (s.confidentialite == "local_uniquement") is prive]
        if not choisis:
            continue
        contenu = "\n".join(f"- {' '.join(s.contenu.split())}" for s in reversed(choisis))[:LIMITE_MAX]
        await ecrire(base, label, contenu, auteur, "local_uniquement" if prive else "normal", len(contenu) + 1000)
        comptes[label] = len(choisis)
    for s in tous:
        await base.execute(
            "UPDATE memoires SET tags = $2, maj_le = now() WHERE id = $1",
            s.id,
            [t if t != TAG_NOYAU else "noyau-converti" for t in s.tags],
        )
    return comptes
