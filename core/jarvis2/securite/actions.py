"""Actions déclarées et leur niveau. Toute action qui modifie ou détruit passe par la file d'approbations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ..db import Connexion
from .permissions import Action, ErreurAction, Registre
from .urgence import ArretUrgence


def _uuid(params: dict[str, Any], cle: str) -> UUID:
    try:
        return UUID(str(params[cle]))
    except (KeyError, ValueError) as exc:
        raise ErreurAction(f"Paramètre « {cle} » manquant ou invalide") from exc


async def _titre(conn: Connexion, conversation: UUID) -> str:
    titre: str | None = await conn.fetchval("SELECT titre FROM conversations WHERE id = $1", conversation)
    if titre is None:
        raise ErreurAction("Conversation introuvable")
    return titre


def creer_registre(urgence: ArretUrgence) -> Registre:
    registre = Registre()

    async def archiver_conversation(conn: Connexion, p: dict[str, Any]) -> dict[str, Any]:
        ident = _uuid(p, "conversation_id")
        titre = await _titre(conn, ident)
        await conn.execute("UPDATE conversations SET archivee = true WHERE id = $1", ident)
        return {"conversation_id": str(ident), "titre": titre}

    async def supprimer_conversation(conn: Connexion, p: dict[str, Any]) -> dict[str, Any]:
        ident = _uuid(p, "conversation_id")
        titre = await _titre(conn, ident)
        nb = await conn.fetchval("SELECT count(*) FROM messages WHERE conversation_id = $1", ident)
        await conn.execute("DELETE FROM conversations WHERE id = $1", ident)
        return {"conversation_id": str(ident), "titre": titre, "messages_supprimes": nb}

    async def archiver_souvenir(conn: Connexion, p: dict[str, Any]) -> dict[str, Any]:
        ident = _uuid(p, "souvenir_id")
        statut = await conn.execute("UPDATE memoires SET archived = true, maj_le = now() WHERE id = $1", ident)
        if statut.endswith(" 0"):
            raise ErreurAction("Souvenir introuvable")
        return {"souvenir_id": str(ident)}  # archivé, jamais effacé : réversible

    async def lever_urgence(conn: Connexion, p: dict[str, Any]) -> dict[str, Any]:
        if not urgence.actif:
            raise ErreurAction("L'arrêt d'urgence n'est pas actif")
        await urgence.lever(conn)
        return {"arret_urgence": False}

    registre.ajouter(
        Action(
            "conversation.archiver",
            "jaune",
            "Archiver une conversation (réversible)",
            lambda p: f"Archiver la conversation « {p.get('titre') or p.get('conversation_id')} »",
            archiver_conversation,
        )
    )
    registre.ajouter(
        Action(
            "conversation.supprimer",
            "rouge",
            "Supprimer définitivement une conversation et ses messages",
            lambda p: f"Supprimer DÉFINITIVEMENT la conversation « {p.get('titre') or p.get('conversation_id')} »",
            supprimer_conversation,
        )
    )
    registre.ajouter(
        Action(
            "memoire.archiver",
            "jaune",
            "Archiver un souvenir (il n'est plus utilisé, mais reste restaurable)",
            lambda p: f"Archiver le souvenir {p.get('souvenir_id')}",
            archiver_souvenir,
        )
    )
    registre.ajouter(
        Action(
            "urgence.lever",
            "rouge",
            "Lever l'arrêt d'urgence",
            lambda p: "Lever l'arrêt d'urgence et reprendre le fonctionnement normal",
            lever_urgence,
        )
    )
    return registre
