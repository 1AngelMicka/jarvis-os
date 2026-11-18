"""Journal d'audit en ajout seul, chaîné par empreintes SHA-256 (voir la migration 004).

Le rôle applicatif n'écrit que par la fonction `audit_ajouter()` ; il ne peut ni modifier ni effacer une entrée.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from ..db import Executant

Niveau = Literal["vert", "jaune", "rouge"]


async def journaliser(
    conn: Executant,
    *,
    acteur: str,
    action: str,
    niveau: Niveau = "vert",
    cible: str | None = None,
    details: dict[str, Any] | None = None,
    resultat: str = "ok",
) -> dict[str, Any]:
    ligne = await conn.fetchrow(
        "SELECT id, horodatage, hash FROM audit_ajouter($1, $2, $3, $4, $5::text::jsonb, $6)",
        acteur,
        action,
        niveau,
        cible,
        json.dumps(details or {}, ensure_ascii=False),
        resultat,
    )
    assert ligne is not None
    return {"id": ligne["id"], "horodatage": ligne["horodatage"].isoformat(), "hash": ligne["hash"]}


async def verifier(conn: Executant) -> int | None:
    """Identifiant de la première entrée altérée, ou None si la chaîne est intacte."""
    rompue: int | None = await conn.fetchval("SELECT audit_verifier()")
    return rompue


async def lister(conn: Executant, limite: int = 50) -> list[dict[str, Any]]:
    lignes = await conn.fetch(
        "SELECT id, horodatage, acteur, action, niveau, cible, details, resultat FROM audit ORDER BY id DESC LIMIT $1",
        limite,
    )
    return [{**dict(r), "horodatage": r["horodatage"].isoformat()} for r in lignes]
