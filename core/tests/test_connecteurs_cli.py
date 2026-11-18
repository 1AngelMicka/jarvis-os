"""Connecteurs « compte par CLI » : Codex et Antigravity (flux JSONL enregistrés, fausse CLI, garde-fous)."""

from __future__ import annotations

import builtins
import io
import json
import os
import pathlib
import sys
from pathlib import Path
from typing import Any

import pytest

from jarvis2.moteurs.antigravity import CONSIGNE, AnalyseurAntigravity, MoteurAntigravity, lire_modeles
from jarvis2.moteurs.base import Delta, ErreurMoteur, Fin, Message
from jarvis2.moteurs.codex import AnalyseurCodex, MoteurCodex

DONNEES = Path(__file__).with_name("donnees")
FAUSSE = Path(__file__).with_name("fausse_cli.py")
MESSAGES = [Message("systeme", "Tu es JARVIS."), Message("utilisateur", "Bonjour")]


def evenements(nom: str) -> list[dict[str, Any]]:
    return [json.loads(ligne) for ligne in (DONNEES / nom).read_text(encoding="utf-8").splitlines() if ligne.strip()]


# --- Analyseurs sur des flux enregistrés ---------------------------------------------------------------


def test_analyseur_codex_flux_enregistre() -> None:
    a = AnalyseurCodex()
    morceaux = [m for ev in evenements("codex_exec.jsonl") if (m := a.lire(ev))]
    # Raisonnement et commandes ignorés ; le message arrive par mises à jour successives, puis un second message
    assert morceaux == ["Bonjour, ", "je suis là.", "\n\nAutre chose ?"]
    assert a.texte == "Bonjour, je suis là.\n\nAutre chose ?"
    assert a.usage.jetons_entree == 24763 and a.usage.jetons_sortie == 122
    assert a.fini and a.erreur is None


def test_analyseur_codex_erreurs() -> None:
    a = AnalyseurCodex()
    a.lire({"type": "turn.failed", "error": {"message": "usage limit reached"}})
    assert a.erreur == "usage limit reached"
    b = AnalyseurCodex()
    b.lire({"type": "error", "message": "stream disconnected"})
    assert b.erreur == "stream disconnected"


def test_analyseur_antigravity_flux_enregistre() -> None:
    a = AnalyseurAntigravity()
    morceaux = [m for ev in evenements("antigravity_stream.jsonl") if (m := a.lire(ev))]
    assert morceaux == ["Bonjour ", "Monsieur."] and a.texte == "Bonjour Monsieur."
    assert a.modele == "gemini-3.8-pro" and a.outils == 1  # l'appel d'outil n'est jamais pris pour une réponse
    assert a.usage.jetons_entree == 280 and a.usage.jetons_sortie == 20 and a.erreur is None
    b = AnalyseurAntigravity()
    b.lire({"type": "result", "status": "error", "error": {"message": "403 ToS"}})
    assert b.erreur == "403 ToS"


def test_modeles_antigravity() -> None:
    assert lire_modeles("Modèles disponibles :\n  gemini-3.8-pro   (défaut)\n  gemini-3.8-flash\n") == [
        "gemini-3.8-pro",
        "gemini-3.8-flash",
    ]


# --- Appel réel d'une CLI (fausse) : arguments, dossier vide, environnement, entrée standard ------------


@pytest.fixture
def env_cli(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "OPENAI_API_KEY": "cle-factice-openai",
            "GEMINI_API_KEY": "cle-factice-gemini",
            "DATABASE_URL": "postgresql://x",
            "FAUSSE_CLI_NOTE": str(tmp_path / "note.json"),
        }
    )
    return env


async def test_codex_appel_complet(tmp_path: Path, env_cli: dict[str, str]) -> None:
    env_cli["FAUSSE_CLI_FLUX"] = str(DONNEES / "codex_exec.jsonl")
    m = MoteurCodex(commande=[sys.executable, str(FAUSSE)], dossier_travail=tmp_path / "vide", env=env_cli)
    flux = [e async for e in m.stream(MESSAGES)]
    assert [e.texte for e in flux if isinstance(e, Delta)] == ["Bonjour, ", "je suis là.", "\n\nAutre chose ?"]
    fin = flux[-1]
    assert isinstance(fin, Fin) and fin.reponse.cout_usd == 0.0 and fin.reponse.meta["source_auth"] == "compte"
    note = json.loads((tmp_path / "note.json").read_text(encoding="utf-8"))
    assert note["args"] == ["exec", "--json", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral", "-"]
    assert note["contenu_cwd"] == [] and note["sensibles"] == []  # dossier vide, aucune clé transmise
    assert "Nouveau message de l'utilisateur :\nBonjour" in note["entree"]  # prompt sur l'entrée standard
    assert not Path(note["cwd"]).exists()  # dossier temporaire effacé après l'appel
    assert m.arguments("gpt-x")[-3:] == ["-m", "gpt-x", "-"]


async def test_antigravity_appel_complet(tmp_path: Path, env_cli: dict[str, str]) -> None:
    env_cli["FAUSSE_CLI_FLUX"] = str(DONNEES / "antigravity_stream.jsonl")
    m = MoteurAntigravity(commande=[sys.executable, str(FAUSSE)], dossier_travail=tmp_path / "vide", env=env_cli)
    reponse = await m.generate(MESSAGES, None)
    assert reponse.texte == "Bonjour Monsieur." and reponse.meta["outils_refuses"] == 1
    note = json.loads((tmp_path / "note.json").read_text(encoding="utf-8"))
    assert note["args"] == ["-p", CONSIGNE, "--output-format", "stream-json", "--sandbox"]
    assert "--dangerously-skip-permissions" not in m.arguments("x") and "--yolo" not in m.arguments("x")
    assert note["contenu_cwd"] == [] and note["sensibles"] == []
    assert [x.id for x in await m.list_models()] == ["gemini-3.8-pro", "gemini-3.8-flash"]


async def test_etat_connexion_codex(env_cli: dict[str, str]) -> None:
    connecte = MoteurCodex(commande=[sys.executable, str(FAUSSE)], env=env_cli)
    assert (await connecte.health()).connecte is True
    env_cli["FAUSSE_CLI_DECONNECTE"] = "1"
    deconnecte = MoteurCodex(commande=[sys.executable, str(FAUSSE)], env=env_cli)
    sante = await deconnecte.health()
    assert sante.installe and sante.connecte is False and "codex login" in sante.detail


async def test_cli_non_installees(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda nom: None)
    for moteur in (MoteurCodex(), MoteurAntigravity()):
        sante = await moteur.health()
        assert sante.installe is False and sante.detail == "non installé"
        assert moteur.installation_url and moteur.installation_url.startswith("https://")
        with pytest.raises(ErreurMoteur, match="pas installé"):
            await moteur.generate(MESSAGES)


async def test_identifiants_des_cli_jamais_ouverts(
    tmp_path: Path, env_cli: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le processus JARVIS n'ouvre aucun fichier d'identifiants (~/.codex, ~/.gemini, Antigravity)."""
    ouverts: list[str] = []
    vrai_open, vrai_path_open = builtins.open, pathlib.Path.open

    def espion(fichier: Any, *a: Any, **k: Any) -> Any:
        ouverts.append(str(fichier))
        return vrai_open(fichier, *a, **k)

    def espion_path(self: Path, *a: Any, **k: Any) -> Any:
        ouverts.append(str(self))
        return vrai_path_open(self, *a, **k)

    monkeypatch.setattr(builtins, "open", espion)
    monkeypatch.setattr(io, "open", espion)
    monkeypatch.setattr(pathlib.Path, "open", espion_path)
    for flux, classe in (("codex_exec.jsonl", MoteurCodex), ("antigravity_stream.jsonl", MoteurAntigravity)):
        env_cli["FAUSSE_CLI_FLUX"] = str(DONNEES / flux)
        m = classe(commande=[sys.executable, str(FAUSSE)], dossier_travail=tmp_path / "vide", env=env_cli)
        await m.health()
        await m.list_models()
        await m.generate(MESSAGES)
    interdits = [f for f in ouverts if any(x in f.lower() for x in (".codex", ".gemini", "antigravity", "auth.json"))]
    assert interdits == []
