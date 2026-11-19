"""Copie complète d'un stockage vers l'autre (PostgreSQL ⇄ SQLite), vers un stockage cible VIDE.

Tout est copié tel quel : identifiants, dates, vecteurs, journal d'audit (empreintes comprises : la chaîne se
vérifie à l'identique dans la cible). Le plein texte est recalculé par la cible (tsvector français ou FTS5).
La source n'est que lue. La cible est vérifiée après la copie : mêmes nombres de lignes, chaîne d'audit intacte,
clés étrangères cohérentes.

PostgreSQL cible : rôle propriétaire (seul à pouvoir écrire l'audit et suspendre les contrôles le temps de la copie).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .db import Base, Connexion, Executant
from .securite import audit

journal = logging.getLogger("jarvis2.stockage")

# Ordre des clés étrangères (les contrôles sont de toute façon suspendus pendant la copie)
TABLES = (
    "conversations",
    "memoires",
    "messages",
    "telemetrie",
    "profil_reponses",
    "missions",
    "creations",
    "creation_versions",
    "creation_donnees",
    "chantiers",
    "imports",
    "memory_blocks",
    "memory_block_versions",
    "appareils",
    "jumelages",
    "cles_acces",
    "defis_webauthn",
    "demandes",
    "etat_systeme",
    "connecteurs",
    "regles_protection",
    "commandes_rapides",
    "autorisations_permanentes",
    "audit",
)
SEQUENCES = ("messages", "telemetrie", "imports", "audit")  # identifiants entiers auto-incrémentés (PostgreSQL)
TEMOINS_VIDE = ("conversations", "memoires", "appareils", "audit")


class ErreurCopie(RuntimeError):
    pass


@dataclass
class RapportCopie:
    lignes: dict[str, int] = field(default_factory=dict)
    ecarts: dict[str, tuple[int, int]] = field(default_factory=dict)
    audit_intact: bool = False

    @property
    def complet(self) -> bool:
        return not self.ecarts and self.audit_intact

    def texte(self) -> str:
        lignes = [f"  {t} : {n}" for t, n in self.lignes.items() if n]
        lignes += [f"  ÉCART {t} : source {a}, cible {b}" for t, (a, b) in self.ecarts.items()]
        lignes.append(f"  Journal d'audit : {'chaîne intacte' if self.audit_intact else 'ALTÉRÉ'}")
        return "Copie " + ("terminée" if self.complet else "INCOMPLÈTE") + " :\n" + "\n".join(lignes)


async def colonnes(base: Executant, table: str) -> list[str]:
    if base.dialecte == "sqlite":
        return [r["name"] for r in await base.fetch(f"SELECT name FROM pragma_table_info('{table}')")]  # noqa: S608
    lignes = await base.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = $1"
        " ORDER BY ordinal_position",
        table,
    )
    return [r["column_name"] for r in lignes]


async def verifier_vide(cible: Executant) -> None:
    for table in TEMOINS_VIDE:
        if await cible.fetchval(f"SELECT count(*) FROM {table}"):  # noqa: S608 — noms constants
            raise ErreurCopie(f"Le stockage cible n'est pas vide (table {table}) : copie refusée")


async def _copier_table(source: Executant, cible: Connexion, table: str) -> int:
    communes = [c for c in await colonnes(source, table) if c in set(await colonnes(cible, table)) and c != "tsv"]
    if not communes:
        return 0
    liste = ", ".join(communes)
    valeurs = [f"${i}" for i in range(1, len(communes) + 1)]
    noms = list(communes)
    if cible.dialecte == "postgres" and table == "memoires":  # plein texte français recalculé
        noms.append("tsv")
        valeurs.append(f"to_tsvector('french', ${communes.index('contenu') + 1})")
    requete = f"INSERT INTO {table} ({', '.join(noms)}) VALUES ({', '.join(valeurs)})"  # noqa: S608 — constantes
    if table == "etat_systeme":  # ligne créée par les migrations de la cible : remplacée
        await cible.execute("DELETE FROM etat_systeme")
    lignes = await source.fetch(f"SELECT {liste} FROM {table}")  # noqa: S608 — constantes
    for ligne in lignes:
        await cible.execute(requete, *[_valeur(ligne[c]) for c in communes])
    return len(lignes)


def _valeur(v: Any) -> Any:
    """Types d'un moteur → types Python standards (UUID d'asyncpg, numeric)."""
    if isinstance(v, uuid.UUID):
        return uuid.UUID(int=v.int)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, list):
        return [_valeur(x) for x in v]
    if hasattr(v, "to_numpy"):  # pgvector.Vector
        return v.to_numpy()
    return v


async def copier(source: Base, cible: Base) -> RapportCopie:
    """Copie tout `source` dans `cible` (déjà migrée, vide), puis vérifie."""
    if source.dialecte == cible.dialecte:
        raise ErreurCopie("La source et la cible utilisent le même moteur")
    await verifier_vide(cible)
    rapport = RapportCopie()
    if cible.dialecte == "sqlite":
        await cible.execute("PRAGMA foreign_keys = OFF")  # hors transaction ; rétabli à la fin
    try:
        async with cible.acquire() as conn, conn.transaction():
            if cible.dialecte == "postgres":
                await conn.execute("SET LOCAL session_replication_role = replica")  # contrôles suspendus
            for table in TABLES:
                rapport.lignes[table] = await _copier_table(source, conn, table)
                journal.info("Copie : %s (%d lignes)", table, rapport.lignes[table])
            if cible.dialecte == "postgres":
                for table in SEQUENCES:
                    await conn.execute(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'),"  # noqa: S608 — constantes
                        f" GREATEST((SELECT max(id) FROM {table}), 1))"
                    )
            elif await conn.fetch("PRAGMA foreign_key_check"):
                raise ErreurCopie("Clés étrangères incohérentes dans la cible")
    finally:
        if cible.dialecte == "sqlite":
            await cible.execute("PRAGMA foreign_keys = ON")
    for table in TABLES:
        a = await source.fetchval(f"SELECT count(*) FROM {table}")  # noqa: S608 — constantes
        b = await cible.fetchval(f"SELECT count(*) FROM {table}")  # noqa: S608 — constantes
        if a != b:
            rapport.ecarts[table] = (int(a), int(b))
    rapport.audit_intact = await audit.verifier(cible) is None
    return rapport
