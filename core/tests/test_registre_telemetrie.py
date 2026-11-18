"""Registre de moteurs et enveloppe de télémétrie."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence
from typing import ClassVar

import pytest

from jarvis2.journal import masquer
from jarvis2.moteurs import construire_moteurs
from jarvis2.moteurs.base import (
    Delta,
    ErreurMoteur,
    EtatSante,
    Evenement,
    Fin,
    InfoModele,
    Message,
    Moteur,
    Options,
    Reponse,
    Usage,
)
from jarvis2.moteurs.telemetrie import EnregistreurMemoire, MoteurInstrumente
from jarvis2.registre import MoteurRegistry, RegistryBase


class FauxMoteur(Moteur):
    id: ClassVar[str] = "faux"
    nom: ClassVar[str] = "Faux"

    def __init__(self, echec: bool = False, lent: bool = False) -> None:
        self.echec, self.lent = echec, lent

    async def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        await asyncio.sleep(0.01)
        yield Delta("a")
        if self.lent:
            await asyncio.sleep(10)
        if self.echec:
            raise ErreurMoteur("panne")
        yield Fin(Reponse("a", "faux-1", Usage(3, 1), 0.0, {"source_auth": "none"}))

    async def list_models(self) -> list[InfoModele]:
        return [InfoModele("faux-1", "Faux 1", True)]

    async def health(self) -> EtatSante:
        return EtatSante(True)


def test_registres_isoles() -> None:
    class A(RegistryBase[int]):
        pass

    class B(RegistryBase[int]):
        pass

    A.register("x")(1)
    assert A.contains("x") and not B.contains("x")
    with pytest.raises(ValueError, match="déjà"):
        A.register("x")(2)
    with pytest.raises(KeyError):
        B.get("x")


def test_moteurs_inscrits() -> None:
    assert {"claude_code", "ollama"} <= set(MoteurRegistry.keys())


def test_construire_moteurs_enveloppe_chacun() -> None:
    from jarvis2.config import Parametres

    moteurs = construire_moteurs(Parametres(), EnregistreurMemoire())
    assert {"claude_code", "ollama"} <= set(moteurs)
    assert all(isinstance(m, MoteurInstrumente) for m in moteurs.values())


async def test_mesure_ok() -> None:
    enr = EnregistreurMemoire()
    m = MoteurInstrumente(FauxMoteur(), enr)
    evenements = [e async for e in m.stream([Message("utilisateur", "x")])]
    assert isinstance(evenements[-1], Fin)
    (mesure,) = enr.mesures
    assert mesure.moteur == "faux" and mesure.modele == "faux-1" and mesure.statut == "ok"
    assert mesure.operation == "stream" and mesure.cout_usd == 0.0
    assert mesure.premier_jeton_ms is not None and mesure.latence_ms >= mesure.premier_jeton_ms
    assert mesure.jetons_entree == 3 and mesure.jetons_sortie == 1


async def test_mesure_erreur() -> None:
    enr = EnregistreurMemoire()
    with pytest.raises(ErreurMoteur):
        await MoteurInstrumente(FauxMoteur(echec=True), enr).generate([Message("utilisateur", "x")])
    assert enr.mesures[0].statut == "erreur" and enr.mesures[0].erreur == "panne"


async def test_mesure_annulation() -> None:
    enr = EnregistreurMemoire()
    flux = MoteurInstrumente(FauxMoteur(lent=True), enr).stream([Message("utilisateur", "x")])
    assert isinstance(await flux.__anext__(), Delta)
    await flux.aclose()
    assert enr.mesures[0].statut == "annule"


def test_masquage_des_secrets() -> None:
    assert "sk-ant" not in masquer("clé sk-ant-abcdefghijklmnopqrstuvwxyz dans le texte")
    assert masquer("postgresql://jarvis2_app:motdepasse@127.0.0.1:5433/jarvis2") == (
        "postgresql://jarvis2_app:***@127.0.0.1:5433/jarvis2"
    )
    assert masquer("rien à cacher") == "rien à cacher"
