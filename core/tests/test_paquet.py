"""Paquet installable (pipx, uv tool) : point d'entrée, interface livrée ou page d'explication si absente."""

from __future__ import annotations

import io
import sys
import tomllib
from pathlib import Path

import httpx
import pytest

from jarvis2.__main__ import main
from jarvis2.api import creer_app
from jarvis2.config import Parametres

CORE = Path(__file__).resolve().parents[1]


def _client(monkeypatch: pytest.MonkeyPatch, dossier: Path) -> httpx.AsyncClient:
    monkeypatch.setattr(Parametres, "dossier_interface", property(lambda _self: dossier))
    app = creer_app(Parametres())
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765")


def test_point_entree_et_metadonnees() -> None:
    projet = tomllib.loads((CORE / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert projet["scripts"]["jarvis2"] == "jarvis2.__main__:main"
    assert projet["license"] == "Apache-2.0" and (CORE / projet["readme"]).is_file()
    assert projet["urls"]["Source"].startswith("https://github.com/")


def test_aide_sans_base(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as fin:
        main(["--help"])
    assert fin.value.code == 0 and "docteur" in capsys.readouterr().out


async def test_interface_absente_expliquee(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async with _client(monkeypatch, tmp_path / "<absente>") as client:
        rep = await client.get("/")
    assert rep.status_code == 503 and rep.headers["content-type"].startswith("text/html")
    assert "interface n'est pas installée" in rep.text and "jarvis2 docteur" in rep.text
    assert "&lt;absente&gt;" in rep.text  # chemin échappé
    assert "Content-Security-Policy" in rep.headers


async def test_interface_livree_servie(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<!doctype html><title>HUD</title>", encoding="utf-8")
    async with _client(monkeypatch, tmp_path) as client:
        rep = await client.get("/")
    assert rep.status_code == 200 and "HUD" in rep.text


def test_aide_sortie_cp1252(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows, sortie redirigée : page de code cp1252, sans ⇄ ni ✔. L'aide ne doit pas planter."""
    tampon = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(tampon, encoding="cp1252"))
    with pytest.raises(SystemExit) as fin:
        main(["--help"])
    sys.stdout.flush()
    assert fin.value.code == 0 and b"docteur" in tampon.getvalue()
