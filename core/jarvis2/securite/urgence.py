"""Arrêt d'urgence : coupe tout de suite les réponses en cours et refuse toute écriture (HTTP 423).

L'état est gardé en base (il survit à un redémarrage) et en mémoire (contrôle instantané à chaque requête).
Lever l'arrêt est une action 🔴 (clé d'accès).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from ..db import Executant

journal = logging.getLogger("jarvis2.urgence")


class ArretUrgence:
    def __init__(self) -> None:
        self.actif = False
        self.depuis: datetime | None = None
        self.par: str | None = None
        self._taches: set[asyncio.Task[Any]] = set()

    async def charger(self, conn: Executant) -> None:
        valeur = await conn.fetchval("SELECT valeur FROM etat_systeme WHERE cle = 'arret_urgence'")
        etat = valeur if isinstance(valeur, dict) else json.loads(valeur or "{}")
        self.actif = bool(etat.get("actif"))
        self.par = etat.get("par")
        self.depuis = datetime.fromisoformat(etat["depuis"]) if etat.get("depuis") else None

    @contextmanager
    def suivre(self) -> Iterator[None]:
        """Inscrit la tâche courante (une réponse en cours) : l'arrêt d'urgence l'annulera."""
        tache = asyncio.current_task()
        if tache is not None:
            self._taches.add(tache)
        try:
            yield
        finally:
            if tache is not None:
                self._taches.discard(tache)

    @property
    def en_cours(self) -> int:
        return len(self._taches)

    async def arreter(self, conn: Executant, par: str) -> int:
        """Active l'arrêt, annule toutes les réponses en cours ; renvoie leur nombre."""
        self.actif, self.par, self.depuis = True, par, datetime.now(UTC)
        taches = list(self._taches)
        for t in taches:
            t.cancel()
        await self._enregistrer(conn)
        journal.warning("ARRÊT D'URGENCE par %s : %d réponse(s) interrompue(s)", par, len(taches))
        return len(taches)

    async def lever(self, conn: Executant) -> None:
        self.actif, self.par, self.depuis = False, None, None
        await self._enregistrer(conn)

    async def _enregistrer(self, conn: Executant) -> None:
        valeur = {"actif": self.actif, "par": self.par, "depuis": self.depuis.isoformat() if self.depuis else None}
        await conn.execute(
            "UPDATE etat_systeme SET valeur = $1::text::jsonb, maj_le = now() WHERE cle = 'arret_urgence'",
            json.dumps(valeur),
        )

    def en_dict(self) -> dict[str, Any]:
        return {"actif": self.actif, "par": self.par, "depuis": self.depuis.isoformat() if self.depuis else None}
