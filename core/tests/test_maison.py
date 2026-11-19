"""Lot 14-D17 : connecteurs maison Philips Hue et OBS (faux pont, faux OBS ; aucun appel réseau réel)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import ServiceDialogue
from jarvis2.maison import CLES, GestionnaireMaison
from jarvis2.maison.hue import ErreurHue, adresse_locale, couleur_xy, luminosite_pont, reponse_hue, requete_mdns
from jarvis2.moteurs.telemetrie import EnregistreurMemoire, MoteurInstrumente
from jarvis2.securite import appareils
from jarvis2.securite.coffre import Coffre

from .faux_maison import CLE_PONT, FauxOBS, FauxPont
from .test_securite import ORIGINE, MoteurEspion, enregistrer_cle

pytestmark = pytest.mark.base
PONT = "192.168.1.20"


@pytest.fixture
async def maison(pool: Base, tmp_path: Path) -> AsyncIterator[dict[str, Any]]:
    pont, obs = FauxPont(), FauxOBS(mot_de_passe="mot-de-passe-obs")
    await obs.demarrer()
    en_ligne: list[str] = []

    def service_signify(requete: httpx.Request) -> httpx.Response:
        en_ligne.append(str(requete.url))
        return httpx.Response(200, json=[{"id": "x", "internalipaddress": PONT}, {"internalipaddress": "8.8.8.8"}])

    async def mdns_muet() -> list[str]:
        return []

    coffre = Coffre(tmp_path / "coffre.json", chiffrement=False)
    gestion = GestionnaireMaison(
        pool,
        coffre,
        transport_hue=pont.transport(),
        decouvreur_local=mdns_muet,
        transport_en_ligne=httpx.MockTransport(service_signify),
    )
    depot = DepotConversations(pool)
    moteurs = {"espion": MoteurInstrumente(MoteurEspion(), EnregistreurMemoire())}
    ctx = Contexte(pool, depot, moteurs, ServiceDialogue(depot, moteurs, "espion"), "espion", maison=gestion)
    app = creer_app(Parametres(), ctx)
    app.state.ctx = ctx
    await gestion.charger()
    _, jeton = await appareils.creer(pool, "PC", "pc")
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGINE,
        headers={"Authorization": f"Bearer {jeton}", "Origin": ORIGINE},
    )
    try:
        yield {"client": client, "pont": pont, "obs": obs, "coffre": coffre, "en_ligne": en_ligne, "ctx": ctx}
    finally:
        await client.aclose()
        await obs.arreter()


async def action(client: httpx.AsyncClient, nom_action: str, **parametres: Any) -> httpx.Response:
    return await client.post("/v1/actions", json={"action": nom_action, "parametres": parametres})


async def approuver(client: httpx.AsyncClient, reponse: httpx.Response) -> httpx.Response:
    corps = reponse.json()
    assert corps["statut"] == "en_attente", corps
    return await client.post(
        f"/v1/demandes/{corps['demande']['id']}/approuver", json={"empreinte": corps["demande"]["empreinte"]}
    )


async def noms_actions(client: httpx.AsyncClient) -> set[str]:
    return {a["nom"] for a in (await client.get("/v1/actions")).json()["actions"]}


async def appairer_et_activer(m: dict[str, Any]) -> None:
    m["pont"].bouton = True
    assert (await m["client"].post("/v1/maison/hue/appairer", json={"adresse": PONT})).status_code == 200
    assert (await m["client"].post("/v1/maison/hue/activer", json={"actif": True})).status_code == 200


async def configurer_obs(m: dict[str, Any], mot_de_passe: str = "mot-de-passe-obs") -> None:
    corps = {"adresse": f"127.0.0.1:{m['obs'].port}", "mot_de_passe": mot_de_passe}
    assert (await m["client"].put("/v1/maison/obs", json=corps)).status_code == 200
    assert (await m["client"].post("/v1/maison/obs/activer", json={"actif": True})).status_code == 200


# --- Désactivés par défaut ----------------------------------------------------------------------------


async def test_desactives_par_defaut_et_aucun_outil_expose(maison: dict[str, Any]) -> None:
    client = maison["client"]
    etat = (await client.get("/v1/maison")).json()
    assert [c["actif"] for c in etat["connecteurs"]] == [False, False]
    assert etat["outils_actifs"] == []
    assert not {n for n in await noms_actions(client) if n.startswith(("hue.", "obs."))}
    refus = await action(client, "hue.etat")
    assert refus.status_code == 422 and "indisponible" in refus.json()["detail"]
    # Activer sans appairage ni adresse : refusé
    assert (await client.post("/v1/maison/hue/activer", json={"actif": True})).status_code == 422
    assert (await client.post("/v1/maison/obs/activer", json={"actif": True})).status_code == 422
    assert maison["pont"].appels == [] and maison["obs"].requetes == []


# --- Hue -----------------------------------------------------------------------------------------------


async def test_hue_appairage_par_bouton_cle_dans_le_coffre(maison: dict[str, Any], pool: Base) -> None:
    client = maison["client"]
    sans_bouton = await client.post("/v1/maison/hue/appairer", json={"adresse": PONT})
    assert sans_bouton.status_code == 422 and "bouton" in sans_bouton.json()["detail"]
    maison["pont"].bouton = True
    rep = await client.post("/v1/maison/hue/appairer", json={"adresse": PONT})
    assert rep.status_code == 200 and CLE_PONT not in rep.text
    assert maison["coffre"].lire(CLES["hue"]) == CLE_PONT
    carte = (await client.get("/v1/maison")).json()["connecteurs"][0]
    assert carte["secret_enregistre"] is True and carte["adresse"] == PONT and CLE_PONT not in json.dumps(carte)
    assert await pool.fetchval("SELECT count(*) FROM audit WHERE action = 'maison.hue.appaire'") == 1
    textes = [str(r["details"]) for r in await pool.fetch("SELECT details FROM audit")]
    assert not any(CLE_PONT in t for t in textes)  # la clé n'est jamais journalisée


async def test_hue_adresse_hors_reseau_local_refusee(maison: dict[str, Any]) -> None:
    maison["pont"].bouton = True
    for adresse in ("8.8.8.8", "127.0.0.1", "pont.exemple.com"):
        rep = await maison["client"].post("/v1/maison/hue/appairer", json={"adresse": adresse})
        assert rep.status_code == 422, adresse
    assert maison["pont"].appels == []


async def test_hue_etat_vert_commandes_jaunes(maison: dict[str, Any], pool: Base) -> None:
    client, pont = maison["client"], maison["pont"]
    await appairer_et_activer(maison)
    assert {"hue.etat", "hue.allumer", "hue.scene"} <= await noms_actions(client)
    assert {o["nom"] for o in (await client.get("/v1/maison")).json()["outils_actifs"]} >= {"hue.etat", "hue.couleur"}
    assert not {n for n in await noms_actions(client) if n.startswith("obs.")}  # OBS reste désactivé

    etat = (await action(client, "hue.etat")).json()  # 🟢 : exécuté tout de suite
    assert etat["statut"] == "executee"
    assert [x["nom"] for x in etat["resultat"]["lumieres"]] == ["Salon", "Bureau"]

    demande = await action(client, "hue.allumer", cible="lumiere", id="1", nom="Salon")
    assert demande.json()["demande"]["niveau"] == "jaune" and "Salon" in demande.json()["demande"]["resume"]
    assert pont.lumieres["1"]["state"]["on"] is False  # rien tant que l'utilisateur n'a pas approuvé
    assert (await approuver(client, demande)).json()["statut"] == "executee"
    assert pont.lumieres["1"]["state"]["on"] is True

    assert (await approuver(client, await action(client, "hue.luminosite", id="1", pourcent=50))).status_code == 200
    assert pont.lumieres["1"]["state"]["bri"] == 127
    rouge = await approuver(client, await action(client, "hue.couleur", cible="groupe", id="1", couleur="#ff0000"))
    assert rouge.status_code == 200 and pont.groupes["1"]["action"]["xy"] == couleur_xy("#ff0000")
    assert (await approuver(client, await action(client, "hue.eteindre", cible="groupe", id="0"))).status_code == 200
    assert pont.groupes["0"]["action"]["on"] is False
    assert (await approuver(client, await action(client, "hue.scene", scene="abc123"))).status_code == 200
    assert pont.groupes["1"]["action"]["scene"] == "abc123"
    inconnue = await approuver(client, await action(client, "hue.scene", scene="zzz"))
    assert inconnue.status_code == 409 and "inconnue" in inconnue.json()["detail"]
    assert await pool.fetchval("SELECT count(*) FROM audit WHERE action = 'hue.allumer' AND resultat = 'execute'") == 1


async def test_hue_decouverte_en_ligne_seulement_avec_accord(maison: dict[str, Any], pool: Base) -> None:
    client = maison["client"]
    assert (await client.post("/v1/maison/hue/decouvrir", json={})).json() == {"ponts": []}
    assert maison["en_ligne"] == []  # sans accord : le service de Signify n'est jamais appelé
    rep = (await client.post("/v1/maison/hue/decouvrir", json={"en_ligne": True})).json()
    assert rep == {"ponts": [PONT]}  # l'adresse publique renvoyée est écartée
    assert maison["en_ligne"] == ["https://discovery.meethue.com/"]
    assert await pool.fetchval("SELECT count(*) FROM audit WHERE action = 'maison.hue.decouverte_en_ligne'") == 1


async def test_desactivation_bloque_une_demande_deja_creee(maison: dict[str, Any]) -> None:
    client, pont = maison["client"], maison["pont"]
    await appairer_et_activer(maison)
    demande = await action(client, "hue.allumer", id="1")
    assert (await client.post("/v1/maison/hue/activer", json={"actif": False})).status_code == 200
    refus = await approuver(client, demande)
    assert refus.status_code == 409 and "désactivé" in refus.json()["detail"]
    assert pont.lumieres["1"]["state"]["on"] is False
    assert "hue.etat" not in await noms_actions(client)


async def test_arret_d_urgence_bloque_les_commandes_maison(maison: dict[str, Any]) -> None:
    client, pont = maison["client"], maison["pont"]
    await appairer_et_activer(maison)
    demande = await action(client, "hue.allumer", id="1")
    await client.post("/v1/urgence/arreter")
    assert (await action(client, "hue.allumer", id="2")).status_code == 423  # aucune nouvelle demande
    assert (await client.post("/v1/maison/hue/activer", json={"actif": False})).status_code == 423
    refus = await approuver(client, demande)  # approuver reste permis pendant l'arrêt… mais n'agit pas
    assert refus.status_code == 409 and "urgence" in refus.json()["detail"]
    assert pont.lumieres["1"]["state"]["on"] is False


async def test_oublier_retire_la_cle_et_desactive(maison: dict[str, Any]) -> None:
    await appairer_et_activer(maison)
    assert (await maison["client"].delete("/v1/maison/hue")).status_code == 200
    assert maison["coffre"].lire(CLES["hue"]) is None
    carte = (await maison["client"].get("/v1/maison")).json()["connecteurs"][0]
    assert carte["actif"] is False and carte["adresse"] is None


# --- OBS -----------------------------------------------------------------------------------------------


async def test_obs_etat_scene_et_enregistrement(maison: dict[str, Any], pool: Base) -> None:
    client, obs = maison["client"], maison["obs"]
    await configurer_obs(maison)
    assert maison["coffre"].lire(CLES["obs"]) == "mot-de-passe-obs"
    assert "mot-de-passe-obs" not in (await client.get("/v1/maison")).text
    test = (await client.post("/v1/maison/obs/tester")).json()
    assert test["disponible"] is True and "Caméra" in test["detail"]

    etat = (await action(client, "obs.etat")).json()["resultat"]
    assert etat == {"scene": "Caméra", "scenes": ["Caméra", "Écran", "Pause"], "enregistrement": False, "direct": False}

    demande = await action(client, "obs.scene", scene="Écran")
    assert demande.json()["demande"]["niveau"] == "jaune" and obs.scene == "Caméra"
    assert (await approuver(client, demande)).status_code == 200 and obs.scene == "Écran"
    inconnue = await approuver(client, await action(client, "obs.scene", scene="Nulle part"))
    assert inconnue.status_code == 409 and obs.scene == "Écran"

    assert (await approuver(client, await action(client, "obs.enregistrement", demarrer=True))).status_code == 200
    assert obs.enregistrement is True
    assert (await approuver(client, await action(client, "obs.enregistrement", demarrer=False))).status_code == 200
    assert obs.enregistrement is False
    textes = [str(r["details"]) for r in await pool.fetch("SELECT details FROM audit")]
    assert not any("mot-de-passe-obs" in t for t in textes)


async def test_obs_direct_rouge_exige_une_cle_d_acces(maison: dict[str, Any]) -> None:
    client, obs = maison["client"], maison["obs"]
    await configurer_obs(maison)
    demande = (await action(client, "obs.direct.demarrer")).json()["demande"]
    assert demande["niveau"] == "rouge"
    clic = await client.post(f"/v1/demandes/{demande['id']}/approuver", json={"empreinte": demande["empreinte"]})
    assert clic.status_code == 409 and "clé d'accès" in clic.json()["detail"] and obs.direct is False
    cle = await enregistrer_cle(client)
    defi = (await client.post(f"/v1/demandes/{demande['id']}/options")).json()
    ok = await client.post(
        f"/v1/demandes/{demande['id']}/approuver",
        json={"empreinte": demande["empreinte"], "credential": cle.signer(defi)},
    )
    assert ok.status_code == 200 and obs.direct is True
    assert (await approuver(client, await action(client, "obs.direct.arreter"))).status_code == 200  # 🟡
    assert obs.direct is False


async def test_obs_mauvais_mot_de_passe(maison: dict[str, Any]) -> None:
    await configurer_obs(maison, mot_de_passe="faux")
    test = (await maison["client"].post("/v1/maison/obs/tester")).json()
    assert test == {"disponible": False, "detail": "Mot de passe OBS refusé"}
    assert maison["obs"].requetes == []


async def test_obs_adresse_publique_refusee(maison: dict[str, Any]) -> None:
    rep = await maison["client"].put("/v1/maison/obs", json={"adresse": "93.184.216.34:4455"})
    assert rep.status_code == 422


# --- Fonctions pures -----------------------------------------------------------------------------------


def test_outils_purs() -> None:
    assert adresse_locale("192.168.1.20") == "192.168.1.20"
    assert adresse_locale("10.0.0.5:8443") == "10.0.0.5:8443"
    assert adresse_locale("127.0.0.1:4455", boucle=True) == "127.0.0.1:4455"
    for mauvaise in (
        "8.8.8.8",
        "0.0.0.0",  # noqa: S104
        "exemple.com",
        "192.168.1.2:99999",
    ):
        with pytest.raises(ErreurHue):
            adresse_locale(mauvaise)
    assert couleur_xy("#FFFFFF") == pytest.approx([0.3227, 0.329], abs=0.01)
    assert couleur_xy("ff0000")[0] > 0.6
    with pytest.raises(ErreurHue):
        couleur_xy("rouge")
    assert luminosite_pont(100) == 254 and luminosite_pont(1) == 3
    with pytest.raises(ErreurHue):
        luminosite_pont(0)
    question = requete_mdns()
    assert b"\x04_hue\x04_tcp\x05local\x00" in question and not reponse_hue(question)  # une question, pas une réponse
    assert reponse_hue(b"\x00\x00\x84\x00" + b"\x00" * 8 + b"\x04_hue\x04_tcp\x05local\x00")


async def test_hue_et_obs_s_annulent(maison: dict[str, Any]) -> None:
    """Pile d'annulation (point B 7) : la lampe revient à son état d'avant, OBS à sa scène d'avant."""
    client, pont, obs = maison["client"], maison["pont"], maison["obs"]
    await appairer_et_activer(maison)
    pont.lumieres["1"]["state"].update(on=True, bri=200)
    assert (await approuver(client, await action(client, "hue.luminosite", id="1", pourcent=10))).status_code == 200
    assert pont.lumieres["1"]["state"]["bri"] != 200
    assert (await client.post("/v1/annulations/derniere/annuler")).status_code == 200
    assert pont.lumieres["1"]["state"]["on"] is True and pont.lumieres["1"]["state"]["bri"] == 200

    await configurer_obs(maison)
    assert (await approuver(client, await action(client, "obs.scene", scene="Écran"))).status_code == 200
    pile = (await client.get("/v1/annulations")).json()["annulations"]
    assert pile[0]["action"] == "obs.scene" and pile[0]["comment"] == "Revenir à la scène OBS d'avant"
    assert (await client.post(f"/v1/annulations/{pile[0]['id']}/annuler")).status_code == 200
    assert obs.scene == "Caméra"
