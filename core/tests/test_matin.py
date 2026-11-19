"""Accueil du matin : premier lancement du jour par appareil, météo Open-Meteo FACTICE (aucun réseau), lieu privé,
modes, arrêt d'urgence, préréglages du premier lancement."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from jarvis2 import matin
from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.connecteurs import Connecteurs, Definition
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import ServiceDialogue
from jarvis2.moteurs.telemetrie import EnregistreurBase, MoteurInstrumente
from jarvis2.securite import appareils
from jarvis2.securite.coffre import Coffre

from .test_connecteurs import Faux

pytestmark = pytest.mark.base

VILLE = "Villeprivée"


class OpenMeteoFactice:
    def __init__(self) -> None:
        self.appels: list[httpx.Request] = []
        self.en_panne = False

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        self.appels.append(requete)
        if self.en_panne:
            return httpx.Response(503)
        if requete.url.host == "geocoding-api.open-meteo.com":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"name": VILLE, "admin1": "Région", "country": "France", "latitude": 45.5, "longitude": 4.25}
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "current": {"temperature_2m": 7.6, "weather_code": 3},
                "daily": {
                    "temperature_2m_min": [3.2],
                    "temperature_2m_max": [11.4],
                    "precipitation_probability_max": [70],
                },
            },
        )


@pytest.fixture
async def systeme(pool: Base, tmp_path: Path) -> dict[str, Any]:
    moteurs = {"local": Faux("local", "local", externe=False)}
    coffre = Coffre(tmp_path / "coffre.json")
    defs = {i: Definition(MoteurInstrumente(m, EnregistreurBase(pool))) for i, m in moteurs.items()}
    connecteurs = Connecteurs(pool, defs, coffre)
    await connecteurs.charger()
    depot = DepotConversations(pool)
    service = ServiceDialogue(depot, connecteurs.moteurs, "local", None, connecteurs)
    factice = OpenMeteoFactice()
    ctx = Contexte(
        pool,
        depot,
        connecteurs.moteurs,
        service,
        "local",
        connecteurs=connecteurs,
        dossier_recettes=tmp_path / "recettes",
        meteo=matin.ServiceMeteo(httpx.MockTransport(factice)),
        matin_locale={"ville": VILLE},
    )
    p = Parametres().model_copy(
        update={"stockage": pool.dialecte, "sqlite": tmp_path / "jarvis2.db", "dossier_donnees": tmp_path}
    )
    app = creer_app(p, ctx)
    app.state.ctx = ctx

    async def client(nom: str) -> httpx.AsyncClient:
        _, jeton = await appareils.creer(pool, nom, "pc")
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost:8765",
            headers={"Authorization": f"Bearer {jeton}"},
        )

    return {"client": await client("PC"), "nouveau": client, "ctx": ctx, "factice": factice, "dossier": tmp_path}


async def test_premier_lancement_du_jour_par_appareil(systeme: dict[str, Any]) -> None:
    client, factice = systeme["client"], systeme["factice"]
    carte = (await client.get("/v1/matin")).json()
    assert carte["afficher"] is True and carte["mode"] == "parle" and carte["lieu_connu"] is True
    assert carte["meteo"]["temperature"] == 7.6 and carte["meteo"]["ciel"] == "ciel couvert"
    assert "À la maison : 8 degrés, ciel couvert ; entre 3 et 11" in carte["texte_parle"]
    assert "70 % de risque de pluie" in carte["texte_parle"]
    assert VILLE not in json.dumps(carte)  # le lieu n'est jamais lu à voix haute ni renvoyé avec la carte
    assert carte["salutation"] in ("Bonjour", "Bonsoir") and carte["texte_parle"].startswith(carte["salutation"])
    assert (await client.post("/v1/matin/vu")).status_code == 200
    assert (await client.get("/v1/matin")).json() == {"afficher": False, "raison": "deja_vu", "mode": "parle"}
    assert (await client.get("/v1/matin", params={"rejouer": True})).json()["afficher"] is True  # « Rejouer »
    autre = await systeme["nouveau"]("Téléphone")
    assert (await autre.get("/v1/matin")).json()["afficher"] is True  # chaque appareil a son premier lancement
    # Ville géocodée une seule fois, météo en cache
    hotes = [r.url.host for r in factice.appels]
    assert hotes.count("geocoding-api.open-meteo.com") == 1 and hotes.count("api.open-meteo.com") == 1


async def test_modes_et_arret_d_urgence(systeme: dict[str, Any]) -> None:
    client, ctx = systeme["client"], systeme["ctx"]
    assert (await client.put("/v1/matin/reglages", json={"mode": "texte"})).json()["mode"] == "texte"
    assert (await client.get("/v1/matin")).json()["mode"] == "texte"
    await client.put("/v1/matin/reglages", json={"mode": "desactive"})
    assert (await client.get("/v1/matin")).json()["raison"] == "desactive"
    assert (await client.get("/v1/matin", params={"rejouer": True})).json()["afficher"] is True
    assert (await client.put("/v1/matin/reglages", json={"mode": "fort"})).status_code == 422
    ctx.urgence.actif = True
    for params in ({}, {"rejouer": True}):  # jamais pendant l'arrêt d'urgence, même rejoué
        assert (await client.get("/v1/matin", params=params)).json()["raison"] == "urgence"


async def test_localisation_privee(systeme: dict[str, Any], pool: Base) -> None:
    client, factice = systeme["client"], systeme["factice"]
    assert (await client.get("/v1/matin/reglages")).json()["localisation"] == {
        "nom": VILLE,
        "source": "configuration",
    }
    lieux = (await client.get("/v1/matin/lieux", params={"q": "Ville"})).json()["lieux"]
    assert lieux[0]["nom"] == VILLE and lieux[0]["latitude"] == 45.5
    assert (await client.get("/v1/matin/lieux", params={"q": "x"})).status_code == 422
    position = {"latitude": 43.3, "longitude": 5.4, "nom": "Position de l'appareil", "source": "appareil"}
    reglages = (await client.put("/v1/matin/reglages", json={"localisation": position})).json()
    assert reglages["localisation"]["source"] == "appareil" and reglages["localisation"]["latitude"] == 43.3
    await client.get("/v1/matin")
    assert factice.appels[-1].url.params["latitude"] == "43.3"
    audit = await pool.fetch("SELECT details FROM audit WHERE action = 'matin.reglages'")
    assert audit and all("43.3" not in str(a["details"]) and VILLE not in str(a["details"]) for a in audit)
    effacee = (await client.put("/v1/matin/reglages", json={"effacer_localisation": True})).json()
    assert effacee["localisation"]["source"] == "configuration"  # retour à la configuration locale
    factice.en_panne = True
    assert (await client.get("/v1/matin/lieux", params={"q": "Ville"})).status_code == 502


async def test_meteo_en_panne_et_sans_lieu(systeme: dict[str, Any]) -> None:
    client, ctx, factice = systeme["client"], systeme["ctx"], systeme["factice"]
    factice.en_panne = True
    carte = (await client.get("/v1/matin")).json()
    assert carte["afficher"] is True and carte["meteo"] is None and "maison" not in carte["texte_parle"]
    ctx.matin_locale = {}
    assert (await client.get("/v1/matin", params={"rejouer": True})).json()["lieu_connu"] is False


async def test_recettes_et_points_d_attention(systeme: dict[str, Any], pool: Base) -> None:
    client, dossier = systeme["client"], systeme["dossier"]
    (dossier / "recettes").mkdir()
    (dossier / "recettes" / "veille.yaml").write_text(
        "nom: Veille du matin\nplanification: '0 7 * * *'\nconsigne: Résume.\n", "utf-8"
    )
    maintenant = datetime.now(UTC)
    for recette, statut in (("veille", "ok"), ("rapport", "erreur"), ("systeme:nuit", "erreur")):
        await pool.execute(
            "INSERT INTO executions_recettes (recette, declencheur, debut, statut)"
            " VALUES ($1, 'planification', $2, $3)",
            recette,
            maintenant,
            statut,
        )
    carte = (await client.get("/v1/matin")).json()
    assert {r["id"] for r in carte["recettes"]} == {"veille", "rapport"}  # tâches système écartées
    assert "Ce matin : Veille du matin." in carte["texte_parle"]
    assert carte["attention"] == ["La recette « rapport » a échoué ce matin."]


def test_points_d_attention_limites_a_deux() -> None:
    recettes = [{"nom": "a", "statut": "erreur"}, {"nom": "b", "statut": "erreur"}]
    points = matin.points_attention(recettes, 3)
    assert points == ["2 recettes ont échoué ce matin.", "3 demandes attendent votre approbation."]
    assert len(matin.points_attention(recettes, 1)) <= matin.MAX_ATTENTION


async def test_prereglages_du_premier_lancement(systeme: dict[str, Any]) -> None:
    client, dossier, ctx = systeme["client"], systeme["dossier"], systeme["ctx"]
    await client.put("/v1/matin/reglages", json={"mode": "desactive"})
    rep = (await client.post("/v1/accueil/prereglages", json={"choix": ["point_du_matin", "code"]})).json()
    assert rep == {"prereglages": ["code", "point_du_matin"], "recette": "creee"}
    recette = yaml.safe_load((dossier / "recettes" / "point-du-matin.yaml").read_text("utf-8"))
    assert recette["nom"] == "Point du matin" and recette["active"] is True
    assert ctx.planificateur is not None and "point-du-matin" in {r.id for r in ctx.planificateur.recettes()[0]}
    assert (await client.get("/v1/matin/reglages")).json()["mode"] == "parle"
    again = (await client.post("/v1/accueil/prereglages", json={"choix": ["point_du_matin"]})).json()
    assert again["recette"] == "existante"  # jamais écrasée
    assert (await client.post("/v1/accueil/prereglages", json={"choix": ["autre"]})).status_code == 422
    await client.post("/v1/accueil/terminer")
    etat = (await client.get("/v1/accueil")).json()
    assert etat["termine"] is True and etat["prereglages"] == ["point_du_matin"]
