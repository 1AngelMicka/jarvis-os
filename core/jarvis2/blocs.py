"""Blocs de mémoire éditables (à la Letta) : textes courts toujours injectés, tenus par l'utilisateur et JARVIS.

Chaque modification crée une version (table `memory_block_versions`) : l'historique est complet, rien n'est perdu.
Un bloc « local_uniquement » n'est jamais envoyé à une IA externe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from .db import Base, Connexion, Executant
from .memoire import TAG_NOYAU, lire_noyau

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

    def en_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "content": self.content,
            "version": self.version,
            "char_limit": self.char_limit,
            "confidentialite": self.confidentialite,
            "maj_le": self.maj_le.isoformat(),
        }


def _bloc(r: Any) -> Bloc:
    return Bloc(r["label"], r["content"], r["version"], r["char_limit"], r["confidentialite"], r["maj_le"])


async def lister(conn: Executant, exclure_local: bool = False, vides: bool = False) -> list[Bloc]:
    lignes = await conn.fetch(
        "SELECT label, content, version, char_limit, confidentialite, maj_le FROM memory_blocks"
        " WHERE ($2 OR content <> '') AND (NOT $1 OR confidentialite <> 'local_uniquement') ORDER BY label",
        exclure_local,
        vides,
    )
    return [_bloc(r) for r in lignes]


async def ecrire(
    base: Executant,
    label: str,
    contenu: str,
    auteur: str,
    confidentialite: str | None = None,
    char_limit: int | None = None,
) -> Bloc:
    """Crée ou modifie un bloc ; chaque écriture est une nouvelle version gardée."""
    if not LABEL.match(label):
        raise ErreurBloc("Nom de bloc : minuscules, chiffres et . _ : - (64 caractères au plus)")
    if confidentialite not in (None, "normal", "local_uniquement"):
        raise ErreurBloc("Confidentialité : normal ou local_uniquement")
    if hasattr(base, "acquire"):
        async with cast(Base, base).acquire() as c:
            return await ecrire(c, label, contenu, auteur, confidentialite, char_limit)
    conn = cast(Connexion, base)
    async with conn.transaction():
        actuel = await conn.fetchrow("SELECT id, version, char_limit FROM memory_blocks WHERE label = $1", label)
        limite = min(max(char_limit or (actuel["char_limit"] if actuel else LIMITE_DEFAUT), 1), LIMITE_MAX)
        if len(contenu) > limite:
            raise ErreurBloc(f"Bloc trop long : {len(contenu)} caractères pour {limite} au plus")
        if actuel is None:
            ligne = await conn.fetchrow(
                "INSERT INTO memory_blocks (label, content, char_limit, confidentialite) VALUES ($1, $2, $3, $4)"
                " RETURNING id, version",
                label,
                contenu,
                limite,
                confidentialite or "normal",
            )
        else:
            ligne = await conn.fetchrow(
                "UPDATE memory_blocks SET content = $2, char_limit = $3, version = version + 1, maj_le = now(),"
                " confidentialite = coalesce($4, confidentialite) WHERE label = $1 RETURNING id, version",
                label,
                contenu,
                limite,
                confidentialite,
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
            "SELECT label, content, version, char_limit, confidentialite, maj_le FROM memory_blocks WHERE label = $1",
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
