"""Phase 13, lot D : profil guidé (réponses en mémoire, privées locales, modification sans effacement, API)."""

from __future__ import annotations

from typing import Any

import pytest

from jarvis2 import memoire, profil
from jarvis2.db import Base

from .test_accueil import systeme  # noqa: F401  (fixture)
from .test_memoire import EncodeurFactice

pytestmark = pytest.mark.base


def test_questions_generiques_et_uniques() -> None:
    ids = [q.id for s in profil.SECTIONS for q in s.questions]
    assert len(ids) == len(set(ids)) == profil.TOTAL
    attendues = {"identite", "objectifs", "competences", "travail", "pensee", "passions", "valeurs"}
    attendues |= {"communication", "sante", "apprentissage", "habitudes", "projets", "rythme", "energie"}
    attendues |= {"argent", "reussites", "limites"}
    assert attendues <= set(profil.PAR_SECTION)
    assert profil.PAR_SECTION["sante"].prive and not profil.PAR_SECTION["identite"].prive


def test_texte_de_tolere_les_formats() -> None:
    assert profil.texte_de({"texte": "Bonjour", "prive": True}) == ("Bonjour", True)
    assert profil.texte_de("simple") == ("simple", False)
    assert profil.texte_de('"chaîne JSON"') == ("chaîne JSON", False)
    assert profil.texte_de(["a", "b"]) == ("a, b", False)
    assert profil.texte_de({"value": 3}) == ("3", False)


async def test_reponse_en_memoire_et_modification_sans_effacement(pool: Base) -> None:
    enc = EncodeurFactice()
    r, change = await profil.repondre(pool, "communication.ton", "Direct, avec un peu d'humour.", encodeur=enc)
    assert change and not r.prive and r.souvenir_id
    vivants = await memoire.parcourir(pool, origine="profil")
    assert len(vivants) == 1 and "humour" in vivants[0].contenu and vivants[0].confidentialite == "normal"

    # Même réponse : rien ne bouge
    _, change = await profil.repondre(pool, "communication.ton", "Direct, avec un peu d'humour.", encodeur=enc)
    assert not change

    # Modification : l'ancien souvenir est fermé, pas effacé
    r2, change = await profil.repondre(pool, "communication.ton", "Formel et bref.", encodeur=enc)
    assert change and r2.souvenir_id != r.souvenir_id
    vivants = await memoire.parcourir(pool, origine="profil")
    assert [s.contenu.endswith("Formel et bref.") for s in vivants] == [True]
    versions = await profil.historique(pool, "communication.ton")
    assert len(versions) == 2 and versions[1]["jusqu_a"] is not None and versions[0]["jusqu_a"] is None
    ferme = await pool.fetchval("SELECT valid_to FROM memoires WHERE id = $1", r.souvenir_id)
    assert ferme is not None


async def test_reponse_privee_reste_locale(pool: Base) -> None:
    r, _ = await profil.repondre(pool, "sante.attention", "Allergie aux arachides.")
    assert r.prive  # section privée par défaut
    conf = await pool.fetchval("SELECT confidentialite FROM memoires WHERE id = $1", r.souvenir_id)
    assert conf == "local_uniquement"
    # Une question ordinaire peut être rendue privée, et le reste après modification
    r, _ = await profil.repondre(pool, "identite.cadre", "En ville.", prive=True)
    r, _ = await profil.repondre(pool, "identite.cadre", "À la campagne.")
    assert r.prive
    conf = await pool.fetchval("SELECT confidentialite FROM memoires WHERE id = $1", r.souvenir_id)
    assert conf == "local_uniquement"


async def test_progression_reprise_et_heritage(pool: Base) -> None:
    await pool.execute(
        "INSERT INTO profil_reponses (question_id, reponse) VALUES ($1, $2)",
        "ancienne_question_v1",
        {"value": "Réponse v1"},
    )
    etat = profil.progression(await profil.lister(pool))
    assert etat["repondues"] == 0 and etat["heritees"] == 1
    assert etat["reprise"] == {"section": "identite", "question": "identite.appel"}
    await profil.repondre(pool, "identite.appel", "Par mon prénom, en tutoyant.")
    etat = profil.progression(await profil.lister(pool))
    assert etat["repondues"] == 1 and etat["reprise"]["question"] == "identite.presentation"
    assert etat["sections"][0]["repondues"] == 1
    with pytest.raises(profil.ErreurProfil, match="inconnue"):
        await profil.repondre(pool, "nimporte.quoi", "x")
    with pytest.raises(profil.ErreurProfil, match="vide"):
        await profil.repondre(pool, "identite.appel", "   ")
    assert await profil.retirer(pool, "identite.appel")
    assert not await profil.retirer(pool, "identite.appel")
    assert await memoire.parcourir(pool, origine="profil") == []
    assert len(await profil.historique(pool, "identite.appel")) == 1  # gardé, fermé


async def test_api_profil(systeme: dict[str, Any], pool: Base) -> None:  # noqa: F811
    client = systeme["client"]
    etat = (await client.get("/v1/profil")).json()
    assert etat["total"] == profil.TOTAL and etat["repondues"] == 0 and etat["reprise"]["section"] == "identite"
    section = (await client.get("/v1/profil/sections/argent")).json()
    assert section["prive"] and all(q["reponse"] is None for q in section["questions"])
    assert (await client.get("/v1/profil/sections/inconnue")).status_code == 404

    rep = await client.put("/v1/profil/reponses/argent.objectifs", json={"texte": "Épargner pour un voyage."})
    assert rep.status_code == 200 and rep.json()["reponse"]["prive"] and rep.json()["modifiee"]
    assert (await client.put("/v1/profil/reponses/x.y", json={"texte": "a"})).status_code == 404
    assert (await client.put("/v1/profil/reponses/argent.objectifs", json={"texte": " "})).status_code == 422

    toutes = (await client.get("/v1/profil/reponses")).json()["reponses"]
    assert [r["question_id"] for r in toutes] == ["argent.objectifs"]
    journal = await pool.fetch("SELECT details FROM audit WHERE action = 'profil.reponse'")
    assert journal and "voyage" not in str([dict(x) for x in journal])  # jamais le contenu dans l'audit
    assert (await client.delete("/v1/profil/reponses/argent.objectifs")).json() == {"retiree": "argent.objectifs"}
    assert (await client.get("/v1/profil")).json()["repondues"] == 0
