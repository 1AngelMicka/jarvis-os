"""Appareils autorisés et jumelage.

- Un appareil s'authentifie par un jeton aléatoire (32 octets), envoyé en `Authorization: Bearer`. Seule son
  empreinte SHA-256 est stockée ; un appareil révoqué ne passe plus.
- Jumelage : un appareil déjà autorisé (ou la ligne de commande sur le PC) crée un code à usage unique valable
  5 minutes, montré en QR ; le nouvel appareil l'échange contre son propre jeton.
- Premier appareil : tant qu'AUCUN appareil n'a jamais été enregistré, le navigateur du PC (boucle locale) peut
  s'enregistrer directement ; ensuite, seul le jumelage le permet.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import asyncpg

from ..db import Connexion, Executant

DUREE_JUMELAGE = timedelta(minutes=5)


def empreinte(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def nouveau_secret() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True, slots=True)
class Appareil:
    id: UUID
    nom: str
    type: str
    cree_le: datetime
    dernier_acces: datetime | None
    revoque_le: datetime | None

    @property
    def acteur(self) -> str:
        return f"appareil:{self.nom}"

    def en_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "nom": self.nom,
            "type": self.type,
            "cree_le": self.cree_le.isoformat(),
            "dernier_acces": self.dernier_acces.isoformat() if self.dernier_acces else None,
            "revoque": self.revoque_le is not None,
        }


COLONNES = "id, nom, type, cree_le, dernier_acces, revoque_le"


def _appareil(r: asyncpg.Record) -> Appareil:
    return Appareil(r["id"], r["nom"], r["type"], r["cree_le"], r["dernier_acces"], r["revoque_le"])


class ErreurJumelage(Exception):
    """Code inconnu, expiré ou déjà utilisé, ou premier appareil déjà enregistré."""


async def creer(conn: Executant, nom: str, type_: str, cree_par: UUID | None = None) -> tuple[Appareil, str]:
    jeton = nouveau_secret()
    ligne = await conn.fetchrow(
        f"INSERT INTO appareils (nom, type, jeton_hash, cree_par) VALUES ($1, $2, $3, $4) RETURNING {COLONNES}",
        nom.strip()[:80] or "Appareil",
        type_,
        empreinte(jeton),
        cree_par,
    )
    assert ligne is not None
    return _appareil(ligne), jeton


async def authentifier(conn: Executant, jeton: str) -> Appareil | None:
    """Appareil non révoqué correspondant au jeton (dernier accès noté au plus une fois par minute)."""
    ligne = await conn.fetchrow(
        "UPDATE appareils SET dernier_acces = now()"
        " WHERE jeton_hash = $1 AND revoque_le IS NULL"
        f" AND (dernier_acces IS NULL OR dernier_acces < now() - interval '1 minute') RETURNING {COLONNES}",
        empreinte(jeton),
    )
    if ligne is None:
        ligne = await conn.fetchrow(
            f"SELECT {COLONNES} FROM appareils WHERE jeton_hash = $1 AND revoque_le IS NULL",
            empreinte(jeton),
        )
    return _appareil(ligne) if ligne else None


async def lister(conn: Executant) -> list[Appareil]:
    lignes = await conn.fetch(f"SELECT {COLONNES} FROM appareils ORDER BY revoque_le NULLS FIRST, cree_le")
    return [_appareil(r) for r in lignes]


async def revoquer(conn: Executant, appareil_id: UUID) -> bool:
    statut = await conn.execute(
        "UPDATE appareils SET revoque_le = now() WHERE id = $1 AND revoque_le IS NULL", appareil_id
    )
    return statut.endswith(" 1")


async def premier_possible(conn: Executant) -> bool:
    return not await conn.fetchval("SELECT EXISTS (SELECT 1 FROM appareils)")


async def creer_premier(conn: Connexion, nom: str) -> tuple[Appareil, str]:
    """Premier appareil : refusé dès qu'un appareil a existé (verrou contre deux premiers simultanés)."""
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(726005)")
        if not await premier_possible(conn):
            raise ErreurJumelage("Un appareil est déjà enregistré : utilisez le jumelage")
        return await creer(conn, nom, "pc")


async def creer_jumelage(conn: Executant, cree_par: UUID | None, type_: str = "telephone") -> tuple[str, datetime]:
    code = nouveau_secret()
    expire: datetime = await conn.fetchval(
        "INSERT INTO jumelages (code_hash, cree_par, type, expire_le) VALUES ($1, $2, $3, now() + $4)"
        " RETURNING expire_le",
        empreinte(code),
        cree_par,
        type_,
        DUREE_JUMELAGE,
    )
    return code, expire


async def echanger_jumelage(conn: Connexion, code: str, nom: str) -> tuple[Appareil, str]:
    """Code -> nouvel appareil et son jeton. Le code ne sert qu'une fois, dans les 5 minutes."""
    async with conn.transaction():
        ligne = await conn.fetchrow(
            "UPDATE jumelages SET utilise_le = now() WHERE code_hash = $1 AND utilise_le IS NULL"
            " AND expire_le > now() RETURNING cree_par, type",
            empreinte(code),
        )
        if ligne is None:
            raise ErreurJumelage("Code de jumelage inconnu, expiré ou déjà utilisé")
        appareil, jeton = await creer(conn, nom, ligne["type"], ligne["cree_par"])
        await conn.execute("UPDATE jumelages SET appareil = $1 WHERE code_hash = $2", appareil.id, empreinte(code))
    return appareil, jeton
