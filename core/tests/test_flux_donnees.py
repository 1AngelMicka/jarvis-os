"""« Où partent mes données » : carte des flux depuis la configuration réelle, accord images vers le cloud."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncGenerator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis2 import matin
from jarvis2.agents.mcp import GestionnaireMCP
from jarvis2.agents.recherche_web import RechercheWeb
from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.connecteurs import Connecteurs, Definition
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import AccordImagesRequis, ServiceDialogue
from jarvis2.flux_donnees import destination_url
from jarvis2.moteurs.base import (
    Delta,
    EtatSante,
    Evenement,
    Fin,
    Image,
    InfoModele,
    Message,
    Moteur,
    Options,
    Reponse,
    Usage,
)
from jarvis2.moteurs.telemetrie import EnregistreurBase, MoteurInstrumente
from jarvis2.securite import appareils
from jarvis2.securite.coffre import Coffre

pytestmark = pytest.mark.base

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
CLE = "sk-ant-api03-" + "x" * 40
SEARXNG = "http://192.168.1.20:8888"


class Faux(Moteur):
    def __init__(
        self, ident: str, famille: str, vision: bool = True, url: str | None = None, installe: bool = True
    ) -> None:
        self.id, self.nom, self.famille = ident, f"Faux {ident}", famille  # type: ignore[assignment]
        self.externe = famille != "local"
        self.vision = vision
        self.actif_par_defaut = True
        if url:
            self.url = url
        self.installe = installe
        self.recus: list[Sequence[Message]] = []

    async def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        self.recus.append(list(messages))
        yield Delta("vu")
        yield Fin(Reponse("vu", "m", Usage(), 0.0, {}))

    async def list_models(self) -> list[InfoModele]:
        return []

    async def health(self) -> EtatSante:
        return EtatSante(self.installe, installe=self.installe)


@pytest.fixture
async def systeme(pool: Base, tmp_path: Path) -> dict[str, Any]:
    moteurs = {
        "compte": Faux("compte", "cli"),
        "cle": Faux("cle", "api"),
        "sanscle": Faux("sanscle", "api"),
        "absent": Faux("absent", "cli", installe=False),
        "maison": Faux("maison", "local", url="http://192.168.1.30:11434"),
        "local": Faux("local", "local", url="http://127.0.0.1:11434"),
    }
    coffre = Coffre(tmp_path / "coffre.json", chiffrement=False)
    coffre.definir("cle", CLE)
    defs = {
        i: Definition(MoteurInstrumente(m, EnregistreurBase(pool)), i if "cle" in i else None)
        for i, m in moteurs.items()
    }
    connecteurs = Connecteurs(pool, defs, coffre, prefere="compte")
    await connecteurs.charger()
    depot = DepotConversations(pool)
    service = ServiceDialogue(depot, connecteurs.moteurs, "compte", None, connecteurs)
    service.titre_auto = False
    ctx = Contexte(
        pool,
        depot,
        connecteurs.moteurs,
        service,
        "compte",
        connecteurs=connecteurs,
        recherche=RechercheWeb(SEARXNG),
        mcp=GestionnaireMCP.depuis_config(
            [{"id": "fichiers", "commande": "C:/Rangement/serveur.exe", "args": ["D:/Perso"]}]
        ),
        matin_locale={"ville": "Villeprivee", "latitude": 45.123456, "longitude": 4.654321},
    )
    app = creer_app(Parametres(dossier_donnees=tmp_path), ctx)
    app.state.ctx = ctx
    _, jeton = await appareils.creer(pool, "PC", "pc")
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:8765",
        headers={"Authorization": f"Bearer {jeton}"},
    )
    return {"client": client, "connecteurs": connecteurs, "service": service, "moteurs": moteurs, "pool": pool}


@pytest.mark.parametrize(
    ("url", "attendu"),
    [
        ("http://127.0.0.1:8888", "pc"),
        ("http://localhost:1234/v1", "pc"),
        ("http://[::1]:80", "pc"),
        ("http://192.168.1.20:8888", "reseau"),
        ("http://10.0.0.2", "reseau"),
        ("http://100.101.102.103", "reseau"),
        ("https://pc.tailnet-abc.ts.net", "reseau"),
        ("http://nas.local:8080", "reseau"),
        ("http://nas:8080", "reseau"),
        ("https://search.example.org", "internet"),
        ("https://8.8.8.8", "internet"),
        (None, "internet"),
    ],
)
def test_destination_url(url: str | None, attendu: str) -> None:
    assert destination_url(url) == attendu


async def test_flux_depuis_la_configuration_reelle(systeme: dict[str, Any]) -> None:
    r = await systeme["client"].get("/v1/donnees/flux")
    assert r.status_code == 200
    corps = r.json()
    flux = {f["id"]: f for f in corps["flux"]}
    # Connecteurs : actifs et avec leur clé seulement (« sanscle » n'a pas de clé : rien ne part)
    assert {"connecteur:compte", "connecteur:cle", "connecteur:maison", "connecteur:local"} <= set(flux)
    # « absent » : programme non installé, rien ne peut partir
    assert "connecteur:sanscle" not in flux and "connecteur:absent" not in flux
    assert corps["resume"]["connecteurs_inactifs"] == 2
    assert flux["connecteur:local"]["destination"] == "pc" and flux["connecteur:local"]["local"] is True
    assert flux["connecteur:maison"]["destination"] == "reseau"
    assert flux["connecteur:cle"]["destination"] == "internet" and flux["connecteur:cle"]["jamais"]
    assert flux["connecteur:cle"]["images"] == {"accorde": False, "accorde_le": None}
    assert flux["connecteur:local"]["images"] is None  # local : aucun accord à donner
    assert flux["connecteur:cle"]["desactiver"]["reglage"] == "connecteurs"
    # Recherche, météo, MCP, téléchargements, locaux
    assert flux["searxng"]["etat"] == "actif" and flux["searxng"]["destination"] == "internet"
    assert flux["searxng"]["detail"] == "Instance sur votre réseau."
    assert flux["scientifique"]["etat"] == "inactif"  # pas de sources dans ce contexte
    assert flux["meteo"]["etat"] == "actif" and flux["meteo"]["desactiver"]["reglage"] == "accueil-matin"
    assert flux["mcp:fichiers"]["destination"] == "variable" and flux["mcp:fichiers"]["etat"] == "inactif"
    assert flux["mcp:fichiers"]["desactiver"]["vue"] == "agents"
    assert flux["telechargements"]["etat"] == "sur_accord"
    assert flux["telephone"]["etat"] == "inactif"
    assert flux["interface"]["local"] is True
    # Aucun secret, aucune adresse, aucun lieu, aucun chemin
    texte = json.dumps(corps, ensure_ascii=False)
    for interdit in (
        CLE,
        "sk-ant",
        "192.168",
        "8888",
        "Villeprivee",
        "45.12",
        "4.65",
        "Rangement",
        "serveur.exe",
        "Perso",
        "11434",
    ):
        assert interdit not in texte, interdit


async def test_meteo_desactivee(systeme: dict[str, Any]) -> None:
    pool = systeme["pool"]
    etat = await matin.lire_etat(pool)
    await matin.ecrire_etat(pool, {**etat, "mode": "desactive"})
    flux = {f["id"]: f for f in (await systeme["client"].get("/v1/donnees/flux")).json()["flux"]}
    assert flux["meteo"]["etat"] == "inactif"


def _image() -> str:
    return f"data:image/png;base64,{base64.b64encode(PNG).decode()}"


async def test_accord_images_cloud_une_fois_par_connecteur(systeme: dict[str, Any]) -> None:
    client, pool, moteurs = systeme["client"], systeme["pool"], systeme["moteurs"]
    corps = {"message": "Regarde", "moteur": "cle", "images": [_image()]}
    # Sans accord : événement dédié, rien envoyé au moteur, rien enregistré (pas de conversation vide)
    r = await client.post("/v1/dialogue", json=corps)
    assert "event: accord_images" in r.text and '"connecteur": "cle"' in r.text
    assert moteurs["cle"].recus == []
    assert await pool.fetchval("SELECT count(*) FROM conversations") == 0
    # Un connecteur local n'en demande pas
    r = await client.post("/v1/dialogue", json={**corps, "moteur": "local"})
    assert "event: fin" in r.text and len(moteurs["local"].recus) == 1
    # Accord donné : mémorisé, l'image part ; audit tracé
    assert (await client.put("/v1/connecteurs/cle/images", json={"accorde": True})).json() == {"ok": True}
    r = await client.post("/v1/dialogue", json=corps)
    assert "event: fin" in r.text and moteurs["cle"].recus[0][-1].images == (Image("image/png", PNG),)
    carte = next(c for c in (await client.get("/v1/connecteurs")).json()["connecteurs"] if c["id"] == "cle")
    assert carte["images_accord_requis"] is True and carte["images_accordees_le"]
    flux = {f["id"]: f for f in (await client.get("/v1/donnees/flux")).json()["flux"]}
    assert flux["connecteur:cle"]["images"]["accorde"] is True
    actions = [r["action"] for r in await pool.fetch("SELECT action FROM audit ORDER BY id")]
    assert "connecteur.images_accordees" in actions
    # Accord propre au connecteur : « compte » le demande encore
    r = await client.post("/v1/dialogue", json={**corps, "moteur": "compte"})
    assert "event: accord_images" in r.text
    # Révoqué : de nouveau demandé ; un texte sans image passe toujours
    assert (await client.put("/v1/connecteurs/cle/images", json={"accorde": False})).status_code == 200
    r = await client.post("/v1/dialogue", json=corps)
    assert "event: accord_images" in r.text
    r = await client.post("/v1/dialogue", json={"message": "Sans image", "moteur": "cle"})
    assert "event: fin" in r.text
    assert "connecteur.images_revoquees" in [r["action"] for r in await pool.fetch("SELECT action FROM audit")]
    # Sans objet pour un connecteur local
    r = await client.put("/v1/connecteurs/local/images", json={"accorde": True})
    assert r.status_code == 422


async def test_accord_images_par_le_routeur(systeme: dict[str, Any]) -> None:
    """Choix automatique : le connecteur routé (cloud) demande l'accord avant toute image."""
    with pytest.raises(AccordImagesRequis) as exc:
        [e async for e in systeme["service"].repondre("Vois", images=[Image("image/png", PNG)])]
    assert exc.value.connecteur == "compte"
