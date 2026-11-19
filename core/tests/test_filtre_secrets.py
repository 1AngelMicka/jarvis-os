"""Lot 14-C13 : masquage des secrets étendu (vrais positifs, faux positifs, journaux).

Toutes les valeurs sont factices et assemblées à l'exécution : aucun texte du dépôt ne ressemble à un vrai secret.
Les numéros de carte sont les numéros de test publiés par les réseaux (Visa, Mastercard…).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import pytest

from jarvis2.db import Base
from jarvis2.journal import FiltreSecrets
from jarvis2.journal import masquer as masquer_journal
from jarvis2.securite import audit
from jarvis2.securite.filtre import masquer, masquer_secrets, masquer_valeurs

A = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"  # 36 caractères alphanumériques quelconques

# (texte contenant le secret, valeur qui ne doit plus apparaître, étiquette attendue)
VRAIS_POSITIFS: list[tuple[str, str, str]] = [
    ("clé " + "sk-" + "ant-api03-" + A, "sk-" + "ant-api03-" + A, "SECRET : clé Anthropic"),
    ("clé " + "sk-" + A, "sk-" + A, "SECRET : clé OpenAI"),
    ("clé " + "sk-" + "proj-" + A + "_x-y", "sk-" + "proj-" + A, "SECRET : clé OpenAI"),
    ("stripe " + "sk_" + "live_" + A[:24], "sk_" + "live_" + A[:24], "SECRET : clé Stripe"),
    ("stripe " + "rk_" + "live_" + A[:24], "rk_" + "live_" + A[:24], "SECRET : clé Stripe"),
    ("stripe " + "pk_" + "test_" + A[:24], "pk_" + "test_" + A[:24], "SECRET : clé Stripe"),
    ("webhook " + "whsec_" + A, "whsec_" + A, "SECRET : clé Stripe"),
    ("jeton " + "ghp_" + A, "ghp_" + A, "SECRET : jeton GitHub"),
    ("jeton " + "gho_" + A, "gho_" + A, "SECRET : jeton GitHub"),
    ("jeton " + "github_" + "pat_" + A + "_" + A, "github_" + "pat_" + A, "SECRET : jeton GitHub"),
    ("google " + "AIza" + "Sy" + A[:33], "AIza" + "Sy" + A[:33], "SECRET : clé Google"),
    ("aws " + "AKIA" + "IOSFODNN7EXAMPLE", "AKIA" + "IOSFODNN7EXAMPLE", "SECRET : clé AWS"),
    (
        "aws_secret_access_key = " + "wJalrXUtnFEMI/K7MDENG/" + "bPxRfiCYEXAMPLEKEY",
        "wJalrXUtnFEMI/K7MDENG/" + "bPxRfiCYEXAMPLEKEY",
        "SECRET : clé AWS",
    ),
    (
        'AWS_SECRET_ACCESS_KEY="' + "wJalrXUtnFEMI/K7MDENG/" + 'bPxRfiCYEXAMPLEKEY"',
        "wJalrXUtnFEMI/K7MDENG/" + "bPxRfiCYEXAMPLEKEY",
        "SECRET : clé AWS",
    ),
    (
        "jwt " + "eyJ" + "hbGciOiJIUzI1NiJ9." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0." + "dozjgNryP4J3jVmNHl0w5N",
        "dozjgNryP4J3jVmNHl0w5N",
        "SECRET : jeton JWT",
    ),
    ("Authorization: " + "Bearer " + "abc123def456ghi789jkl", "abc123def456ghi789jkl", "SECRET : jeton"),
    ("authorization: " + "bearer " + "Zm9vYmFyYmF6cXV4cXV1eA==", "Zm9vYmFyYmF6cXV4cXV1eA==", "SECRET : jeton"),
    ("Votre code : 123456", "123456", "CODE À USAGE UNIQUE"),
    ("code de vérification: 842 913", "842 913", "CODE À USAGE UNIQUE"),
    ("Code à usage unique = 90817", "90817", "CODE À USAGE UNIQUE"),
    ("Your verification code is 551234", "551234", "CODE À USAGE UNIQUE"),
    ("OTP: 7788", "7788", "CODE À USAGE UNIQUE"),
    ("483920 est votre code de connexion", "483920", "CODE À USAGE UNIQUE"),
    ("https://" + "alice:" + "s3cr3tPass" + "@exemple.org/depot", "s3cr3tPass", "SECRET : identifiants"),
    ("redis://" + "user:" + "pa55word" + "@127.0.0.1:6379", "pa55word", "SECRET : identifiants"),
    ("pass" + "word=" + "hunter2hunter2", "hunter2hunter2", "SECRET : mot de passe"),
    ("mot de passe : " + "Tr0ub4dor&3", "Tr0ub4dor&3", "SECRET : mot de passe"),
    ("carte 4111 " + "1111 1111 1111", "4111 1111 1111 1111", "CARTE BANCAIRE"),
    ("carte 4111-" + "1111-1111-1111", "4111-1111-1111-1111", "CARTE BANCAIRE"),
    ("carte 5555" + "555555554444", "5555555555554444", "CARTE BANCAIRE"),
    ("amex 3782 " + "822463 10005", "3782 822463 10005", "CARTE BANCAIRE"),
    ("discover 6011" + "111111111117", "6011111111111117", "CARTE BANCAIRE"),
    ("jcb 3530" + "111333300000", "3530111333300000", "CARTE BANCAIRE"),
    ("carte 4970 " + "1012 3456 7893", "4970 1012 3456 7893", "CARTE BANCAIRE"),
]


@pytest.mark.parametrize(("texte", "valeur", "etiquette"), VRAIS_POSITIFS)
def test_vrais_positifs(texte: str, valeur: str, etiquette: str) -> None:
    r = masquer(texte)
    assert valeur not in r.texte, r.texte
    assert r.masques[etiquette] >= 1, r.masques
    assert f"[{etiquette}]" in r.texte


FAUX_POSITIFS = [
    "Le 12/03/2026, 1 500 € ; commande 1234 5678 9012 3456 ; IBAN FR00 1234 5678 9012",
    "commit " + "3f786850e387550fdab836ed7e6dc881de23001b",  # SHA-1
    "empreinte " + "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",  # SHA-256
    "identifiant " + str(uuid.UUID("12345678-1234-5678-1234-567812345678")),
    "uuid 01234567-0612-3456-7890-123456789012",  # chiffres seuls, ressemble à un téléphone ou une carte
    "rev " + "0612345678abcdef0123456789abcdef01234567",  # SHA-1 qui commence comme un numéro de mobile
    "code postal : 75001",
    "erreur code 404, puis HTTP 500",
    "le code est simple à lire",
    "numéro de commande 1234567812345670",  # passe Luhn, mais aucun émetteur ne commence par 1
    "suivi colis 9876543210987654321",
    "horodatage 1700000000000 ms",
    "ISBN 978-2-07-036822-8",
    "0000 0000 0000 0000",  # passe Luhn, pas une carte
    "la tâche sk-1 et le ticket pk-42",
    "skip-this-not-a-key, risk-free",
    "ma clé est rangée dans le tiroir",
    "bearer de mauvaises nouvelles",
    "token: court",
    "https://exemple.org/chemin?x=1 et user@exemple",
    "version 1.2.3, port 8765, 2026-11-19T10:00:00Z",
    "AKIA tout seul et AIza trop court",
]


@pytest.mark.parametrize("texte", FAUX_POSITIFS)
def test_faux_positifs(texte: str) -> None:
    r = masquer(texte)
    assert r.texte == texte, r.texte
    assert not r.masques


def test_empreinte_git_masquee_si_contexte_de_secret() -> None:
    hexa = "3f786850e387550fdab836ed7e6dc881de23001b"
    assert hexa not in masquer("token: " + hexa).texte
    assert hexa in masquer("commit " + hexa).texte


def test_compteurs_par_type_et_libelles_lisibles() -> None:
    texte = " ; ".join(t for t, _, _ in VRAIS_POSITIFS)
    r = masquer(texte)
    for _, valeur, _ in VRAIS_POSITIFS:
        assert valeur not in r.texte
    assert r.masques["CARTE BANCAIRE"] == 7
    assert r.masques["CODE À USAGE UNIQUE"] == 6
    assert r.masques["SECRET : jeton GitHub"] == 3
    for etiquette in r.masques:
        assert etiquette == etiquette.strip() and "_" not in etiquette


def test_valeur_seule_remplacee_le_contexte_reste_lisible() -> None:
    assert masquer("Votre code : 123456").texte == "Votre code : [CODE À USAGE UNIQUE]"
    assert masquer("Authorization: Bearer abcdefghijklmnop1234").texte == "Authorization: Bearer [SECRET : jeton]"
    url = "https://" + "alice:" + "s3cr3t" + "@exemple.org/x"
    assert masquer(url).texte == "https://[SECRET : identifiants]@exemple.org/x"


def test_secrets_seuls_pour_les_journaux_locaux() -> None:
    texte = "écrire à jean.dupont" + "@" + "exemple.fr, 06 12 34 56 78, clé " + "sk-" + A
    propre = masquer_secrets(texte)
    assert "sk-" + A not in propre and "[SECRET : clé OpenAI]" in propre
    assert "jean.dupont@exemple.fr" in propre and "06 12 34 56 78" in propre


def test_masquer_valeurs_parcourt_la_structure() -> None:
    entree: dict[str, Any] = {"a": "clé " + "ghp_" + A, "b": [1, "code : 654321", {"c": None}], "d": 3}
    sortie = masquer_valeurs(entree)
    assert sortie == {
        "a": "clé [SECRET : jeton GitHub]",
        "b": [1, "code : [CODE À USAGE UNIQUE]", {"c": None}],
        "d": 3,
    }


def test_journal_applicatif_masque_les_nouveaux_secrets() -> None:
    assert "ghp_" + A not in masquer_journal("jeton ghp_" + A)
    assert masquer_journal("postgresql://jarvis2_app:motdepasse@127.0.0.1:5433/jarvis2") == (
        "postgresql://jarvis2_app:***@127.0.0.1:5433/jarvis2"
    )
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "carte %s", ("4111 1111 1111 1111",), None)
    FiltreSecrets().filter(record)
    assert record.getMessage() == "carte [CARTE BANCAIRE]"


async def test_journal_d_audit_sans_secret(pool: Base) -> None:
    secret = "sk-" + "ant-api03-" + A
    await audit.journaliser(
        pool,
        acteur="test",
        action="outil.appel",
        cible="https://" + "bob:" + "m0tdepasse" + "@exemple.org",
        details={"commande": f"curl -H 'Authorization: Bearer {A}'", "args": [secret], "n": 2},
    )
    lignes = await audit.lister(pool, 5)
    brut = repr(lignes)
    assert secret not in brut and A not in brut and "m0tdepasse" not in brut
    assert "[SECRET : clé Anthropic]" in brut
    assert await audit.verifier(pool) is None  # la chaîne reste valide : on hache le texte déjà masqué
