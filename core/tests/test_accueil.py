"""Premier lancement : accueil de Claude Code (case cochée), diagnostic, réparations sûres, état de l'assistant."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis2 import diagnostic
from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.connecteurs import CONDITIONS, Connecteurs, Definition
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base, lister_migrations
from jarvis2.dialogue import ServiceDialogue
from jarvis2.moteurs.telemetrie import EnregistreurBase, MoteurInstrumente
from jarvis2.securite import appareils
from jarvis2.securite.coffre import Coffre
from jarvis2.tailscale import EtatTailscale

from .test_connecteurs import Faux

pytestmark = pytest.mark.base


@pytest.fixture
async def systeme(pool: Base, tmp_path: Path) -> dict[str, Any]:
    moteurs = {"claude_code": Faux("claude_code", "cli"), "local": Faux("local", "local", externe=False)}
    coffre = Coffre(tmp_path / "coffre.json")
    defs = {i: Definition(MoteurInstrumente(m, EnregistreurBase(pool))) for i, m in moteurs.items()}
    connecteurs = Connecteurs(pool, defs, coffre)
    await connecteurs.charger()
    depot = DepotConversations(pool)
    service = ServiceDialogue(depot, connecteurs.moteurs, "claude_code", None, connecteurs)
    ctx = Contexte(pool, depot, connecteurs.moteurs, service, "claude_code", connecteurs=connecteurs)
    p = Parametres().model_copy(
        update={"stockage": pool.dialecte, "sqlite": tmp_path / "jarvis2.db", "dossier_donnees": tmp_path}
    )
    app = creer_app(p, ctx)
    app.state.ctx = ctx
    _, jeton = await appareils.creer(pool, "PC", "pc")
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost:8765",
        headers={"Authorization": f"Bearer {jeton}"},
    )
    return {"client": client, "connecteurs": connecteurs, "ctx": ctx, "p": p}


async def test_claude_code_attend_la_case_cochee(systeme: dict[str, Any]) -> None:
    client, c = systeme["client"], systeme["connecteurs"]
    carte = next(x for x in (await client.get("/v1/connecteurs")).json()["connecteurs"] if x["id"] == "claude_code")
    assert not carte["actif"] and not carte["conditions_acceptees"] and not carte["risque"]
    assert "usage personnel" in carte["conditions"]["texte"] and "clé d'API Anthropic" in carte["conditions"]["texte"]
    assert carte["conditions"]["url"].startswith("https://www.anthropic.com/")
    assert await c.router() == "local"  # tant que l'avertissement n'est pas accepté
    assert (await client.post("/v1/connecteurs/claude_code/activer", json={})).status_code == 422
    version = CONDITIONS["claude_code"]["version"]
    rep = await client.post("/v1/connecteurs/claude_code/activer", json={"accepte": True, "version": version})
    assert rep.status_code == 200 and c.actif("claude_code") and not c.conditions_a_accepter("claude_code")
    assert await c.router() == "claude_code"  # un compte passe avant le local, et n'est pas « à risque »


async def test_assistant_d_accueil(systeme: dict[str, Any]) -> None:
    client = systeme["client"]
    etat = (await client.get("/v1/accueil")).json()
    assert etat["termine"] is False and etat["tailscale"] is None
    assert (await client.post("/v1/accueil/terminer")).json() == {"termine": True}
    assert (await client.get("/v1/accueil")).json()["termine"] is True


async def test_diagnostic_et_reparations(systeme: dict[str, Any], pool: Base) -> None:
    client = systeme["client"]
    verifs = {v["id"]: v for v in (await client.get("/v1/diagnostic")).json()["verifications"]}
    assert {"python", "donnees", "stockage", "interface", "modele", "cerveau", "reseau", "telephone", "audit"} <= set(
        verifs
    )
    assert verifs["stockage"]["statut"] == "ok"
    assert lister_migrations(pool.dialecte)[-1][0] in verifs["stockage"]["detail"]
    assert verifs["claude_code"]["statut"] == "attention"  # avertissement à accepter
    assert verifs["audit"]["statut"] == "ok"
    assert (await client.post("/v1/diagnostic/reparer/effacer_tout")).status_code == 404
    rep = await client.post("/v1/diagnostic/reparer/migrer")
    assert rep.status_code == (200 if pool.dialecte == "sqlite" else 409)  # PostgreSQL : rôle propriétaire


async def test_telechargements_sur_accord_seulement(systeme: dict[str, Any]) -> None:
    client = systeme["client"]
    etats = {e["id"]: e for e in (await client.get("/v1/telechargements")).json()["telechargements"]}
    assert set(etats) == {"embeddings", "voix", "proprietaire"} and all(e["statut"] == "absent" for e in etats.values())
    assert (await client.post("/v1/telechargements/inconnu")).status_code == 404
    verifs = {v["id"]: v for v in (await client.get("/v1/diagnostic")).json()["verifications"]}
    assert verifs["voix"]["reparation"] == "telecharger_voix"  # proposé, jamais lancé seul


def test_telephone_selon_tailscale() -> None:
    assert diagnostic.verifier_telephone(None, 8765).statut == "info"
    assert diagnostic.verifier_telephone(EtatTailscale(installe=True), 8765).aide == "tailscale up"
    connecte = EtatTailscale(installe=True, connecte=True, nom="pc.reseau.ts.net")
    v = diagnostic.verifier_telephone(connecte, 8765)
    assert v.statut == "attention" and v.aide == "tailscale serve --bg 8765"
    publie = EtatTailscale(installe=True, connecte=True, nom="pc.reseau.ts.net", serve_actif=True)
    assert diagnostic.verifier_telephone(publie, 8765).detail.endswith("https://pc.reseau.ts.net")


async def test_jumelage_par_tailscale(systeme: dict[str, Any]) -> None:
    client, ctx = systeme["client"], systeme["ctx"]
    assert "http://localhost:8765/#jumeler=" in (await client.post("/v1/jumelage", json={})).json()["url"]
    ctx.tailscale = EtatTailscale(installe=True, connecte=True, nom="pc.reseau.ts.net", serve_actif=True)
    rep = (await client.post("/v1/jumelage", json={"type": "telephone"})).json()
    assert rep["url"].startswith("https://pc.reseau.ts.net/#jumeler=") and rep["tailscale"] is True
