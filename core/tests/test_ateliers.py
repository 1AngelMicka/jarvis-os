"""Phase 9 : ateliers Claude Code (worktrees parallèles, écriture hors du worktree refusée, fusion approuvée)."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis2.api import Contexte, creer_app
from jarvis2.ateliers import mcp_autorisation
from jarvis2.ateliers.autorisation import decider
from jarvis2.ateliers.gestionnaire import GestionnaireAteliers, Projet, git
from jarvis2.config import Parametres
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import ServiceDialogue
from jarvis2.securite import appareils
from jarvis2.securite.actions import creer_registre
from jarvis2.securite.permissions import Approbations
from jarvis2.securite.urgence import ArretUrgence

pytestmark = pytest.mark.base
FAUX = [sys.executable, str(Path(__file__).with_name("faux_claude_atelier.py"))]


def depot_git(dossier: Path) -> Path:
    dossier.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    for args in (["init", "-q", "-b", "main"], ["config", "core.autocrlf", "false"]):
        subprocess.run(["git", *args], cwd=dossier, check=True)
    (dossier / "README.md").write_text("projet\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=dossier, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "départ"], cwd=dossier, check=True, env={**__import__("os").environ, **env}
    )
    return dossier


@pytest.fixture
async def ateliers(pool: Base, tmp_path: Path) -> GestionnaireAteliers:
    projet = depot_git(tmp_path / "projet")
    return GestionnaireAteliers(
        pool, [Projet("essai", "Essai", projet)], tmp_path / "ateliers", "http://127.0.0.1:1", ArretUrgence(), FAUX
    )


async def attendre_fin(g: GestionnaireAteliers, *idents: Any) -> None:
    for _ in range(200):
        if not any(i in g.taches for i in idents):
            return
        await asyncio.sleep(0.05)
    raise AssertionError("atelier toujours en cours")


def test_decisions_d_autorisation(tmp_path: Path) -> None:
    racine = tmp_path / "wt"
    racine.mkdir()
    assert decider(racine, "Write", {"file_path": "src/a.py"}).verdict == "autoriser"
    assert decider(racine, "Edit", {"file_path": str(racine / "b.py")}).verdict == "autoriser"
    for dehors in (
        "../voisin/a.py",
        str(tmp_path / "autre.txt"),
        str(Path(racine.anchor) / "Windows" / "x.dll"),
        "sous/../../evasion.txt",
    ):
        d = decider(racine, "Write", {"file_path": dehors})
        assert d.verdict == "refuser" and "hors de l'atelier" in d.raison
    assert decider(racine, "Write", {"file_path": ".git/config"}).verdict == "refuser"
    assert decider(racine, "Write", {"file_path": ".env"}).verdict == "refuser"
    assert decider(racine, "Read", {"file_path": "a.py"}).verdict == "autoriser"
    assert decider(racine, "Read", {"file_path": "../secret.txt"}).verdict == "demander"
    assert decider(racine, "Bash", {"command": "rm -rf /"}).verdict == "demander"
    assert decider(racine, "TodoWrite", {"todos": []}).reponse({"todos": []})["behavior"] == "allow"


async def test_deux_ateliers_en_parallele_chacun_son_worktree(ateliers: GestionnaireAteliers, pool: Base) -> None:
    a = await ateliers.creer("essai", "Ajouter A", "appareil:pc")
    b = await ateliers.creer("essai", "Ajouter B", "appareil:pc")
    assert a["chemin"] != b["chemin"] and a["branche"] != b["branche"]
    await ateliers.lancer(a["id"], "consigne A")
    await ateliers.lancer(b["id"], "consigne B")  # en même temps
    await attendre_fin(ateliers, a["id"], b["id"])
    fichiers_a = {p.name for p in Path(a["chemin"]).glob("travail-*.txt")}
    fichiers_b = {p.name for p in Path(b["chemin"]).glob("travail-*.txt")}
    assert len(fichiers_a) == 1 and len(fichiers_b) == 1 and fichiers_a.isdisjoint(fichiers_b)
    projet = ateliers.projets["essai"].chemin
    assert not list(projet.glob("travail-*.txt"))  # le projet n'est pas touché avant la fusion
    atelier = await ateliers.obtenir(a["id"])
    assert atelier is not None and atelier["statut"] == "pret" and atelier["session"] == "session-1"
    types = [e["type"] for e in await ateliers.evenements(a["id"])]
    assert types[:3] == ["cree", "consigne", "session"] and "fin" in types

    # La fusion passe par une approbation (🟡), puis chaque branche arrive dans le projet
    approbations = Approbations(pool, creer_registre(ArretUrgence(), None, ateliers))
    appareil, _ = await appareils.creer(pool, "PC", "pc")
    for atelier_id in (a["id"], b["id"]):
        demande = await approbations.demander("atelier.fusionner", {"atelier_id": str(atelier_id)}, appareil)
        assert demande["statut"] == "en_attente" and demande["demande"]["niveau"] == "jaune"
        assert not list(projet.glob(f"{next(iter(fichiers_a if atelier_id == a['id'] else fichiers_b))}"))
        fait = await approbations.decider(demande["demande"]["id"], appareil, True, "clic")
        assert fait["statut"] == "executee", fait
    assert {p.name for p in projet.glob("travail-*.txt")} == fichiers_a | fichiers_b
    _, log = await git(projet, "log", "--oneline")
    assert "Atelier JARVIS : Ajouter A" in log and "Atelier JARVIS : Ajouter B" in log
    assert (await ateliers.obtenir(a["id"]))["statut"] == "fusionne"  # type: ignore[index]


async def test_autorisations_en_direct_et_ecriture_hors_worktree_refusee(ateliers: GestionnaireAteliers) -> None:
    a = await ateliers.creer("essai", "Essai", "appareil:pc")
    ateliers.jetons["jeton-essai"] = a["id"]
    dedans = await ateliers.autoriser("jeton-essai", "Write", {"file_path": "ok.txt", "content": "x"})
    assert dedans["behavior"] == "allow"
    dehors = await ateliers.autoriser("jeton-essai", "Write", {"file_path": "../../evasion.txt", "content": "x"})
    assert dehors["behavior"] == "deny" and "hors de l'atelier" in dehors["message"]
    assert (await ateliers.autoriser("jeton-inconnu", "Write", {"file_path": "ok.txt"}))["behavior"] == "deny"
    # Commande : l'utilisateur décide en direct
    tache = asyncio.create_task(ateliers.autoriser("jeton-essai", "Bash", {"command": "pytest"}))
    for _ in range(50):
        if ateliers.en_attente(a["id"]):
            break
        await asyncio.sleep(0.02)
    (attente,) = ateliers.en_attente(a["id"])
    assert attente["outil"] == "Bash" and "pytest" in attente["raison"]
    assert ateliers.repondre(attente["id"], True)
    assert (await tache)["behavior"] == "allow"


async def test_route_d_autorisation_et_serveur_mcp(
    ateliers: GestionnaireAteliers, pool: Base, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = await ateliers.creer("essai", "Essai", "appareil:pc")
    ateliers.jetons["jeton-route"] = a["id"]
    depot = DepotConversations(pool)
    ctx = Contexte(pool, depot, {}, ServiceDialogue(depot, {}, "x"), "x", ateliers=ateliers)
    app = creer_app(Parametres(), ctx)
    app.state.ctx = ctx
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8765") as client:
        corps = {
            "tool_name": "Write",
            "input": {"file_path": str(Path(ateliers.dossier.anchor) / "hors" / "atelier.txt")},
        }
        rep = await client.post("/v1/ateliers-autorisation", json=corps, headers={"X-Atelier-Jeton": "jeton-route"})
        assert rep.status_code == 200 and rep.json()["behavior"] == "deny"
        sans_jeton = await client.post("/v1/ateliers-autorisation", json=corps)
        assert sans_jeton.json()["behavior"] == "deny"
    # Le serveur MCP lancé par Claude Code relaie la question au Core et renvoie sa décision en texte JSON
    monkeypatch.setenv("JARVIS2_ATELIER_URL", "http://core/v1/ateliers-autorisation")
    monkeypatch.setenv("JARVIS2_ATELIER_JETON", "j")
    vu: dict[str, Any] = {}

    def repondre(requete: httpx.Request) -> httpx.Response:
        vu["jeton"] = requete.headers["x-atelier-jeton"]
        return httpx.Response(200, json={"behavior": "deny", "message": "non"})

    client_sync = httpx.Client(transport=httpx.MockTransport(repondre))
    monkeypatch.setattr("jarvis2.ateliers.mcp_autorisation.httpx.Client", lambda **_: client_sync)
    reponse = mcp_autorisation.traiter(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "autoriser", "arguments": {"tool_name": "Bash", "input": {}}},
        }
    )
    assert reponse is not None and '"deny"' in reponse["result"]["content"][0]["text"] and vu["jeton"] == "j"


async def test_arret_puis_reprise(ateliers: GestionnaireAteliers, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAUX_ATELIER", "lent")
    a = await ateliers.creer("essai", "Long", "appareil:pc")
    await ateliers.lancer(a["id"], "travail long")
    for _ in range(100):
        atelier = await ateliers.obtenir(a["id"])
        if atelier and atelier["session"]:
            break
        await asyncio.sleep(0.05)
    assert await ateliers.arreter(a["id"])
    assert (await ateliers.obtenir(a["id"]))["statut"] == "arrete"  # type: ignore[index]
    monkeypatch.delenv("FAUX_ATELIER")
    await ateliers.lancer(a["id"], "continue", reprendre=True)
    await attendre_fin(ateliers, a["id"])
    atelier = await ateliers.obtenir(a["id"])
    assert atelier is not None and atelier["session"] == "session-reprise" and atelier["statut"] == "pret"
