"""Phase 12 : sauvegarde chiffrée, restauration vérifiée (lignes, chaîne d'audit), rotation."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from jarvis2.conversations import DepotConversations
from jarvis2.db_sqlite import BaseSQLite, appliquer_migrations
from jarvis2.sauvegarde import ErreurSauvegarde, chiffrer, creer, dechiffrer, ouvrir, rotation, verifier_sqlite
from jarvis2.securite import audit

PHRASE = "une phrase de passe assez longue"


async def _remplir(chemin: Path) -> None:
    await appliquer_migrations(chemin)
    base = await BaseSQLite.ouvrir(chemin)
    try:
        depot = DepotConversations(base)
        conv = await depot.creer("Sauvegarde")
        await depot.ajouter_message(conv.id, "utilisateur", "Bonjour")
        await audit.journaliser(base, acteur="test", action="sauvegarde.essai")
    finally:
        await base.close()


def test_chiffrement() -> None:
    contenu = chiffrer(b"secret", PHRASE)
    assert b"secret" not in contenu and dechiffrer(contenu, PHRASE) == b"secret"
    with pytest.raises(ErreurSauvegarde, match="incorrecte"):
        dechiffrer(contenu, "une autre phrase de passe")
    altere = contenu[:-1] + bytes([contenu[-1] ^ 1])
    with pytest.raises(ErreurSauvegarde, match="altérée"):
        dechiffrer(altere, PHRASE)
    with pytest.raises(ErreurSauvegarde, match="courte"):
        chiffrer(b"x", "court")


def test_sauvegarde_puis_restauration_verifiee(tmp_path: Path) -> None:
    base = tmp_path / "donnees" / "jarvis2.db"
    base.parent.mkdir()
    asyncio.run(_remplir(base))
    config = tmp_path / "config"
    (config / "recettes").mkdir(parents=True)
    (config / "config.toml").write_text("[confidentialite]\n", encoding="utf-8")
    (config / "recettes" / "matin.yaml").write_text("nom: x\n", encoding="utf-8")
    hors_site = tmp_path / "disque-externe"
    fichier = creer(hors_site, PHRASE, "sqlite", base, config)
    assert fichier.suffix == ".jarvis2" and b"Bonjour" not in fichier.read_bytes()  # chiffrée
    manifeste, archive = ouvrir(fichier, PHRASE)
    assert manifeste.comptes["messages"] == 1 and manifeste.comptes["conversations"] == 1 and manifeste.audit_dernier
    assert {"base/jarvis2.db", "config/config.toml", "config/recettes/matin.yaml", "manifeste.json"} <= set(
        archive.getnames()
    )
    rapport = verifier_sqlite(fichier, PHRASE)
    assert rapport["valide"] and rapport["audit_intact"] and not rapport["ecarts"]


def test_rotation(tmp_path: Path) -> None:
    for i in range(10):
        (tmp_path / f"jarvis2-20261118-00000{i}.jarvis2").write_bytes(b"x")
    retirees = rotation(tmp_path, garder=7)
    assert len(retirees) == 3 and len(list(tmp_path.glob("*.jarvis2"))) == 7
    assert not (tmp_path / "jarvis2-20261118-000000.jarvis2").exists()
