"""Mode serveur sans écran : le Core refuse lui-même tout ce qui touche l'écran, le docteur l'indique."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from jarvis2 import __main__ as principal
from jarvis2 import diagnostic, ecran
from jarvis2.config import Parametres

from .test_medias import PNG, client


@pytest.mark.base
async def test_capture_refusee_par_le_core(pool: Any, tmp_path: Path) -> None:
    c, ctx = await client(pool, tmp_path)
    assert (await c.get("/v1/etat")).json()["sans_ecran"] is False
    ctx.sans_ecran = True
    rep = await c.post("/v1/vision/decrire", json={"image": PNG})
    assert rep.status_code == ecran.CODE_SANS_ECRAN
    assert "mode sans écran" in rep.json()["detail"]
    assert (await c.get("/v1/etat")).json()["sans_ecran"] is True
    assert (await c.get("/v1/sante")).json()["sans_ecran"] is True
    # La voix reste disponible : l'enregistrement vient du micro du navigateur
    voix = await c.post("/v1/voix/transcrire", content=b"audio")
    assert voix.status_code == 200


def test_exiger_ecran() -> None:
    ecran.exiger_ecran(False)
    with pytest.raises(ecran.SansEcran):
        ecran.exiger_ecran(True)


def test_session_graphique(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert not ecran.session_graphique()
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert ecran.session_graphique()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("WAYLAND_DISPLAY")
    assert ecran.session_graphique()


def test_docteur_indique_le_mode() -> None:
    assert diagnostic.verifier_ecran(True).statut == "info"
    assert "sans écran" in diagnostic.verifier_ecran(True).detail
    assert diagnostic.verifier_ecran(False, graphique=True).statut == "ok"
    sans_bureau = diagnostic.verifier_ecran(False, graphique=False)
    assert sans_bureau.statut == "attention" and sans_bureau.aide and "--sans-ecran" in sans_bureau.aide


def test_option_de_lancement(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`jarvis2 serveur --sans-ecran --ouvrir` : mode transmis au Core, aucun navigateur ouvert sur le serveur."""
    p = Parametres(JARVIS2_DOSSIER_DONNEES=tmp_path, JARVIS2_STOCKAGE="sqlite")
    monkeypatch.setattr(principal, "parametres", lambda: p)

    async def migrer(*_: Any) -> list[str]:
        return []

    vu: dict[str, Any] = {}

    def lancer(app: Any, **_: Any) -> None:
        vu["p"] = app.state.parametres

    monkeypatch.setattr(principal, "migrer", migrer)
    monkeypatch.setattr("uvicorn.run", lancer)
    assert principal.main(["serveur", "--sans-ecran", "--ouvrir"]) == 0
    assert vu["p"].sans_ecran is True and vu["p"].ouvrir_navigateur is False
    assert principal.main(["serveur"]) == 0
    assert vu["p"].sans_ecran is False


def test_reglage_equivalent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS2_SANS_ECRAN", "true")
    assert Parametres().sans_ecran is True
