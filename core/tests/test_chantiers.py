"""Phase 13, lot C : chantiers (sans doublon, progression, « C'est fait », abandon 🟡, suppression 🔴) et Activité."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest

from jarvis2 import chantiers
from jarvis2.db import Base

from .test_securite import nb_audit, systeme  # noqa: F401  (fixture partagée)

pytestmark = pytest.mark.base


def test_signature_meme_sens() -> None:
    assert chantiers.signature("Réparer le vélo") == chantiers.signature("vélos : RÉPARER")
    assert chantiers.signature("Ranger le garage et la cave") == chantiers.signature("cave, garage : ranger")
    assert chantiers.signature("Réparer le vélo") != chantiers.signature("Réparer la voiture")
    assert chantiers.signature("Écrire le rapport 2026") != chantiers.signature("Écrire le rapport 2025")
    assert chantiers.signature("le la les") == ""


def test_etapes_tolerantes() -> None:
    brut = ["Acheter", {"nom": "Monter", "statut": "termine"}, {"titre": "Tester", "fait": True}, {"x": 1}, 3]
    assert chantiers.lire_etapes(brut) == [
        {"titre": "Acheter", "fait": False},
        {"titre": "Monter", "fait": True},
        {"titre": "Tester", "fait": True},
    ]
    assert chantiers.lire_etapes(None) == []
    assert chantiers.progression_des_etapes(chantiers.lire_etapes(brut)) == 67


async def test_creation_sans_doublon(pool: Base) -> None:
    c1, cree1 = await chantiers.creer(pool, "Réparer le vélo", "test")
    c2, cree2 = await chantiers.creer(pool, "  vélos : réparer ", "test")
    assert cree1 and not cree2 and c1["id"] == c2["id"]
    c3, cree3 = await chantiers.creer(pool, "Réparer la voiture", "test")
    assert cree3 and c3["id"] != c1["id"]
    assert len(await chantiers.lister(pool)) == 2


async def test_creations_simultanees_un_seul_chantier(pool: Base) -> None:
    resultats = await asyncio.gather(*(chantiers.creer(pool, "Trier les photos", "test") for _ in range(5)))
    assert len({c["id"] for c, _ in resultats}) == 1
    assert sum(1 for _, cree in resultats if cree) == 1


async def test_progression_par_etapes_et_statut(pool: Base) -> None:
    c, _ = await chantiers.creer(pool, "Déménager", "test", etapes=["Cartons", "Camion", "Clés"])
    assert c["statut"] == "a_faire" and c["progression"] == 0 and c["etape_courante"] == "Cartons"
    etapes = [{"titre": "Cartons", "fait": True}, {"titre": "Camion", "fait": False}, {"titre": "Clés", "fait": False}]
    m = await chantiers.modifier(pool, UUID(c["id"]), etapes=etapes)
    assert m["progression"] == 33 and m["statut"] == "en_cours" and m["etape_courante"] == "Camion"
    m = await chantiers.modifier(pool, UUID(c["id"]), progression=80, statut="en_attente_utilisateur")
    assert m["progression"] == 80 and m["statut"] == "en_attente_utilisateur" and len(m["etapes"]) == 3


async def test_terminer_abandonne_les_jumeaux(pool: Base) -> None:
    a, _ = await chantiers.creer(pool, "Réparer le vélo", "test", etapes=["Pneu"])
    # Jumeau arrivé par l'import de JARVIS v1 (sans passer par la déduplication)
    jumeau: UUID = await pool.fetchval(
        "INSERT INTO chantiers (titre, categorie, statut, responsable, cree_par, origine)"
        " VALUES ('vélo à réparer', 'general', 'en_cours', 'jarvis', 'import', 'jarvis') RETURNING id"
    )
    fini, doublons = await chantiers.terminer(pool, UUID(a["id"]))
    assert fini["statut"] == "termine" and fini["progression"] == 100 and fini["termine_le"]
    assert all(e["fait"] for e in fini["etapes"])
    assert [d["id"] for d in doublons] == [str(jumeau)]
    j = await chantiers.obtenir(pool, jumeau)
    assert j is not None and j["statut"] == "abandonne" and j["motif"] == "Doublon de « Réparer le vélo »"
    assert await chantiers.lister(pool) == []
    assert [c["id"] for c in await chantiers.lister(pool, "termines")] == [a["id"]]
    # Rouvrir : possible (aucun jumeau ouvert), puis recréer renvoie le chantier rouvert
    r = await chantiers.rouvrir(pool, UUID(a["id"]))
    assert r["statut"] == "a_faire" and r["termine_le"] is None
    assert (await chantiers.creer(pool, "vélo réparer", "test"))[0]["id"] == a["id"]
    with pytest.raises(chantiers.ErreurChantier):
        await chantiers.rouvrir(pool, jumeau)  # le même sens est déjà ouvert : pas de doublon


async def test_clos_non_modifiable(pool: Base) -> None:
    c, _ = await chantiers.creer(pool, "Payer la taxe", "test")
    await chantiers.terminer(pool, UUID(c["id"]))
    with pytest.raises(chantiers.ErreurChantier):
        await chantiers.modifier(pool, UUID(c["id"]), progression=10)


# --- API ------------------------------------------------------------------------------------------------------


async def test_api_chantiers(systeme: dict[str, Any], pool: Base) -> None:  # noqa: F811
    client = systeme["client"]
    rep = await client.post("/v1/chantiers", json={"titre": "Écrire le guide", "etapes": [{"titre": "Plan"}]})
    assert rep.status_code == 200 and rep.json()["cree"] is True
    ident = rep.json()["chantier"]["id"]
    double = (await client.post("/v1/chantiers", json={"titre": "guide : écrire"})).json()
    assert double["cree"] is False and double["chantier"]["id"] == ident
    assert (await client.post("/v1/chantiers", json={"titre": ""})).status_code == 422

    etapes = [{"titre": "Plan", "fait": True}, {"titre": "Texte"}]
    maj = await client.patch(f"/v1/chantiers/{ident}", json={"etapes": etapes})
    assert maj.json()["progression"] == 50 and maj.json()["statut"] == "en_cours"
    assert (await client.patch(f"/v1/chantiers/{ident}", json={"statut": "termine"})).status_code == 422
    assert (await client.patch(f"/v1/chantiers/{ident}", json={"progression": 101})).status_code == 422

    liste = (await client.get("/v1/chantiers")).json()["chantiers"]
    assert [c["id"] for c in liste] == [ident]
    assert (await client.get("/v1/chantiers?statut=inconnu")).status_code == 422
    assert (await client.get("/v1/chantiers/00000000-0000-0000-0000-000000000000")).status_code == 404

    fait = (await client.post(f"/v1/chantiers/{ident}/terminer")).json()
    assert fait["chantier"]["statut"] == "termine" and fait["doublons_abandonnes"] == 0
    assert (await client.get("/v1/chantiers")).json()["chantiers"] == []
    assert await nb_audit(pool, "chantier.termine") >= 1
    assert (await client.post(f"/v1/chantiers/{ident}/rouvrir")).json()["statut"] == "a_faire"


async def test_api_abandon_jaune_et_suppression_rouge(systeme: dict[str, Any], pool: Base) -> None:  # noqa: F811
    client = systeme["client"]
    ident = (await client.post("/v1/chantiers", json={"titre": "Apprendre le piano"})).json()["chantier"]["id"]
    rep = (
        await client.post("/v1/actions", json={"action": "chantier.abandonner", "parametres": {"chantier_id": ident}})
    ).json()
    assert rep["statut"] == "en_attente" and rep["demande"]["niveau"] == "jaune"
    assert (await chantiers.obtenir(pool, UUID(ident)) or {})["statut"] == "a_faire"  # rien sans accord
    ok = (await client.post(f"/v1/demandes/{rep['demande']['id']}/approuver", json={})).json()
    assert ok["statut"] == "executee"
    assert (await chantiers.obtenir(pool, UUID(ident)) or {})["statut"] == "abandonne"

    rouge = (
        await client.post("/v1/actions", json={"action": "chantier.supprimer", "parametres": {"chantier_id": ident}})
    ).json()
    assert rouge["statut"] == "en_attente" and rouge["demande"]["niveau"] == "rouge"
    refus = await client.post(f"/v1/demandes/{rouge['demande']['id']}/approuver", json={})
    assert refus.status_code == 409 and "clé d'accès" in refus.json()["detail"]  # un clic ne suffit pas
    assert await chantiers.obtenir(pool, UUID(ident)) is not None


async def test_api_activite(systeme: dict[str, Any], pool: Base) -> None:  # noqa: F811
    client = systeme["client"]
    await client.post("/v1/chantiers", json={"titre": "Ranger le bureau"})
    await pool.execute(
        "INSERT INTO missions (type, objectif, statut, progression, acteur)"
        " VALUES ('recherche', 'Vélos', 'en_cours', 40, 't')"
    )
    await pool.execute(
        "INSERT INTO missions (type, objectif, statut, acteur, termine_le)"
        " VALUES ('revue', 'Ancienne', 'terminee', 't', now() - interval '3 days')"
        if pool.dialecte == "postgres"
        else "INSERT INTO missions (type, objectif, statut, acteur, termine_le)"
        " VALUES ('revue', 'Ancienne', 'terminee', 't', '2020-01-01T00:00:00.000000+00:00')"
    )
    await pool.execute("INSERT INTO creations (titre, version_courante, cree_par) VALUES ('Minuteur', 1, 't')")
    a = (await client.get("/v1/activite")).json()
    assert [c["titre"] for c in a["chantiers"]] == ["Ranger le bureau"]
    assert [m["objectif"] for m in a["missions"]] == ["Vélos"]  # la mission terminée il y a 3 jours n'y est plus
    assert [c["titre"] for c in a["creations"]] == ["Minuteur"]
    assert a["ateliers"] == [] and a["en_cours"] == 1
