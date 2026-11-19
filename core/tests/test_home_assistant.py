"""Lot 14-D18 : connecteur Home Assistant (faux Home Assistant : REST, MCP HTTP, OAuth + PKCE ; aucun appel réel)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import ServiceDialogue
from jarvis2.maison import GestionnaireMaison
from jarvis2.maison.home_assistant import (
    COFFRE_CODE_ALARME,
    COFFRE_JETON,
    COFFRE_OAUTH,
    ErreurHomeAssistant,
    adresse_home_assistant,
    defi_pkce,
    niveau_entite,
    verifieur_pkce,
)
from jarvis2.moteurs.telemetrie import EnregistreurMemoire, MoteurInstrumente
from jarvis2.securite import appareils
from jarvis2.securite.coffre import Coffre

from .faux_home_assistant import ADRESSE, JETON_LONGUE_DUREE, FauxHomeAssistant
from .test_securite import ORIGINE, MoteurEspion, enregistrer_cle
from .test_transcription import FauxEmpreinteur, resultat

pytestmark = pytest.mark.base


@pytest.fixture
async def maison(pool: Base, tmp_path: Path) -> AsyncIterator[dict[str, Any]]:
    ha = FauxHomeAssistant()
    coffre = Coffre(tmp_path / "coffre.json", chiffrement=False)
    gestion = GestionnaireMaison(pool, coffre, transport_ha=ha.transport())
    depot = DepotConversations(pool)
    moteurs = {"espion": MoteurInstrumente(MoteurEspion(), EnregistreurMemoire())}
    ctx = Contexte(
        pool, depot, moteurs, ServiceDialogue(depot, moteurs, "espion"), "espion", maison=gestion,
        dossier_donnees=tmp_path, dossier_modeles=tmp_path,
    )  # fmt: skip
    ctx.proprietaire.empreinteur = FauxEmpreinteur()
    app = creer_app(Parametres(), ctx)
    app.state.ctx = ctx
    app.state.parametres = Parametres()
    await gestion.charger()
    _, jeton = await appareils.creer(pool, "PC", "pc")
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGINE,
        headers={"Authorization": f"Bearer {jeton}", "Origin": ORIGINE},
    )
    debut = datetime.now(UTC) - timedelta(seconds=1)
    try:
        yield {"client": client, "ha": ha, "coffre": coffre, "ctx": ctx, "debut": debut}
    finally:
        await client.aclose()


async def action(client: httpx.AsyncClient, nom_action: str, **parametres: Any) -> httpx.Response:
    return await client.post("/v1/actions", json={"action": nom_action, "parametres": parametres})


async def approuver(client: httpx.AsyncClient, reponse: httpx.Response) -> httpx.Response:
    corps = reponse.json()
    assert corps["statut"] == "en_attente", corps
    return await client.post(f"/v1/demandes/{corps['demande']['id']}/approuver", json={})


async def noms_actions(client: httpx.AsyncClient) -> set[str]:
    return {a["nom"] for a in (await client.get("/v1/actions")).json()["actions"]}


async def configurer_rest(m: dict[str, Any]) -> None:
    corps = {"adresse": ADRESSE, "mode": "rest", "jeton": JETON_LONGUE_DUREE}
    assert (await m["client"].put("/v1/maison/home-assistant", json=corps)).status_code == 200
    assert (await m["client"].post("/v1/maison/home-assistant/activer", json={"actif": True})).status_code == 200


async def audits_depuis(pool: Base, debut: datetime) -> list[dict[str, Any]]:
    lignes = await pool.fetch("SELECT action, details FROM audit WHERE horodatage >= $1 ORDER BY id", debut)
    return [{"action": r["action"], "details": str(r["details"])} for r in lignes]


# --- Désactivé par défaut -----------------------------------------------------------------------------------------


async def test_desactive_par_defaut(maison: dict[str, Any]) -> None:
    client, ha = maison["client"], maison["ha"]
    carte = (await client.get("/v1/maison/home-assistant")).json()
    assert carte["actif"] is False and carte["pret"] is False and carte["adresse"] is None
    assert len(carte["outils"]) == 7
    assert not {n for n in await noms_actions(client) if n.startswith("ha.")}
    assert (await action(client, "ha.etat")).status_code == 422
    refus = await client.post("/v1/maison/home-assistant/activer", json={"actif": True})
    assert refus.status_code == 422 and "adresse" in refus.json()["detail"]
    # Adresse Internet refusée : le jeton ne part jamais vers un service en ligne
    publique = await client.put("/v1/maison/home-assistant", json={"adresse": "https://93.184.216.34:8123"})
    assert publique.status_code == 422 and "réseau local" in publique.json()["detail"]
    assert ha.services == [] and ha.outils == []


# --- REST (repli, jeton longue durée) -------------------------------------------------------------------------------


async def test_rest_lecture_verte_et_commandes_jaunes(maison: dict[str, Any], pool: Base) -> None:
    client, ha = maison["client"], maison["ha"]
    await configurer_rest(maison)
    assert maison["coffre"].lire(COFFRE_JETON) == JETON_LONGUE_DUREE
    assert JETON_LONGUE_DUREE not in (await client.get("/v1/maison")).text
    assert {"ha.etat", "ha.lumiere", "ha.serrure"} <= await noms_actions(client)
    test = (await client.post("/v1/maison/home-assistant/tester")).json()
    assert test["disponible"] is True and "pilotable" in test["detail"]

    etat = (await action(client, "ha.etat")).json()
    assert etat["statut"] == "executee" and etat["resultat"]["source"] == "rest"
    niveaux = {e["entite"]: e["niveau"] for e in etat["resultat"]["entites"]}
    assert niveaux["light.salon"] == "jaune" and niveaux["lock.entree"] == "rouge"
    assert niveaux["cover.volet"] is None and niveaux["sensor.temperature"] is None

    demande = await action(client, "ha.lumiere", entite="light.salon", allumer=True, luminosite=40)
    assert demande.json()["demande"]["niveau"] == "jaune" and ha.services == []
    assert (await approuver(client, demande)).status_code == 200
    assert ha.services == [("light.turn_on", {"entity_id": "light.salon", "brightness_pct": 40})]

    assert (await approuver(client, await action(client, "ha.prise", entite="switch.cafetiere"))).status_code == 200
    media = await action(client, "ha.media", entite="media_player.salon", commande="volume", volume=30)
    assert (await approuver(client, media)).status_code == 200
    assert ha.services[-2:] == [
        ("switch.turn_on", {"entity_id": "switch.cafetiere"}),
        ("media_player.volume_set", {"entity_id": "media_player.salon", "volume_level": 0.3}),
    ]
    textes = [a["details"] for a in await audits_depuis(pool, maison["debut"])]
    assert not any(JETON_LONGUE_DUREE in t for t in textes)


async def test_domaine_impose_par_l_action(maison: dict[str, Any]) -> None:
    """« Allumer une prise » ne peut viser ni une serrure, ni un portail ; un volet n'est pas un portail."""
    client, ha = maison["client"], maison["ha"]
    await configurer_rest(maison)
    detour = await approuver(client, await action(client, "ha.prise", entite="lock.entree"))
    assert detour.status_code == 409 and "switch" in detour.json()["detail"]
    volet = (await action(client, "ha.portail", entite="cover.volet", operation="ouvrir")).json()
    assert volet == {"detail": volet["detail"]}  # refusé avant même la demande (voix du propriétaire absente)
    assert ha.services == []


async def test_arret_d_urgence(maison: dict[str, Any]) -> None:
    client, ha = maison["client"], maison["ha"]
    await configurer_rest(maison)
    demande = await action(client, "ha.lumiere", entite="light.salon")
    await client.post("/v1/urgence/arreter")
    assert (await action(client, "ha.lumiere", entite="light.salon")).status_code == 423
    refus = await approuver(client, demande)
    assert refus.status_code == 409 and "urgence" in refus.json()["detail"]
    assert ha.services == []


async def test_desactivation_et_oubli(maison: dict[str, Any]) -> None:
    client = maison["client"]
    await configurer_rest(maison)
    demande = await action(client, "ha.lumiere", entite="light.salon")
    assert (await client.post("/v1/maison/home-assistant/activer", json={"actif": False})).status_code == 200
    assert (await approuver(client, demande)).status_code == 409
    assert (await client.delete("/v1/maison/home-assistant")).status_code == 200
    assert maison["coffre"].lire(COFFRE_JETON) is None
    assert (await client.get("/v1/maison/home-assistant")).json()["adresse"] is None


# --- MCP HTTP + OAuth/PKCE ----------------------------------------------------------------------------------------


async def connecter_oauth(m: dict[str, Any]) -> None:
    client, ha = m["client"], m["ha"]
    assert (await client.put("/v1/maison/home-assistant", json={"adresse": ADRESSE})).status_code == 200
    url = (await client.post("/v1/maison/home-assistant/oauth")).json()["url"]
    morceaux = urlsplit(url)
    params = {k: v[0] for k, v in parse_qs(morceaux.query).items()}
    assert url.startswith(f"{ADRESSE}/auth/authorize?") and params["code_challenge_method"] == "S256"
    assert params["redirect_uri"] == f"{params['client_id'].rstrip('/')}/v1/maison/home-assistant/oauth/retour"
    ha.autoriser("code-accorde", params["code_challenge"])
    # Navigation du navigateur : sans jeton d'appareil
    retour = await client.get(
        "/v1/maison/home-assistant/oauth/retour",
        params={"code": "code-accorde", "state": params["state"]},
        headers={"Authorization": ""},
    )
    assert retour.status_code == 303 and retour.headers["location"] == "/#reglages/connecteurs"
    rejoue = await client.get(  # le `state` ne sert qu'une fois
        "/v1/maison/home-assistant/oauth/retour", params={"code": "code-accorde", "state": params["state"]}
    )
    assert rejoue.status_code == 400


async def test_oauth_pkce_puis_mcp(maison: dict[str, Any], pool: Base) -> None:
    client, ha, coffre = maison["client"], maison["ha"], maison["coffre"]
    await connecter_oauth(maison)
    garde = json.loads(coffre.lire(COFFRE_OAUTH))
    assert garde["refresh_token"] == "rafraichir-0"
    carte = (await client.get("/v1/maison/home-assistant")).json()
    assert carte["oauth"] is True and carte["mode"] == "mcp" and "rafraichir" not in json.dumps(carte)
    assert (await client.post("/v1/maison/home-assistant/activer", json={"actif": True})).status_code == 200

    etat = (await action(client, "ha.etat")).json()["resultat"]
    assert etat["source"] == "mcp" and "Salon" in etat["texte"]
    demande = await action(client, "ha.lumiere", entite="light.salon", nom="Salon", allumer=False)
    assert (await approuver(client, demande)).status_code == 200
    assert ha.outils[-1] == ("HassTurnOff", {"name": "Salon", "domain": ["light"]})
    assert ha.services == []  # rien par REST : pas de jeton longue durée
    # Alarme : pas d'outil MCP équivalent, repli REST exigé (et refusé avant, faute de voix du propriétaire)
    textes = [a["details"] for a in await audits_depuis(pool, maison["debut"])]
    assert not any("rafraichir-0" in t or "acces-1" in t for t in textes)


async def test_oauth_state_inconnu_et_mauvais_verifieur(maison: dict[str, Any]) -> None:
    client, ha = maison["client"], maison["ha"]
    await client.put("/v1/maison/home-assistant", json={"adresse": ADRESSE})
    inconnu = await client.get("/v1/maison/home-assistant/oauth/retour", params={"code": "x", "state": "pirate"})
    assert inconnu.status_code == 400
    url = (await client.post("/v1/maison/home-assistant/oauth")).json()["url"]
    params = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    ha.autoriser("code-vole", defi_pkce(verifieur_pkce()))  # défi d'un autre client : le vérifieur ne correspond pas
    refus = await client.get(
        "/v1/maison/home-assistant/oauth/retour", params={"code": "code-vole", "state": params["state"]}
    )
    assert refus.status_code == 400 and maison["coffre"].lire(COFFRE_OAUTH) is None


async def test_mcp_absent_repli_rest(maison: dict[str, Any]) -> None:
    client, ha = maison["client"], maison["ha"]
    ha.mcp_present = False
    corps = {"adresse": ADRESSE, "mode": "mcp", "jeton": JETON_LONGUE_DUREE}
    assert (await client.put("/v1/maison/home-assistant", json=corps)).status_code == 200
    assert (await client.post("/v1/maison/home-assistant/activer", json={"actif": True})).status_code == 200
    etat = (await action(client, "ha.etat")).json()["resultat"]
    assert etat["source"] == "rest"


# --- 🔴 : clé d'accès + voix du propriétaire -------------------------------------------------------------------------


async def test_rouge_refuse_sans_reconnaissance_du_proprietaire(maison: dict[str, Any], pool: Base) -> None:
    client, ha = maison["client"], maison["ha"]
    await configurer_rest(maison)
    refus = await action(client, "ha.serrure", entite="lock.entree", operation="ouvrir")
    assert refus.status_code == 422 and "indisponible" in refus.json()["detail"]
    assert "maison.rouge_refusee" in [a["action"] for a in await audits_depuis(pool, maison["debut"])]
    # Reconnaissance activée, voix inscrite, mais rien n'a été dit : refus aussi
    p = maison["ctx"].proprietaire
    await p.regler(actif=True)
    await p.inscrire(resultat(""))
    muet = await action(client, "ha.serrure", entite="lock.entree", operation="ouvrir")
    assert muet.status_code == 422 and "voix" in muet.json()["detail"]
    # Une autre voix que celle du propriétaire : refus
    await p.observer(resultat("Jarvis, ouvre la porte d'entrée", niveau=0.2))
    assert (await action(client, "ha.serrure", entite="lock.entree", operation="ouvrir")).status_code == 422
    assert ha.services == []


async def test_rouge_cle_d_acces_et_voix(maison: dict[str, Any], pool: Base) -> None:
    client, ha, coffre = maison["client"], maison["ha"], maison["coffre"]
    await configurer_rest(maison)
    assert (await client.put("/v1/maison/home-assistant", json={"code_alarme": "1234"})).status_code == 200
    p = maison["ctx"].proprietaire
    await p.regler(actif=True)
    await p.inscrire(resultat(""))
    await p.observer(resultat("Jarvis, ouvre la porte d'entrée"))
    demande = (await action(client, "ha.serrure", entite="lock.entree", operation="ouvrir")).json()["demande"]
    assert demande["niveau"] == "rouge" and "OUVRIR" in demande["resume"]
    clic = await client.post(f"/v1/demandes/{demande['id']}/approuver", json={})
    assert clic.status_code == 409 and "clé d'accès" in clic.json()["detail"] and ha.services == []
    cle = await enregistrer_cle(client)
    defi = (await client.post(f"/v1/demandes/{demande['id']}/options")).json()
    ok = await client.post(f"/v1/demandes/{demande['id']}/approuver", json={"credential": cle.signer(defi)})
    assert ok.status_code == 200 and ha.services == [("lock.unlock", {"entity_id": "lock.entree"})]

    # Alarme : le code vient du coffre au moment d'agir, jamais de la demande ni du journal
    await p.observer(resultat("Jarvis, désarme l'alarme"))
    alarme = (await action(client, "ha.alarme", entite="alarm_control_panel.maison", mode="desarmer")).json()
    assert "1234" not in json.dumps(alarme)
    defi = (await client.post(f"/v1/demandes/{alarme['demande']['id']}/options")).json()
    ok = await client.post(f"/v1/demandes/{alarme['demande']['id']}/approuver", json={"credential": cle.signer(defi)})
    assert ok.status_code == 200
    assert ha.services[-1] == (
        "alarm_control_panel.alarm_disarm",
        {"entity_id": "alarm_control_panel.maison", "code": "1234"},
    )
    textes = [a["details"] for a in await audits_depuis(pool, maison["debut"])]
    assert not any("1234" in t for t in textes) and coffre.lire(COFFRE_CODE_ALARME) == "1234"

    # Reconnaissance devenue indisponible entre la demande et l'approbation : l'action n'agit pas
    await p.observer(resultat("Jarvis, ouvre le portail"))
    portail = (await action(client, "ha.portail", entite="cover.portail", operation="ouvrir")).json()["demande"]
    p.empreinteur = FauxEmpreinteur(present=False)
    defi = (await client.post(f"/v1/demandes/{portail['id']}/options")).json()
    echec = await client.post(f"/v1/demandes/{portail['id']}/approuver", json={"credential": cle.signer(defi)})
    assert echec.status_code == 409 and "indisponible" in echec.json()["detail"]
    assert ha.services[-1][0] == "alarm_control_panel.alarm_disarm"


async def test_profil_d_une_autre_personne_n_est_pas_le_proprietaire(maison: dict[str, Any]) -> None:
    client = maison["client"]
    await configurer_rest(maison)
    p = maison["ctx"].proprietaire
    await p.regler(actif=True)
    await p.inscrire(resultat(""))
    await p.inscrire(resultat("", niveau=0.3), profil="ado-1234")
    await p.observer(resultat("Jarvis, ouvre le portail", niveau=0.3))
    attestation = p.attestation("ouvre le portail")
    assert attestation is not None and attestation.profil == "ado-1234"
    assert (await action(client, "ha.portail", entite="cover.portail", operation="ouvrir")).status_code == 422


# --- Fonctions pures ------------------------------------------------------------------------------------------------


def test_fonctions_pures() -> None:
    assert adresse_home_assistant("homeassistant.local:8123") == "http://homeassistant.local:8123"
    assert adresse_home_assistant("https://192.168.1.30:8123/") == "https://192.168.1.30:8123"
    assert adresse_home_assistant("http://127.0.0.1:8123") == "http://127.0.0.1:8123"
    for mauvaise in ("http://exemple.com", "http://8.8.8.8:8123", "http://u:p@192.168.1.30", "ftp://192.168.1.30"):
        with pytest.raises(ErreurHomeAssistant):
            adresse_home_assistant(mauvaise)
    v = verifieur_pkce()
    assert 43 <= len(v) <= 128 and defi_pkce(v) != v and "=" not in defi_pkce(v)
    assert niveau_entite("light.x") == "jaune" and niveau_entite("lock.x") == "rouge"
    assert niveau_entite("cover.x", {"device_class": "garage"}) == "rouge"
    assert niveau_entite("cover.x", {"device_class": "blind"}) is None and niveau_entite("climate.x") is None
