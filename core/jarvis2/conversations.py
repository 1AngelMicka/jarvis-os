"""Conversations et messages stockés dans PostgreSQL (rôle applicatif)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from .db import Base, Ligne

LONGUEUR_TITRE = 60


def titre_provisoire(message: str) -> str:
    """Début du premier message, coupé à un mot : titre « extrait » en attendant mieux."""
    texte = " ".join(message.split())
    if len(texte) <= LONGUEUR_TITRE:
        return texte or "Nouvelle conversation"
    coupe = texte[:LONGUEUR_TITRE].rsplit(" ", 1)[0]
    return (coupe or texte[:LONGUEUR_TITRE]) + "…"


@dataclass(frozen=True, slots=True)
class Conversation:
    id: UUID
    titre: str
    titre_source: str
    epinglee: bool
    archivee: bool
    cree_le: datetime
    maj_le: datetime
    nb_messages: int = 0
    connecteur: str | None = None  # choix imposé pour cette conversation
    modele: str | None = None

    def en_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "titre": self.titre,
            "titre_source": self.titre_source,
            "epinglee": self.epinglee,
            "archivee": self.archivee,
            "cree_le": self.cree_le.isoformat(),
            "maj_le": self.maj_le.isoformat(),
            "nb_messages": self.nb_messages,
            "connecteur": self.connecteur,
            "modele": self.modele,
        }


@dataclass(frozen=True, slots=True)
class MessageStocke:
    id: int
    role: str
    contenu: str
    horodatage: datetime
    meta: dict[str, Any]

    def en_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "contenu": self.contenu,
            "horodatage": self.horodatage.isoformat(),
            "meta": self.meta,
        }


COLONNES = "c.id, c.titre, c.titre_source, c.epinglee, c.archivee, c.cree_le, c.maj_le, c.connecteur, c.modele"
NB_MESSAGES = "(SELECT count(*) FROM messages m WHERE m.conversation_id = c.id)::int AS nb_messages"


def _conversation(ligne: Ligne) -> Conversation:
    return Conversation(
        id=ligne["id"],
        titre=ligne["titre"],
        titre_source=ligne["titre_source"],
        epinglee=ligne["epinglee"],
        archivee=ligne["archivee"],
        cree_le=ligne["cree_le"],
        maj_le=ligne["maj_le"],
        nb_messages=ligne.get("nb_messages", 0),
        connecteur=ligne.get("connecteur"),
        modele=ligne.get("modele"),
    )


class DepotConversations:
    def __init__(self, pool: Base) -> None:
        self.pool = pool

    async def creer(self, titre: str = "Nouvelle conversation") -> Conversation:
        # RETURNING sans préfixe de table (SQLite ne l'accepte pas)
        requete = f"INSERT INTO conversations (titre) VALUES ($1) RETURNING {COLONNES.replace('c.', '')}"  # noqa: S608
        ligne = await self.pool.fetchrow(requete, titre)
        assert ligne is not None
        return _conversation(ligne)

    async def obtenir(self, conversation_id: UUID) -> Conversation | None:
        ligne = await self.pool.fetchrow(
            f"SELECT {COLONNES}, {NB_MESSAGES} FROM conversations c WHERE c.id = $1",  # noqa: S608 — constantes
            conversation_id,
        )
        return _conversation(ligne) if ligne else None

    async def lister(self, limite: int = 50, archivees: bool = False) -> list[Conversation]:
        lignes = await self.pool.fetch(
            f"SELECT {COLONNES}, {NB_MESSAGES} FROM conversations c"  # noqa: S608 — constantes
            " WHERE c.archivee = $1 AND NOT c.interne"
            " ORDER BY c.epinglee DESC, c.maj_le DESC LIMIT $2",
            archivees,
            limite,
        )
        return [_conversation(ligne) for ligne in lignes]

    async def chercher(self, texte: str, archivees: bool = False, limite: int = 50) -> list[Conversation]:
        """Conversations dont le titre ou un message contient le texte (sans tenir compte de la casse)."""
        motif = "%" + texte.lower().replace("\\", "").replace("%", "").replace("_", "") + "%"
        lignes = await self.pool.fetch(
            f"SELECT {COLONNES}, {NB_MESSAGES} FROM conversations c"  # noqa: S608 — constantes
            " WHERE c.archivee = $1 AND NOT c.interne AND (lower(c.titre) LIKE $2 OR EXISTS ("
            "  SELECT 1 FROM messages m WHERE m.conversation_id = c.id AND lower(m.contenu) LIKE $2))"
            " ORDER BY c.epinglee DESC, c.maj_le DESC LIMIT $3",
            archivees,
            motif,
            limite,
        )
        return [_conversation(ligne) for ligne in lignes]

    async def modifier(
        self,
        conversation_id: UUID,
        *,
        titre: str | None = None,
        epinglee: bool | None = None,
        archivee: bool | None = None,
    ) -> Conversation | None:
        """Renommer (titre « utilisateur », plus jamais réécrit par l'IA), épingler, archiver ou restaurer."""
        if titre is not None:
            await self.renommer(conversation_id, titre, "utilisateur")
        if epinglee is not None:
            await self.pool.execute("UPDATE conversations SET epinglee = $2 WHERE id = $1", conversation_id, epinglee)
        if archivee is not None:
            await self.pool.execute("UPDATE conversations SET archivee = $2 WHERE id = $1", conversation_id, archivee)
        return await self.obtenir(conversation_id)

    async def messages(self, conversation_id: UUID, limite: int = 500) -> list[MessageStocke]:
        lignes = await self.pool.fetch(
            "SELECT id, role, contenu, horodatage, meta FROM ("
            " SELECT * FROM messages WHERE conversation_id = $1 ORDER BY id DESC LIMIT $2"
            ") m ORDER BY id",
            conversation_id,
            limite,
        )
        return [
            MessageStocke(id=r["id"], role=r["role"], contenu=r["contenu"], horodatage=r["horodatage"], meta=r["meta"])
            for r in lignes
        ]

    async def ajouter_message(
        self, conversation_id: UUID, role: str, contenu: str, meta: dict[str, Any] | None = None
    ) -> MessageStocke:
        async with self.pool.acquire() as conn, conn.transaction():
            ligne = await conn.fetchrow(
                "INSERT INTO messages (conversation_id, role, contenu, meta) VALUES ($1, $2, $3, $4)"
                " RETURNING id, role, contenu, horodatage, meta",
                conversation_id,
                role,
                contenu,
                meta or {},
            )
            await conn.execute("UPDATE conversations SET maj_le = now() WHERE id = $1", conversation_id)
        assert ligne is not None
        return MessageStocke(
            id=ligne["id"],
            role=ligne["role"],
            contenu=ligne["contenu"],
            horodatage=ligne["horodatage"],
            meta=ligne["meta"],
        )

    async def renommer(self, conversation_id: UUID, titre: str, source: str = "utilisateur") -> None:
        await self.pool.execute(
            "UPDATE conversations SET titre = $2, titre_source = $3 WHERE id = $1", conversation_id, titre, source
        )

    async def retenir_connecteur(self, conversation_id: UUID, connecteur: str | None, modele: str | None) -> None:
        """Connecteur et modèle imposés pour cette conversation (None : le routeur choisit)."""
        await self.pool.execute(
            "UPDATE conversations SET connecteur = $2, modele = $3 WHERE id = $1", conversation_id, connecteur, modele
        )
