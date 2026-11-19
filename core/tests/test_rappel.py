"""Porte de rappel : décision déterministe, sans IA, de chercher ou non dans les souvenirs."""

from __future__ import annotations

import pytest

from jarvis2.rappel import AVEC_RECHERCHE, DESCRIPTION, SANS_RECHERCHE, decider


@pytest.mark.parametrize(
    ("texte", "raison"),
    [
        ("", SANS_RECHERCHE["vide"]),
        ("   ", SANS_RECHERCHE["vide"]),
        ("/aide", SANS_RECHERCHE["commande"]),
        ("/nouvelle conversation sur mon projet", SANS_RECHERCHE["commande"]),
        ("merci", SANS_RECHERCHE["politesse"]),
        ("Merci JARVIS !", SANS_RECHERCHE["politesse"]),
        ("ok, parfait", SANS_RECHERCHE["politesse"]),
        ("Bonjour", SANS_RECHERCHE["politesse"]),
        ("d’accord, ça marche", SANS_RECHERCHE["politesse"]),
        ("ah", SANS_RECHERCHE["politesse"]),
        ("zut", SANS_RECHERCHE["court"]),
        ("…", SANS_RECHERCHE["court"]),
    ],
)
def test_sans_recherche(texte: str, raison: str) -> None:
    porte = decider(texte)
    assert porte.rappeler is False and porte.raison == raison


@pytest.mark.parametrize(
    ("texte", "raison"),
    [
        ("Tu te souviens de mon vélo ?", AVEC_RECHERCHE["memoire"]),
        ("Qu'est-ce que tu sais de moi", AVEC_RECHERCHE["memoire"]),
        ("merci, rappelle-moi le code du portail", AVEC_RECHERCHE["memoire"]),
        ("Bonjour, quel temps fera-t-il demain ?", AVEC_RECHERCHE["question"]),
        ("Combien de tomates faut-il planter", AVEC_RECHERCHE["question"]),
        ("J'habite à Lyon depuis peu", AVEC_RECHERCHE["personnel"]),
        ("Je préfère le thé le matin", AVEC_RECHERCHE["personnel"]),
        ("il fait beau, mon chat dort", AVEC_RECHERCHE["personnel"]),
        ("Raconte une blague", AVEC_RECHERCHE["defaut"]),
        ("jeudi", AVEC_RECHERCHE["defaut"]),  # « je » n'est pas un mot ici
        ("merci pour le plan du potager", AVEC_RECHERCHE["defaut"]),
    ],
)
def test_avec_recherche(texte: str, raison: str) -> None:
    porte = decider(texte)
    assert porte.rappeler is True and porte.raison == raison


def test_description_generee_depuis_les_regles() -> None:
    for raison in (*SANS_RECHERCHE.values(), *AVEC_RECHERCHE.values()):
        assert raison in DESCRIPTION
