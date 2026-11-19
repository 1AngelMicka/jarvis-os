"""Enveloppe de télémétrie (idée d'OpenJarvis : `InstrumentedEngine`).

`MoteurInstrumente` entoure n'importe quel moteur et laisse une `Mesure` par appel : latence totale,
délai du premier morceau, jetons, coût (0 pour l'abonnement Claude et pour Ollama), statut.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from ..db import Base, ErreurBaseOuReseau
from .base import Delta, ErreurMoteur, EtatSante, Evenement, Fin, InfoModele, Message, Moteur, Options, Reponse

journal = logging.getLogger("jarvis2.telemetrie")


@dataclass(slots=True)
class Mesure:
    moteur: str
    modele: str | None
    operation: str
    statut: str
    latence_ms: int
    premier_jeton_ms: int | None = None
    jetons_entree: int | None = None
    jetons_sortie: int | None = None
    cout_usd: float = 0.0
    erreur: str | None = None
    conversation_id: UUID | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class Enregistreur(Protocol):
    async def enregistrer(self, mesure: Mesure) -> None: ...


class EnregistreurMemoire:
    """Garde les mesures en mémoire (tests, mode sans base)."""

    def __init__(self) -> None:
        self.mesures: list[Mesure] = []

    async def enregistrer(self, mesure: Mesure) -> None:
        self.mesures.append(mesure)


class EnregistreurBase:
    def __init__(self, pool: Base) -> None:
        self.pool = pool

    async def enregistrer(self, mesure: Mesure) -> None:
        try:
            await self.pool.execute(
                "INSERT INTO telemetrie (moteur, modele, operation, statut, latence_ms, premier_jeton_ms,"
                " jetons_entree, jetons_sortie, cout_usd, erreur, conversation_id, meta)"
                " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)",
                mesure.moteur,
                mesure.modele,
                mesure.operation,
                mesure.statut,
                mesure.latence_ms,
                mesure.premier_jeton_ms,
                mesure.jetons_entree,
                mesure.jetons_sortie,
                mesure.cout_usd,
                mesure.erreur,
                mesure.conversation_id,
                mesure.meta,
            )
        except ErreurBaseOuReseau:  # la télémétrie ne doit jamais casser une réponse
            journal.exception("Télémétrie non enregistrée")


def _ms(depuis: float) -> int:
    return round((time.perf_counter() - depuis) * 1000)


class MoteurInstrumente(Moteur):
    """Même contrat que le moteur enveloppé ; chaque appel produit une `Mesure`."""

    id = "instrumente"
    nom = "instrumenté"

    def __init__(self, interne: Moteur, enregistreur: Enregistreur) -> None:
        self.interne = interne
        self.enregistreur = enregistreur
        # Vérification avant chaque appel (plafond de dépenses) : lève `ErreurMoteur` pour refuser clairement
        self.garde: Callable[[str], Awaitable[None]] | None = None

    async def _garder(self) -> None:
        if self.garde is not None:
            await self.garde(self.interne.id)

    @property
    def id_moteur(self) -> str:
        return self.interne.id

    async def _noter(self, mesure: Mesure) -> None:
        await self.enregistreur.enregistrer(mesure)

    def _mesure(
        self,
        operation: str,
        debut: float,
        options: Options | None,
        conversation_id: UUID | None,
        reponse: Reponse | None = None,
        statut: str = "ok",
        erreur: str | None = None,
        premier: int | None = None,
    ) -> Mesure:
        meta = dict(reponse.meta) if reponse else {}
        if options is not None and options.route:  # score de la route (routage.py), même en erreur
            meta["route"] = options.route
        return Mesure(
            moteur=self.interne.id,
            modele=(reponse.modele if reponse else None) or (options.modele if options else None),
            operation=operation,
            statut=statut,
            latence_ms=_ms(debut),
            premier_jeton_ms=premier,
            jetons_entree=reponse.usage.jetons_entree if reponse else None,
            jetons_sortie=reponse.usage.jetons_sortie if reponse else None,
            cout_usd=reponse.cout_usd if reponse else 0.0,
            erreur=erreur,
            conversation_id=conversation_id,
            meta=meta,
        )

    def stream(
        self, messages: Sequence[Message], options: Options | None = None, conversation_id: UUID | None = None
    ) -> AsyncGenerator[Evenement]:
        return self._stream(messages, options, conversation_id)

    async def _stream(
        self, messages: Sequence[Message], options: Options | None, conversation_id: UUID | None
    ) -> AsyncGenerator[Evenement]:
        await self._garder()
        debut = time.perf_counter()
        premier: int | None = None
        try:
            async for evenement in self.interne.stream(messages, options):
                if isinstance(evenement, Delta) and premier is None:
                    premier = _ms(debut)
                if isinstance(evenement, Fin):
                    await self._noter(
                        self._mesure("stream", debut, options, conversation_id, evenement.reponse, premier=premier)
                    )
                yield evenement
        except ErreurMoteur as exc:
            await self._noter(
                self._mesure(
                    "stream", debut, options, conversation_id, statut="erreur", erreur=str(exc), premier=premier
                )
            )
            raise
        except (asyncio.CancelledError, GeneratorExit):
            await asyncio.shield(
                self._noter(self._mesure("stream", debut, options, conversation_id, statut="annule", premier=premier))
            )
            raise

    async def generate(
        self, messages: Sequence[Message], options: Options | None = None, conversation_id: UUID | None = None
    ) -> Reponse:
        await self._garder()
        debut = time.perf_counter()
        try:
            reponse = await self.interne.generate(messages, options)
        except ErreurMoteur as exc:
            await self._noter(
                self._mesure("generate", debut, options, conversation_id, statut="erreur", erreur=str(exc))
            )
            raise
        await self._noter(self._mesure("generate", debut, options, conversation_id, reponse))
        return reponse

    async def list_models(self) -> list[InfoModele]:
        return await self.interne.list_models()

    async def health(self) -> EtatSante:
        return await self.interne.health()

    async def fermer(self) -> None:
        await self.interne.fermer()
