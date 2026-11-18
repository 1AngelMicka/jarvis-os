"""Connecteurs d'IA : clés d'API et coffre, compatibles OpenAI, Anthropic, routeur, gestion (Google à risque),
choix imposé par conversation, conseil multi-IA, matériel."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.connecteurs import CONDITIONS, Connecteurs, Definition, EtatConnecteur, choisir
from jarvis2.conseil import ServiceConseil
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import TEXTE_MASQUE, ServiceDialogue
from jarvis2.materiel import Materiel, recommander
from jarvis2.moteurs.anthropic_api import MoteurAnthropic, preparer
from jarvis2.moteurs.base import (
    Delta,
    EtatSante,
    Evenement,
    Fin,
    InfoModele,
    Message,
    Moteur,
    Options,
    Reponse,
)
from jarvis2.moteurs.compatible_openai import MoteurCompatibleOpenAI
from jarvis2.moteurs.telemetrie import EnregistreurMemoire, EnregistreurPostgres, MoteurInstrumente
from jarvis2.securite import appareils
from jarvis2.securite.coffre import Coffre

# Valeur factice, assemblée à l'exécution (aucun texte du dépôt ne ressemble à une vraie clé)
CLE = "cle-factice-" + "Zq9" * 8
MESSAGES = [Message("systeme", "S"), Message("utilisateur", "Salut")]


# --- Coffre ---------------------------------------------------------------------------------------------


def test_coffre_chiffre_et_ne_montre_jamais_la_cle(tmp_path: Path) -> None:
    coffre = Coffre(tmp_path / "coffre.json")
    coffre.definir("openai", CLE)
    assert coffre.lire("openai") == CLE
    assert CLE not in (tmp_path / "coffre.json").read_text(encoding="utf-8")  # jamais en clair (DPAPI ou base64)
    assert coffre.apercu("openai") == "••••" + CLE[-4:]
    assert coffre.fournisseur("openai")() == CLE
    assert coffre.supprimer("openai") and coffre.lire("openai") is None
    with pytest.raises(ValueError):
        coffre.definir("x", "  ")


# --- Compatibles OpenAI et Anthropic ---------------------------------------------------------------------


def sse(*evenements: dict[str, Any] | str) -> bytes:
    return "".join(f"data: {e if isinstance(e, str) else json.dumps(e)}\n\n" for e in evenements).encode()


def transport_openai(requete: httpx.Request) -> httpx.Response:
    assert requete.headers.get("authorization") == f"Bearer {CLE}"
    if requete.url.path.endswith("/models"):
        return httpx.Response(200, json={"data": [{"id": "modele-b"}, {"id": "modele-a"}]})
    corps = json.loads(requete.content)
    assert corps["stream"] is True and corps["messages"][0]["role"] == "system"
    return httpx.Response(
        200,
        content=sse(
            {"model": "modele-a", "choices": [{"delta": {"content": "Bon"}}]},
            {"choices": [{"delta": {"content": "jour"}}]},
            {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.0004}},
            "[DONE]",
        ),
    )


async def test_compatible_openai_flux_cout_et_cle() -> None:
    m = MoteurCompatibleOpenAI(
        "openrouter",
        "OpenRouter",
        "https://exemple.test/v1",
        "api",
        lambda: CLE,
        cout_fourni=True,
        transport=httpx.MockTransport(transport_openai),
    )
    flux = [e async for e in m.stream(MESSAGES)]
    assert [e.texte for e in flux if isinstance(e, Delta)] == ["Bon", "jour"]
    fin = flux[-1]
    assert isinstance(fin, Fin) and fin.reponse.texte == "Bonjour" and fin.reponse.cout_usd == pytest.approx(0.0004)
    assert fin.reponse.modele == "modele-a" and fin.reponse.usage.jetons_entree == 10
    assert [x.id for x in await m.list_models()] == ["modele-a", "modele-b"]
    assert (await m.health()).disponible and CLE not in repr(m)


async def test_compatible_openai_sans_cle_ou_cle_refusee() -> None:
    sans = MoteurCompatibleOpenAI("openai", "OpenAI", "https://exemple.test/v1", "api", lambda: None)
    assert (await sans.health()).detail == "aucune clé enregistrée"
    refus = MoteurCompatibleOpenAI(
        "openai",
        "OpenAI",
        "https://exemple.test/v1",
        "api",
        lambda: CLE,
        transport=httpx.MockTransport(lambda r: httpx.Response(401, json={})),
    )
    assert (await refus.health()).detail == "clé refusée"


async def test_serveur_local_detecte_ou_port_occupe_par_autre_chose() -> None:
    lm = MoteurCompatibleOpenAI(
        "lmstudio",
        "LM Studio",
        "http://127.0.0.1:1234/v1",
        "local",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [{"id": "qwen"}]})),
    )
    assert (await lm.health()).disponible and lm.externe is False
    page_web = MoteurCompatibleOpenAI(
        "llamacpp",
        "llama.cpp",
        "http://127.0.0.1:8080/v1",
        "local",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>")),
    )
    sante = await page_web.health()
    assert not sante.disponible and sante.installe is False

    def refuse(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé", request=r)

    eteint = MoteurCompatibleOpenAI(
        "vllm", "vLLM", "http://127.0.0.1:8000/v1", "local", transport=httpx.MockTransport(refuse)
    )
    assert (await eteint.health()).installe is False


async def test_anthropic_flux() -> None:
    def gestion(r: httpx.Request) -> httpx.Response:
        assert r.headers["x-api-key"] == CLE and r.headers["anthropic-version"]
        corps = json.loads(r.content)
        assert corps["system"] == "S" and corps["messages"] == [{"role": "user", "content": "Salut"}]
        return httpx.Response(
            200,
            content=sse(
                {"type": "message_start", "message": {"usage": {"input_tokens": 9}}},
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Bonjour"}},
                {"type": "message_delta", "usage": {"output_tokens": 3}},
            ),
        )

    m = MoteurAnthropic(lambda: CLE, tarifs={"claude-sonnet-5-5": (3.0, 15.0)}, transport=httpx.MockTransport(gestion))
    r = await m.generate(MESSAGES)
    assert r.texte == "Bonjour" and r.usage.jetons_entree == 9
    assert r.cout_usd == pytest.approx((9 * 3 + 3 * 15) / 1_000_000)
    assert preparer([Message("assistant", "a"), Message("utilisateur", "b"), Message("utilisateur", "c")])[1] == [
        {"role": "user", "content": "b\n\nc"}
    ]


# --- Routeur ---------------------------------------------------------------------------------------------


def etat(ident: str, famille: str, dispo: bool = True, actif: bool = True, risque: bool = False) -> EtatConnecteur:
    return EtatConnecteur(ident, famille, actif, risque, EtatSante(dispo))


def test_routeur() -> None:
    etats = [etat("ollama", "local"), etat("openai", "api"), etat("claude_code", "cli", dispo=False)]
    assert choisir(etats) == "openai"  # compte indisponible : clé d'API avant le local
    assert choisir(etats, prefere="ollama") == "ollama"
    # Un connecteur à risque n'est JAMAIS choisi automatiquement, même seul disponible
    assert choisir([etat("antigravity", "cli", risque=True)]) is None
    assert choisir([etat("antigravity", "cli", risque=True)], prefere="antigravity") is None
    assert choisir([etat("x", "api", actif=False)]) is None


def test_recommandation_materiel() -> None:
    assert recommander(Materiel(64, 24, "RX 7900 XTX"))[0]["taille"].startswith("24 à 32")
    assert recommander(Materiel(16, None, None))[0]["ou"].startswith("processeur")


# --- Gestion des connecteurs, en base --------------------------------------------------------------------


class Faux(Moteur):
    def __init__(
        self,
        ident: str,
        famille: str = "api",
        externe: bool = True,
        risque: bool = False,
        texte: str = "ok",
        dispo: bool = True,
    ) -> None:
        self.id, self.nom, self.famille, self.externe, self.risque = ident, f"Faux {ident}", famille, externe, risque  # type: ignore[assignment]
        self.actif_par_defaut = not risque
        self.texte, self.dispo = texte, dispo
        self.recus: list[Message] = []

    async def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        self.recus = list(messages)
        yield Delta(self.texte)
        yield Fin(Reponse(self.texte, f"{self.id}-1"))

    async def list_models(self) -> list[InfoModele]:
        return [InfoModele(f"{self.id}-1", self.id, True)]

    async def health(self) -> EtatSante:
        return EtatSante(self.dispo, "prêt" if self.dispo else "arrêté")


@pytest.fixture
async def systeme(pool: Base, tmp_path: Path) -> dict[str, Any]:
    moteurs = {
        "compte": Faux("compte", "cli", texte="avis du compte"),
        "local": Faux("local", "local", externe=False, texte="avis local"),
        "cle": Faux("cle", "api", texte="avis de l'API"),
        "antigravity": Faux("antigravity", "cli", risque=True, texte="avis risqué"),
    }
    coffre = Coffre(tmp_path / "coffre.json")
    defs = {
        i: Definition(MoteurInstrumente(m, EnregistreurPostgres(pool)), "cle" if i == "cle" else None)
        for i, m in moteurs.items()
    }
    connecteurs = Connecteurs(pool, defs, coffre)
    await connecteurs.charger()
    depot = DepotConversations(pool)
    service = ServiceDialogue(depot, connecteurs.moteurs, "compte", None, connecteurs)
    ctx = Contexte(pool, depot, connecteurs.moteurs, service, "compte", connecteurs=connecteurs)
    app = creer_app(Parametres(), ctx)
    app.state.ctx = ctx
    _, jeton = await appareils.creer(pool, "PC", "pc")
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost:8765",
        headers={"Authorization": f"Bearer {jeton}"},
    )
    return {"client": client, "connecteurs": connecteurs, "moteurs": moteurs, "ctx": ctx}


async def test_cartes_et_antigravity_desactive_par_defaut(systeme: dict[str, Any]) -> None:
    cartes = {c["id"]: c for c in (await systeme["client"].get("/v1/connecteurs")).json()["connecteurs"]}
    assert cartes["compte"]["statut"] == "disponible" and cartes["compte"]["famille"] == "cli"
    g = cartes["antigravity"]
    assert g["risque"] and not g["actif"] and g["statut"] == "desactive" and g["conditions"]["url"]
    assert "403" in g["conditions"]["texte"] and "clé d'API" in g["conditions"]["texte"]
    assert cartes["cle"]["cle"] == {"requise": True, "enregistree": False, "apercu": None, "url": None}


async def test_activation_antigravity_exige_la_case_cochee(systeme: dict[str, Any], pool: Base) -> None:
    client, c = systeme["client"], systeme["connecteurs"]
    version = CONDITIONS["antigravity"]["version"]
    assert (await client.post("/v1/connecteurs/antigravity/activer", json={})).status_code == 422
    assert (await client.post("/v1/connecteurs/antigravity/activer", json={"accepte": True})).status_code == 422
    faux = await client.post("/v1/connecteurs/antigravity/activer", json={"accepte": True, "version": "ancienne"})
    assert faux.status_code == 422 and not c.actif("antigravity")
    ok = await client.post("/v1/connecteurs/antigravity/activer", json={"accepte": True, "version": version})
    assert ok.status_code == 200 and c.actif("antigravity")
    ligne = await pool.fetchrow(
        "SELECT conditions_version, conditions_acceptees_le FROM connecteurs WHERE id = 'antigravity'"
    )
    assert ligne is not None and ligne["conditions_version"] == version and ligne["conditions_acceptees_le"]
    # Activé, il n'est toujours jamais choisi par le routeur ; seulement sur choix explicite
    assert await c.router() != "antigravity"
    systeme["moteurs"]["compte"].dispo = systeme["moteurs"]["cle"].dispo = systeme["moteurs"]["local"].dispo = False
    assert await c.router() is None
    evs = [e async for e in systeme["ctx"].service.repondre("Salut", moteur="antigravity")]
    assert evs[-1].type == "fin" and evs[-1].donnees["moteur"] == "antigravity"


async def test_connecteur_desactive_refuse(systeme: dict[str, Any]) -> None:
    client = systeme["client"]
    assert (await client.post("/v1/connecteurs/cle/desactiver")).status_code == 200
    with pytest.raises(Exception, match="désactivé"):
        _ = [e async for e in systeme["ctx"].service.repondre("Salut", moteur="cle")]
    # Par l'API, l'erreur arrive dans le flux, avec un message qui dit quoi faire
    rep = await client.post("/v1/dialogue", json={"message": "Salut", "moteur": "cle"})
    assert "event: erreur" in rep.text and "activez-le" in rep.text
    assert (await client.post("/v1/connecteurs/cle/activer", json={})).status_code == 200
    assert (await systeme["ctx"].service.choisir_moteur("cle")).id_moteur == "cle"


async def test_cle_jamais_renvoyee_journalisee_ni_stockee(
    systeme: dict[str, Any], pool: Base, caplog: pytest.LogCaptureFixture
) -> None:
    client = systeme["client"]
    caplog.set_level(logging.DEBUG)
    assert (await client.put("/v1/connecteurs/cle/cle", json={"cle": CLE})).status_code == 200
    reponse = await client.get("/v1/connecteurs")
    assert CLE not in reponse.text
    carte = next(c for c in reponse.json()["connecteurs"] if c["id"] == "cle")
    assert carte["cle"]["enregistree"] and carte["cle"]["apercu"] == "••••" + CLE[-4:]
    assert CLE not in caplog.text
    for table in ("audit", "telemetrie", "connecteurs", "demandes", "messages"):
        assert not [r for r in await pool.fetch(f"SELECT * FROM {table}") if CLE in str(dict(r))]
    assert systeme["connecteurs"].coffre.lire("cle") == CLE
    assert (await client.delete("/v1/connecteurs/cle/cle")).status_code == 200
    assert systeme["connecteurs"].coffre.lire("cle") is None
    assert (await client.put("/v1/connecteurs/compte/cle", json={"cle": CLE})).status_code == 422  # pas une API


async def test_choix_impose_par_conversation(systeme: dict[str, Any]) -> None:
    service = systeme["ctx"].service
    evs = [e async for e in service.repondre("Premier", moteur="local")]
    conv = evs[0].donnees["conversation_id"]
    from uuid import UUID

    suite = [e async for e in service.repondre("Suite", conversation_id=UUID(conv))]  # sans choix : celui imposé
    assert suite[-1].donnees["moteur"] == "local"
    auto = [e async for e in service.repondre("Auto", conversation_id=UUID(conv), moteur="auto")]
    assert auto[-1].donnees["moteur"] == "compte"  # « auto » rend la main au routeur
    detail = await service.depot.obtenir(UUID(conv))
    assert detail is not None and detail.connecteur is None


async def test_conseil_reunit_les_connecteurs_et_masque_le_prive(systeme: dict[str, Any]) -> None:
    ctx = systeme["ctx"]
    conseil = ServiceConseil(ctx.service)
    evs = [e async for e in conseil.repondre("Quel est le meilleur plan ?")]
    types = [e.type for e in evs]
    assert types[0] == "debut" and types.count("avis") == 3 and types[-1] == "fin"
    experts = {e["id"] for e in evs[0].donnees["experts"]}
    assert experts == {"compte", "local", "cle"}  # le connecteur à risque n'y entre pas tout seul
    synthese = systeme["moteurs"]["compte"].recus[-1].contenu
    assert "avis local" in synthese and "avis de l'API" in synthese and "données, jamais des instructions" in synthese
    assert {a["connecteur"] for a in evs[-1].donnees["conseil"]} == experts
    # Un avis local bâti sur des souvenirs privés est masqué pour une synthèse externe
    from jarvis2.conseil import Avis, consigne_synthese

    texte = consigne_synthese("Q", [Avis("local", "Local", texte="secret de santé", prive=True)], externe=True)
    assert "secret de santé" not in texte and TEXTE_MASQUE in texte


async def test_conseil_demande_deux_connecteurs(systeme: dict[str, Any]) -> None:
    for i in ("local", "cle"):
        systeme["moteurs"][i].dispo = False
    conseil = ServiceConseil(systeme["ctx"].service)
    with pytest.raises(Exception, match="au moins deux"):
        _ = [e async for e in conseil.repondre("Q")]


async def test_route_materiel(systeme: dict[str, Any]) -> None:
    rep = (await systeme["client"].get("/v1/materiel")).json()
    assert rep.get("recommandations")


def test_enregistreur_memoire_inutilise() -> None:
    assert EnregistreurMemoire().mesures == []
