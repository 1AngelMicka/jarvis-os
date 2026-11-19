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
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from ..db import Connexion, Executant, Ligne

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


def _appareil(r: Ligne) -> Appareil:
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
        f" AND (dernier_acces IS NULL OR dernier_acces < $2) RETURNING {COLONNES}",
        empreinte(jeton),
        datetime.now(UTC) - timedelta(minutes=1),
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
        await conn.verrouiller(726005)
        if not await premier_possible(conn):
            raise ErreurJumelage("Un appareil est déjà enregistré : utilisez le jumelage")
        return await creer(conn, nom, "pc")


async def creer_jumelage(conn: Executant, cree_par: UUID | None, type_: str = "telephone") -> tuple[str, datetime]:
    code = nouveau_secret()
    expire: datetime = await conn.fetchval(
        "INSERT INTO jumelages (code_hash, cree_par, type, expire_le) VALUES ($1, $2, $3, $4) RETURNING expire_le",
        empreinte(code),
        cree_par,
        type_,
        datetime.now(UTC) + DUREE_JUMELAGE,
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


# --- Limite de tentatives au jumelage --------------------------------------------------------------------------
# Un code vaut 256 bits : il ne se devine pas. La limite coupe court aux essais en rafale (et les rend visibles
# dans l'audit) : 5 échecs par source, ou 20 au total, en 15 minutes bloquent l'échange. Créer un nouveau code
# depuis un appareil autorisé lève le blocage (c'est l'utilisateur qui est là).
FENETRE_TENTATIVES = timedelta(minutes=15)
ECHECS_PAR_SOURCE = 5
ECHECS_GLOBAUX = 20


async def jumelage_bloque(conn: Executant, source: str) -> bool:
    depuis = datetime.now(UTC) - FENETRE_TENTATIVES
    await conn.execute("DELETE FROM tentatives_jumelage WHERE le < $1", depuis)
    total = await conn.fetchval("SELECT count(*) FROM tentatives_jumelage WHERE le >= $1", depuis)
    par_source = await conn.fetchval(
        "SELECT count(*) FROM tentatives_jumelage WHERE le >= $1 AND source = $2", depuis, source[:100]
    )
    return int(total) >= ECHECS_GLOBAUX or int(par_source) >= ECHECS_PAR_SOURCE


async def noter_echec_jumelage(conn: Executant, source: str) -> None:
    await conn.execute("INSERT INTO tentatives_jumelage (source) VALUES ($1)", source[:100])


async def effacer_tentatives(conn: Executant, source: str | None = None) -> None:
    if source is None:
        await conn.execute("DELETE FROM tentatives_jumelage")
    else:
        await conn.execute("DELETE FROM tentatives_jumelage WHERE source = $1", source[:100])
