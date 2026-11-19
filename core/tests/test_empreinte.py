"""Phase 14, point B 7 : approbation liée à l'empreinte du plan exact, pile d'annulation des actions réversibles."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from jarvis2.db import Base
from jarvis2.securite import regles
from jarvis2.securite.permissions import empreinte_courte, empreinte_plan

from .test_pc import action, pc  # noqa: F401  (fixture du contrôle du PC)
from .test_securite import creer_conversation, demander, nb_audit, systeme  # noqa: F401

pytestmark = pytest.mark.base


def test_empreinte_canonique() -> None:
    a = empreinte_plan("x.y", "jaune", "Faire", {"b": 1, "a": [1.0, {"d": "é", "c": 2}]})
    b = empreinte_plan("x.y", "jaune", "Faire", {"a": [1, {"c": 2, "d": "é"}], "b": 1.0})
    assert a == b and len(a) == 64  # ordre des clés et 1.0 / 1 sans effet
    assert empreinte_plan("x.y", "jaune", "Faire", {"b": 2, "a": [1, {"c": 2, "d": "é"}]}) != a  # paramètre changé
    assert empreinte_plan("x.y", "rouge", "Faire", {"b": 1, "a": [1, {"c": 2, "d": "é"}]}) != a  # niveau changé
    assert empreinte_plan("x.y", "jaune", "Autre", {"b": 1, "a": [1, {"c": 2, "d": "é"}]}) != a  # résumé changé
    assert empreinte_courte(a) == f"{a[:4]} {a[4:8]}" and empreinte_courte(None) is None


async def test_demande_porte_son_empreinte(systeme: dict[str, Any], pool: Base) -> None:  # noqa: F811
    client = systeme["client"]
    rep = await demander(client, "conversation.archiver", await creer_conversation(pool))
    d = rep["demande"]
    assert d["empreinte"] == empreinte_plan(d["action"], d["niveau"], d["resume"], d["parametres"])
    assert d["empreinte_courte"] == f"{d['empreinte'][:4]} {d['empreinte'][4:8]}" and d["reversible"] is True
    # Sans empreinte, l'approbation n'est pas reçue
    assert (await client.post(f"/v1/demandes/{d['id']}/approuver", json={})).status_code == 422


async def test_autre_empreinte_fait_tomber_l_approbation(systeme: dict[str, Any], pool: Base) -> None:  # noqa: F811
    client = systeme["client"]
    conv = await creer_conversation(pool)
    d = (await demander(client, "conversation.archiver", conv))["demande"]
    avant = await nb_audit(pool, "demande.empreinte_invalide")
    refus = await client.post(f"/v1/demandes/{d['id']}/approuver", json={"empreinte": "0" * 64})
    assert refus.status_code == 409 and "autre plan" in refus.json()["detail"]
    assert await pool.fetchval("SELECT archivee FROM conversations WHERE id = $1::uuid", conv) is False
    assert await pool.fetchval("SELECT statut FROM demandes WHERE id = $1::uuid", d["id"]) == "echec"
    assert await nb_audit(pool, "demande.empreinte_invalide") == avant + 1
    # L'approbation est tombée : même la bonne empreinte ne la relève pas, il faut relancer l'action
    assert (
        await client.post(f"/v1/demandes/{d['id']}/approuver", json={"empreinte": d["empreinte"]})
    ).status_code == 409


async def test_plan_change_en_base_fait_tomber_l_approbation(systeme: dict[str, Any], pool: Base) -> None:  # noqa: F811
    client = systeme["client"]
    conv, autre = await creer_conversation(pool), await creer_conversation(pool)
    d = (await demander(client, "conversation.archiver", conv))["demande"]
    # Paramètres modifiés après la demande (base altérée) : ce n'est plus le plan approuvé
    await pool.execute(
        "UPDATE demandes SET parametres = $2::text::jsonb WHERE id = $1::uuid",
        d["id"],
        f'{{"conversation_id": "{autre}"}}',
    )
    refus = await client.post(f"/v1/demandes/{d['id']}/approuver", json={"empreinte": d["empreinte"]})
    assert refus.status_code == 409 and "plan enregistré a changé" in refus.json()["detail"]
    assert await pool.fetchval("SELECT archivee FROM conversations WHERE id = $1::uuid", autre) is False


async def test_demande_sans_empreinte_ne_s_approuve_plus(systeme: dict[str, Any], pool: Base) -> None:  # noqa: F811
    client = systeme["client"]
    d = (await demander(client, "conversation.archiver", await creer_conversation(pool)))["demande"]
    await pool.execute("UPDATE demandes SET empreinte = NULL WHERE id = $1::uuid", d["id"])  # d'avant la migration 025
    refus = await client.post(f"/v1/demandes/{d['id']}/approuver", json={"empreinte": d["empreinte"]})
    assert refus.status_code == 409 and "sans empreinte" in refus.json()["detail"]


async def test_annuler_une_action_reversible(systeme: dict[str, Any], pool: Base) -> None:  # noqa: F811
    client = systeme["client"]
    assert (await client.post("/v1/annulations/derniere/annuler")).status_code == 409  # rien à annuler
    conv = await creer_conversation(pool)
    d = (await demander(client, "conversation.archiver", conv))["demande"]
    fait = (await client.post(f"/v1/demandes/{d['id']}/approuver", json={"empreinte": d["empreinte"]})).json()
    assert fait["statut"] == "executee" and fait["resultat"]["annulation"]["comment"] == "Désarchiver la conversation"
    pile = (await client.get("/v1/annulations")).json()["annulations"]
    assert [e["action"] for e in pile] == ["conversation.archiver"] and pile[0]["demande_id"] == d["id"]
    avant = await nb_audit(pool, "annulation.executee")
    annule = await client.post(f"/v1/annulations/{pile[0]['id']}/annuler")
    assert annule.status_code == 200, annule.text
    assert await pool.fetchval("SELECT archivee FROM conversations WHERE id = $1::uuid", conv) is False
    assert await nb_audit(pool, "annulation.executee") == avant + 1
    assert (await client.post(f"/v1/annulations/{pile[0]['id']}/annuler")).status_code == 409  # une seule fois
    assert (await client.get("/v1/annulations")).json()["annulations"] == []


async def test_irreversible_n_entre_pas_dans_la_pile(systeme: dict[str, Any], pool: Base) -> None:  # noqa: F811
    registre = systeme["ctx"].approbations.registre
    assert registre.get("conversation.supprimer").reversible is False
    assert "archivez plutôt" in registre.get("conversation.supprimer").annulation
    # Toute action 🟡 déclare si elle s'annule et comment (ou pourquoi elle ne s'annule pas)
    assert all(a.annulation for a in registre.actions.values() if a.niveau == "jaune")
    listees = {a["nom"]: a for a in (await systeme["client"].get("/v1/actions")).json()["actions"]}
    assert listees["conversation.archiver"]["reversible"] is True and listees["memoire.archiver"]["annulation"]


async def test_retirer_une_regle_s_annule(systeme: dict[str, Any], pool: Base) -> None:  # noqa: F811
    client = systeme["client"]
    regle = await regles.ajouter(pool, "interdire", "*banque*", "Jamais la banque", "appareil:pc")
    rep = await client.post(
        "/v1/actions", json={"action": "regle.supprimer", "parametres": {"regle_id": str(regle.id)}}
    )
    d = rep.json()["demande"]
    assert (
        await client.post(f"/v1/demandes/{d['id']}/approuver", json={"empreinte": d["empreinte"]})
    ).status_code == 200
    assert await regles.obtenir(pool, regle.id) is None
    annule = (await client.post("/v1/annulations/derniere/annuler")).json()
    assert annule["statut"] == "annulee" and annule["annulation"]["action"] == "regle.supprimer"
    remise = await regles.obtenir(pool, regle.id)
    assert remise is not None and remise.motif == "*banque*" and remise.cree_le == regle.cree_le


async def approuver_pc(client: httpx.AsyncClient, corps: dict[str, Any]) -> dict[str, Any]:
    d = corps["demande"]
    r = await client.post(f"/v1/demandes/{d['id']}/approuver", json={"empreinte": d["empreinte"]})
    assert r.status_code == 200, r.text
    resultat: dict[str, Any] = r.json()["resultat"]
    return resultat


async def test_volume_et_mode_du_pc_s_annulent(pc: dict[str, Any]) -> None:  # noqa: F811
    client, pilote = pc["client"], pc["pilote"]
    assert pilote.volume == 50
    r = await approuver_pc(client, await action(client, "pc.volume", niveau=20))
    assert pilote.volume == 20 and r["avant"] == 50 and r["annulation"]["comment"] == "Remettre le volume d'avant"
    assert (await client.post("/v1/annulations/derniere/annuler")).status_code == 200
    assert pilote.volume == 50
    await approuver_pc(client, await action(client, "pc.mode", mode="concentration"))
    assert pc["pc"].etat["mode"] == "concentration"
    assert (await client.post("/v1/annulations/derniere/annuler")).status_code == 200
    assert pc["pc"].etat["mode"] == "normal"
    # Verrouiller ne s'annule pas (déverrouillage interdit par conception) : rien n'entre dans la pile
    verrou = await approuver_pc(client, await action(client, "pc.verrouiller"))
    assert "annulation" not in verrou and (await client.get("/v1/annulations")).json()["annulations"] == []
    registre = pc["ctx"].approbations.registre
    assert all(a.annulation for a in registre.actions.values() if a.niveau == "jaune")


async def test_annulation_refusee_pendant_l_arret_d_urgence(pc: dict[str, Any]) -> None:  # noqa: F811
    client, pilote = pc["client"], pc["pilote"]
    await approuver_pc(client, await action(client, "pc.volume", niveau=10))
    assert (await client.post("/v1/urgence/arreter")).status_code == 200
    assert (await client.post("/v1/annulations/derniere/annuler")).status_code in (409, 423)
    assert pilote.volume == 10
