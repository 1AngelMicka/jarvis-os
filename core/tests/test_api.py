"""API : amorçage, dialogue en SSE, historique stocké, télémétrie, origine."""

from __future__ import annotations

import json
from typing import Any

import asyncpg
import httpx
import pytest

from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.conversations import DepotConversations
from jarvis2.dialogue import ServiceDialogue
from jarvis2.moteurs.telemetrie import EnregistreurPostgres, MoteurInstrumente
from jarvis2.securite import appareils

from .test_registre_telemetrie import FauxMoteur

pytestmark = pytest.mark.base


def lire_sse(corps: str) -> list[tuple[str, dict[str, Any]]]:
    evenements = []
    for bloc in corps.strip().split("\n\n"):
        lignes = dict(ligne.split(": ", 1) for ligne in bloc.splitlines())
        evenements.append((lignes["event"], json.loads(lignes["data"])))
    return evenements


@pytest.fixture
async def client(pool: asyncpg.Pool) -> httpx.AsyncClient:
    depot = DepotConversations(pool)
    moteurs = {
        "faux": MoteurInstrumente(FauxMoteur(), EnregistreurPostgres(pool)),
        "panne": MoteurInstrumente(FauxMoteur(echec=True), EnregistreurPostgres(pool)),
    }
    ctx = Contexte(pool, depot, moteurs, ServiceDialogue(depot, moteurs, "faux"), "faux")
    app = creer_app(Parametres(), ctx)
    app.state.ctx = ctx
    _, jeton = await appareils.creer(pool, "PC de test", "pc")
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:8765",
        headers={"Authorization": f"Bearer {jeton}"},
    )


async def test_dialogue_complet(client: httpx.AsyncClient, pool: asyncpg.Pool) -> None:
    rep = await client.post("/v1/dialogue", json={"message": "Bonjour JARVIS"})
    assert rep.status_code == 200 and rep.headers["content-type"].startswith("text/event-stream")
    evenements = lire_sse(rep.text)
    assert [e for e, _ in evenements] == ["debut", "delta", "fin"]
    debut, fin = evenements[0][1], evenements[-1][1]
    assert debut["titre"] == "Bonjour JARVIS" and debut["moteur"] == "faux"
    assert fin["texte"] == "a" and fin["cout_usd"] == 0.0 and fin["source_auth"] == "none"

    conv = (await client.get(f"/v1/conversations/{debut['conversation_id']}")).json()
    assert [(m["role"], m["contenu"]) for m in conv["messages"]] == [("utilisateur", "Bonjour JARVIS"), ("jarvis", "a")]
    # Suite de la même conversation
    rep2 = await client.post(
        "/v1/dialogue", json={"message": "Et ensuite ?", "conversation_id": debut["conversation_id"]}
    )
    assert lire_sse(rep2.text)[-1][0] == "fin"
    assert (await client.get(f"/v1/conversations/{debut['conversation_id']}")).json()["conversation"][
        "nb_messages"
    ] == 4
    assert await pool.fetchval("SELECT count(*) FROM telemetrie WHERE statut = 'ok'") == 2


async def test_dialogue_erreur_moteur(client: httpx.AsyncClient, pool: asyncpg.Pool) -> None:
    rep = await client.post("/v1/dialogue", json={"message": "x", "moteur": "panne"})
    evenements = lire_sse(rep.text)
    assert evenements[-1] == ("erreur", {"message": "panne", "conversation_id": evenements[0][1]["conversation_id"]})
    assert await pool.fetchval("SELECT statut FROM telemetrie") == "erreur"
    # La réponse partielle est conservée, marquée interrompue
    meta = await pool.fetchval("SELECT meta FROM messages WHERE role = 'jarvis'")
    assert meta["interrompu"] is True


async def test_etat_en_un_appel(client: httpx.AsyncClient) -> None:
    await client.post("/v1/dialogue", json={"message": "premier"})
    etat = (await client.get("/v1/etat")).json()
    assert etat["moteur_defaut"] == "faux"
    assert {m["id"] for m in etat["moteurs"]} == {"faux"}  # deux instances du même faux moteur
    assert etat["moteurs"][0]["modeles"] == [{"id": "faux-1", "nom": "Faux 1", "defaut": True}]
    assert [c["titre"] for c in etat["conversations"]] == ["premier"]


async def test_validations(client: httpx.AsyncClient) -> None:
    assert (await client.post("/v1/dialogue", json={"message": ""})).status_code == 422
    assert (await client.post("/v1/dialogue", json={"message": "x", "moteur": "inconnu"})).status_code == 422
    inconnue = "00000000-0000-0000-0000-000000000000"
    assert (await client.post("/v1/dialogue", json={"message": "x", "conversation_id": inconnue})).status_code == 404
    assert (await client.get(f"/v1/conversations/{inconnue}")).status_code == 404


async def test_entetes_de_securite_hors_api(client: httpx.AsyncClient) -> None:
    rep = await client.get("/page-inexistante")
    assert "script-src 'self'" in rep.headers["content-security-policy"]
    assert rep.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in (await client.get("/v1/sante")).headers


async def test_origine_inconnue_refusee(client: httpx.AsyncClient) -> None:
    rep = await client.post("/v1/dialogue", json={"message": "x"}, headers={"Origin": "https://malveillant.example"})
    assert rep.status_code == 403
    ok = await client.get("/v1/sante", headers={"Origin": "http://127.0.0.1:5174"})
    assert ok.status_code == 200 and ok.json()["base"] is True and ok.json()["schema"] == "004_securite"
