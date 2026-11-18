"""Journal d'audit en ajout seul, chaîné par empreintes SHA-256.

- PostgreSQL (migration 004) : le rôle applicatif n'écrit que par `audit_ajouter()` (SECURITY DEFINER) ; il ne peut ni
  modifier ni effacer une entrée.
- SQLite : l'entrée est chaînée ici, dans une transaction d'écriture ; des déclencheurs refusent UPDATE et DELETE.

Le texte canonique d'une entrée est le même dans les deux moteurs (celui d'`audit_canonique()`) : un journal copié
d'un stockage à l'autre se vérifie à l'identique.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal, cast

from ..db import Base, Connexion, Executant

Niveau = Literal["vert", "jaune", "rouge"]
ORIGINE = "0" * 64


def texte_jsonb(valeur: Any) -> str:
    """Texte d'une valeur JSON tel que PostgreSQL l'écrit pour `jsonb` (clés triées par longueur puis octets)."""
    if isinstance(valeur, dict):
        cles = sorted(valeur, key=lambda c: (len(str(c).encode()), str(c).encode()))
        return (
            "{" + ", ".join(f"{json.dumps(str(c), ensure_ascii=False)}: {texte_jsonb(valeur[c])}" for c in cles) + "}"
        )
    if isinstance(valeur, list | tuple):
        return "[" + ", ".join(texte_jsonb(v) for v in valeur) + "]"
    return json.dumps(valeur, ensure_ascii=False)


def canonique(e: dict[str, Any]) -> str:
    horodatage: datetime = e["horodatage"]
    details = e["details"] if not isinstance(e["details"], str) else json.loads(e["details"])
    return "|".join(
        [
            str(e["id"]),
            horodatage.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            e["acteur"],
            e["action"],
            e["niveau"],
            e["cible"] or "",
            texte_jsonb(details),
            e["resultat"],
            e["hash_prec"],
        ]
    )


def empreinte(e: dict[str, Any]) -> str:
    return hashlib.sha256(canonique(e).encode()).hexdigest()


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
    if conn.dialecte == "sqlite":
        return await _journaliser_sqlite(conn, acteur, action, niveau, cible, details or {}, resultat)
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


async def _journaliser_sqlite(
    conn: Executant, acteur: str, action: str, niveau: str, cible: str | None, details: dict[str, Any], resultat: str
) -> dict[str, Any]:
    if hasattr(conn, "acquire"):  # la base elle-même : une connexion le temps de l'écriture
        async with cast(Base, conn).acquire() as c:
            return await _journaliser_sqlite(c, acteur, action, niveau, cible, details, resultat)
    connexion = cast(Connexion, conn)
    async with connexion.transaction():  # BEGIN IMMEDIATE : une seule écriture à la fois, chaîne linéaire
        prec = await connexion.fetchrow("SELECT id, hash FROM audit ORDER BY id DESC LIMIT 1")
        e: dict[str, Any] = {
            "id": prec["id"] + 1 if prec else 1,
            "horodatage": datetime.now(UTC),
            "acteur": acteur,
            "action": action,
            "niveau": niveau,
            "cible": cible,
            "details": details,
            "resultat": resultat,
            "hash_prec": prec["hash"] if prec else ORIGINE,
        }
        e["hash"] = empreinte(e)
        await connexion.execute(
            "INSERT INTO audit (id, horodatage, acteur, action, niveau, cible, details, resultat, hash_prec, hash)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
            *e.values(),
        )
    return {"id": e["id"], "horodatage": e["horodatage"].isoformat(), "hash": e["hash"]}


async def verifier(conn: Executant) -> int | None:
    """Identifiant de la première entrée altérée, ou None si la chaîne est intacte."""
    if conn.dialecte == "postgres":
        rompue: int | None = await conn.fetchval("SELECT audit_verifier()")
        return rompue
    attendu = ORIGINE
    for ligne in await conn.fetch(
        "SELECT id, horodatage, acteur, action, niveau, cible, details, resultat, hash_prec, hash FROM audit"
        " ORDER BY id"
    ):
        e = dict(ligne)
        if e["hash_prec"] != attendu or e["hash"] != empreinte(e):
            return int(e["id"])
        attendu = e["hash"]
    return None


async def lister(conn: Executant, limite: int = 50) -> list[dict[str, Any]]:
    lignes = await conn.fetch(
        "SELECT id, horodatage, acteur, action, niveau, cible, details, resultat FROM audit ORDER BY id DESC LIMIT $1",
        limite,
    )
    return [{**dict(r), "horodatage": r["horodatage"].isoformat()} for r in lignes]
