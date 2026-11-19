"""API : amorçage, dialogue en SSE, historique stocké, télémétrie, origine."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base, lister_migrations
from jarvis2.dialogue import ServiceDialogue
from jarvis2.moteurs.telemetrie import EnregistreurBase, MoteurInstrumente
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
async def client(pool: Base) -> httpx.AsyncClient:
    depot = DepotConversations(pool)
    moteurs = {
        "faux": MoteurInstrumente(FauxMoteur(), EnregistreurBase(pool)),
        "panne": MoteurInstrumente(FauxMoteur(echec=True), EnregistreurBase(pool)),
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


async def test_dialogue_complet(client: httpx.AsyncClient, pool: Base) -> None:
    rep = await client.post("/v1/dialogue", json={"message": "Bonjour JARVIS"})
    assert rep.status_code == 200 and rep.headers["content-type"].startswith("text/event-stream")
    evenements = lire_sse(rep.text)
    # Premier échange : l'IA écrit ensuite un vrai titre (« titre »)
    assert [e for e, _ in evenements] == ["debut", "delta", "fin", "titre"]
    debut, fin = evenements[0][1], evenements[2][1]
    assert evenements[3][1]["titre"] == "A"
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
    assert await pool.fetchval("SELECT count(*) FROM telemetrie WHERE statut = 'ok'") == 3  # 2 réponses + le titre
    assert (await client.get(f"/v1/conversations/{debut['conversation_id']}")).json()["conversation"][
        "titre_source"
    ] == "auto"


async def test_historique_chercher_renommer_epingler(client: httpx.AsyncClient) -> None:
    debut = lire_sse((await client.post("/v1/dialogue", json={"message": "Parlons du potager"})).text)[0][1]
    lire_sse((await client.post("/v1/dialogue", json={"message": "Autre sujet : la voiture"})).text)
    ident = debut["conversation_id"]
    trouvees = (await client.get("/v1/conversations", params={"q": "POTAGER"})).json()["conversations"]
    assert [c["id"] for c in trouvees] == [ident]
    rep = await client.patch(f"/v1/conversations/{ident}", json={"titre": "  Mon   potager ", "epinglee": True})
    conv = rep.json()["conversation"]
    assert conv["titre"] == "Mon potager" and conv["titre_source"] == "utilisateur" and conv["epinglee"]
    assert (await client.get("/v1/conversations")).json()["conversations"][0]["id"] == ident  # épinglée en tête
    assert (await client.patch(f"/v1/conversations/{ident}", json={"archivee": True})).status_code == 422
    assert (await client.patch(f"/v1/conversations/{ident}", json={"titre": "   "})).status_code == 422


async def test_dialogue_erreur_moteur(client: httpx.AsyncClient, pool: Base) -> None:
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
    assert [c["titre"] for c in etat["conversations"]] == ["A"]  # titre écrit par l'IA (faux moteur : « a »)


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


async def test_cache_de_l_interface(client: httpx.AsyncClient) -> None:
    """Après une mise à jour, la page est revalidée (sinon l'ancienne interface reste) ; les fichiers à empreinte
    sont gardés."""
    assert (await client.get("/")).headers["cache-control"] == "no-cache"
    assert "immutable" in (await client.get("/assets/inexistant.js")).headers["cache-control"]


async def test_origine_inconnue_refusee(client: httpx.AsyncClient) -> None:
    rep = await client.post("/v1/dialogue", json={"message": "x"}, headers={"Origin": "https://malveillant.example"})
    assert rep.status_code == 403
    ok = await client.get("/v1/sante", headers={"Origin": "http://127.0.0.1:5174"})
    assert ok.status_code == 200 and ok.json()["base"] is True and ok.json()["schema"] == lister_migrations()[-1][0]
