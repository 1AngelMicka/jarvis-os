"""Lot 14 · B 10 : missions « projet » en graphe de dépendances (plan à cases, parallélisme borné, approbations)."""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import AsyncGenerator, Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from jarvis2.agents.missions import ServiceMissions
from jarvis2.agents.missions_graphe import Etape, cocher, lire_plan, ordonnancer
from jarvis2.agents.recherche_web import RechercheWeb
from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import ServiceDialogue
from jarvis2.moteurs.base import Delta, ErreurMoteur, Evenement, Fin, Message, Options, Reponse
from jarvis2.moteurs.telemetrie import EnregistreurBase, MoteurInstrumente
from jarvis2.securite import appareils
from jarvis2.securite.actions import creer_registre
from jarvis2.securite.permissions import Approbations
from jarvis2.securite.urgence import ArretUrgence

from .test_agents import systeme
from .test_connecteurs import Faux
from .test_registre_telemetrie import FauxMoteur

PLAN = """Voici le plan :

- [ ] E1 : Recenser les besoins
  Lister ce que veut l'utilisateur.
  Deux lignes de détail.
- [ ] E2 : Comparer les options
- [ ] E3 : Rédiger la synthèse (après E1, E2)
"""


class Projet(Faux):
    """Faux connecteur : brainstorm, spec, plan, puis une réponse par étape ; compte les étapes simultanées."""

    def __init__(self, ident: str, famille: str = "api", externe: bool = True, plan: str = PLAN) -> None:
        super().__init__(ident, famille, externe=externe)
        self.plan = plan
        self.duree = 0.1
        self.en_cours = 0
        self.max_simultanees = 0
        self.consignes: dict[str, str] = {}
        self.echecs: set[str] = set()

    async def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        demande = messages[-1].contenu
        etape = re.search(r"Réalise maintenant l'étape (E\d+)", demande)
        if "mène un brainstorm" in demande:
            texte = "Idées : partir léger, comparer, décider."
        elif "Rédige la spécification" in demande:
            texte = "# Spécification\nBut : un plan clair."
        elif "Découpe le projet" in demande:
            texte = self.plan
        elif etape is not None:
            ident = etape.group(1)
            self.consignes[ident] = demande
            self.en_cours += 1
            self.max_simultanees = max(self.max_simultanees, self.en_cours)
            try:
                await asyncio.sleep(self.duree)
            finally:
                self.en_cours -= 1
            if ident in self.echecs:
                raise ErreurMoteur(f"panne sur {ident}")
            texte = f"Livrable {ident} par {self.id}"
        else:
            texte = "Réponse directe à la demande."
        yield Delta(texte)
        yield Fin(Reponse(texte, f"{self.id}-1"))


async def service(
    pool: Base, tmp_path: Path, moteurs: dict[str, Faux], prives: Sequence[str] = ()
) -> tuple[ServiceMissions, ArretUrgence]:
    s = await systeme(pool, tmp_path, moteurs, prives)
    urgence = ArretUrgence()
    missions = ServiceMissions(pool, s["service"], RechercheWeb(None), urgence)
    missions.intervalle_approbation = 0.02
    return missions, urgence


async def attendre(condition: Callable[[], Any], delai: float = 5.0) -> Any:
    """Sonde `condition` (coroutine) jusqu'à une valeur vraie."""
    fin = asyncio.get_running_loop().time() + delai
    while True:
        valeur = await condition()
        if valeur:
            return valeur
        if asyncio.get_running_loop().time() > fin:
            raise AssertionError("condition jamais remplie")
        await asyncio.sleep(0.02)


def etats(m: dict[str, Any]) -> dict[str, str]:
    return {e["id"]: e["statut"] for e in m["plan"]["etapes"]}


async def nb_audit(pool: Base, action: str) -> int:
    n: int = await pool.fetchval("SELECT count(*) FROM audit WHERE action = $1", action)
    return n


# --- Lecture du plan (sans base) -----------------------------------------------------------------------------


def test_lecture_du_plan_dependances_cases_et_niveaux() -> None:
    lu = lire_plan(PLAN + "- [x] E4 : Relire (Apres E3)\nTexte libre hors plan.\n- [ ] Case sans identifiant\n")
    assert lu.erreurs == []
    assert [e.id for e in lu.etapes] == ["E1", "E2", "E3", "E4"]
    e1, e2, e3, e4 = lu.etapes
    assert e1.titre == "Recenser les besoins"
    assert e1.detail == "Lister ce que veut l'utilisateur.\nDeux lignes de détail."
    assert e2.detail == "" and e3.titre == "Rédiger la synthèse" and e3.apres == ["E1", "E2"]
    assert e4.apres == ["E3"] and e4.fait and not e1.fait  # « Apres » sans accent, casse indifférente
    assert [e.niveau for e in lu.etapes] == [0, 0, 1, 2]
    assert (lu.faites, lu.total) == (1, 4)
    assert lire_plan("Aucune case ici.").etapes == []


def test_erreurs_du_plan() -> None:
    lu = lire_plan("- [ ] E1 : A\n- [ ] E1 : B\n- [ ] E2 : C (après E9)\n")
    assert any("double" in e and "E1" in e for e in lu.erreurs)
    assert any("inconnue" in e and "E9" in e for e in lu.erreurs)
    cycle = lire_plan("- [ ] E1 : A (après E2)\n- [ ] E2 : B (après E1)\n- [ ] E3 : C (après E3)\n")
    assert any(e.startswith("Cycle") for e in cycle.erreurs)
    assert all(isinstance(e.niveau, int) for e in cycle.etapes)  # niveaux calculés malgré le cycle
    trop = lire_plan("\n".join(f"- [ ] E{i} : étape {i}" for i in range(1, 32)))
    assert any("30" in e for e in trop.erreurs)


def test_cocher_une_case() -> None:
    plan = cocher(PLAN, "E2")
    assert "- [x] E2 : Comparer les options" in plan and "- [ ] E1 :" in plan
    assert plan.replace("[x] E2", "[ ] E2") == PLAN  # le reste du texte est gardé tel quel
    assert [e.fait for e in lire_plan(plan).etapes] == [False, True, False]


@pytest.mark.parametrize("parallele", [1, 2])
async def test_ordonnanceur_borne_et_descendantes_sautees(parallele: int) -> None:
    lu = lire_plan("- [ ] E1 : a\n- [ ] E2 : b\n- [ ] E3 : c\n- [ ] E4 : d (après E2)\n- [x] E5 : e\n")
    en_cours, maxi, sautees = 0, 0, []

    async def lancer(e: Etape) -> bool:
        nonlocal en_cours, maxi
        en_cours += 1
        maxi = max(maxi, en_cours)
        await asyncio.sleep(0.03)
        en_cours -= 1
        return e.id != "E2"

    async def sauter(e: Etape) -> None:
        sautees.append(e.id)

    issues = await ordonnancer(lu.etapes, lancer, sauter, parallele)
    assert maxi == parallele
    assert issues == {"E1": True, "E2": False, "E3": True, "E4": False, "E5": True} and sautees == ["E4"]


# --- Service : préparation, exécution parallèle, cases cochées --------------------------------------------------


@pytest.mark.base
@pytest.mark.parametrize("parallele", [1, 2])
async def test_projet_prepare_puis_execute_en_parallele(pool: Base, tmp_path: Path, parallele: int) -> None:
    moteur = Projet("cle")
    missions, _ = await service(pool, tmp_path, {"cle": moteur})
    ident = await missions.lancer("projet", "Organiser un déménagement", "appareil:test", attendre=True)
    m = await missions.obtenir(ident)
    assert m is not None and m["statut"] == "en_file" and m["progression"] == 0
    plan = m["plan"]
    assert plan["phase"] == "a_valider" and plan["brainstorm"].startswith("Idées") and "Spécification" in plan["spec"]
    assert (plan["total"], plan["faites"], plan["erreurs"]) == (3, 0, [])
    assert [(e["id"], e["niveau"], e["apres"], e["statut"]) for e in plan["etapes"]] == [
        ("E1", 0, [], "a_faire"),
        ("E2", 0, [], "a_faire"),
        ("E3", 1, ["E1", "E2"], "a_faire"),
    ]
    assert moteur.consignes == {}  # rien ne s'exécute sans l'utilisateur

    assert await missions.regler(parallele) == {"parallele": parallele}
    await missions.executer_plan(ident)
    await missions.patienter(ident)
    m = await missions.obtenir(ident)
    assert m is not None and m["statut"] == "terminee" and m["progression"] == 100
    plan = m["plan"]
    assert plan["phase"] == "terminee" and plan["parallele"] == parallele and not plan["repli"]
    assert (plan["faites"], plan["total"]) == (3, 3) and plan["plan"].count("- [x] E") == 3
    assert etats(m) == {"E1": "faite", "E2": "faite", "E3": "faite"}
    e3 = plan["etapes"][2]
    assert e3["resultat"] == "Livrable E3 par cle" and e3["moteur"] == "Faux cle" and e3["debut"] and e3["fin"]
    # Parallélisme réel, borné par le réglage : E1 et E2 se chevauchent seulement avec parallele = 2
    assert moteur.max_simultanees == parallele
    # Les résultats des dépendances sont transmis comme données
    consigne = moteur.consignes["E3"]
    assert "<donnees>" in consigne and consigne.index("Livrable E1") > consigne.index("<donnees>")
    assert "Livrable E2" in consigne and "<donnees>" not in moteur.consignes["E1"]
    rapport = m["resultat"]["rapport"]
    assert "## E1 — Recenser les besoins" in rapport and "Livrable E3 par cle" in rapport
    souvenir = await pool.fetchval("SELECT source FROM memoires WHERE id = $1", m["resultat"]["souvenir_id"])
    assert souvenir == f"mission:{ident}"
    assert [x["id"] for x in await missions.lister()] == [ident]
    assert (await missions.lister())[0]["plan"]["faites"] == 3


@pytest.mark.base
async def test_etape_en_echec_saute_ses_descendantes(pool: Base, tmp_path: Path) -> None:
    moteur = Projet("cle")
    moteur.echecs = {"E1"}
    missions, _ = await service(pool, tmp_path, {"cle": moteur})
    avant = await nb_audit(pool, "mission.etape.echec")
    ident = await missions.lancer("projet", "Projet fragile", "appareil:test", attendre=True)
    await missions.executer_plan(ident)
    await missions.patienter(ident)
    m = await missions.obtenir(ident)
    assert m is not None and m["statut"] == "echec" and m["plan"]["phase"] == "echec"
    assert etats(m) == {"E1": "echec", "E2": "faite", "E3": "sautee"}
    assert "E1" in m["erreur"] and m["plan"]["faites"] == 1 and m["progression"] == 33
    assert await nb_audit(pool, "mission.etape.echec") - avant == 1


# --- Approbations ---------------------------------------------------------------------------------------------


@pytest.mark.base
async def test_etapes_approuvees_une_a_une_refus_saute_les_descendantes(pool: Base, tmp_path: Path) -> None:
    moteur = Projet("cle", plan="- [ ] E1 : Esquisse\n- [ ] E2 : Maquette (après E1)\n- [ ] E3 : Final (après E2)")
    missions, urgence = await service(pool, tmp_path, {"cle": moteur})
    approbations = Approbations(pool, creer_registre(urgence))
    missions.approbations = approbations
    pc, _ = await appareils.creer(pool, "PC", "pc")
    ident = await missions.lancer("projet", "Créer un logo", "appareil:test", attendre=True)
    await missions.executer_plan(ident)

    async def en_attente(etape: str) -> str | None:
        m = await missions.obtenir(ident)
        assert m is not None
        e = next(x for x in m["plan"]["etapes"] if x["id"] == etape)
        return e["demande_id"] if e["statut"] == "attente_approbation" else None

    demande = await attendre(lambda: en_attente("E1"))
    assert moteur.consignes == {}  # rien ne tourne avant l'approbation
    d = await approbations.obtenir(UUID(demande))
    assert d is not None and d.action == "mission.etape" and d.niveau == "jaune" and d.statut == "en_attente"
    assert d.resume == "Mission « Créer un logo » : étape E1 — Esquisse"
    assert approbations.completer(d).toujours_possible  # « Toujours autoriser » proposable
    assert (await approbations.decider(UUID(demande), pc, True, "clic"))["statut"] == "executee"
    demande2 = await attendre(lambda: en_attente("E2"))
    assert "E1" in moteur.consignes
    assert (await approbations.decider(UUID(demande2), pc, False, "clic"))["statut"] == "refusee"
    await missions.patienter(ident)
    m = await missions.obtenir(ident)
    assert m is not None and m["statut"] == "echec"
    assert etats(m) == {"E1": "faite", "E2": "refusee", "E3": "sautee"}
    e2 = m["plan"]["etapes"][1]
    assert e2["demande_id"] == demande2 and "refusée" in e2["erreur"]
    assert set(moteur.consignes) == {"E1"}


@pytest.mark.base
async def test_approbation_expiree_et_toujours_autorisee(pool: Base, tmp_path: Path) -> None:
    moteur = Projet("cle", plan="- [ ] E1 : Seule étape")
    missions, urgence = await service(pool, tmp_path, {"cle": moteur})
    approbations = Approbations(pool, creer_registre(urgence))
    missions.approbations = approbations
    pc, _ = await appareils.creer(pool, "PC", "pc")
    ident = await missions.lancer("projet", "Projet expiré", "appareil:test", attendre=True)
    await missions.executer_plan(ident)
    await attendre(lambda: pool.fetchval("SELECT count(*) FROM demandes WHERE statut = 'en_attente'"))
    await pool.execute("UPDATE demandes SET expire_le = $1", datetime.now(UTC) - timedelta(minutes=1))
    await missions.patienter(ident)
    m = await missions.obtenir(ident)
    assert m is not None and etats(m) == {"E1": "refusee"} and "expirée" in m["plan"]["etapes"][0]["erreur"]
    assert await pool.fetchval("SELECT statut FROM demandes") == "expiree"

    # « Toujours autoriser » : l'étape suivante part sans demande
    deuxieme = await missions.lancer("projet", "Projet autorisé", "appareil:test", attendre=True)
    await missions.executer_plan(deuxieme)
    demande = await attendre(
        lambda: pool.fetchval("SELECT id FROM demandes WHERE statut = 'en_attente' ORDER BY cree_le DESC LIMIT 1")
    )
    await approbations.decider(demande, pc, True, "clic", toujours=True)
    await missions.patienter(deuxieme)
    troisieme = await missions.lancer("projet", "Projet suivant", "appareil:test", attendre=True)
    nb = await pool.fetchval("SELECT count(*) FROM demandes")
    await missions.executer_plan(troisieme)
    await missions.patienter(troisieme)
    m = await missions.obtenir(troisieme)
    assert m is not None and m["statut"] == "terminee" and await pool.fetchval("SELECT count(*) FROM demandes") == nb


# --- Arrêt d'urgence ------------------------------------------------------------------------------------------


@pytest.mark.base
async def test_arret_d_urgence_annule_le_projet(pool: Base, tmp_path: Path) -> None:
    moteur = Projet("cle")
    moteur.duree = 10
    missions, urgence = await service(pool, tmp_path, {"cle": moteur})
    ident = await missions.lancer("projet", "Projet long", "appareil:test", attendre=True)
    await missions.executer_plan(ident)
    await attendre(lambda: asyncio.sleep(0, moteur.en_cours == 2))
    assert await urgence.arreter(pool, "test") >= 3  # la mission et ses deux étapes en cours
    with contextlib.suppress(asyncio.CancelledError):
        await missions.patienter(ident)
    m = await missions.obtenir(ident)
    assert m is not None and m["statut"] == "annulee" and m["plan"]["phase"] == "echec"
    assert m["plan"]["faites"] == 0 and moteur.en_cours == 0

    # Arrêt déjà actif : vérifié avant toute étape, rien ne part
    await urgence.lever(pool)
    autre = await missions.lancer("projet", "Projet suivant", "appareil:test", attendre=True)
    urgence.actif = True
    moteur.consignes.clear()
    await missions.executer_plan(autre)
    await missions.patienter(autre)
    m = await missions.obtenir(autre)
    assert m is not None and m["statut"] == "annulee" and moteur.consignes == {}


# --- Raison du choix de modèle, repli -----------------------------------------------------------------------------


@pytest.mark.base
async def test_raison_du_modele_dans_l_audit(pool: Base, tmp_path: Path) -> None:
    plan = "- [ ] E1 : Liste de courses\n- [ ] E2 : Bilan de santé"
    moteurs: dict[str, Faux] = {"cle": Projet("cle", plan=plan), "local": Projet("local", "local", False, plan)}
    missions, _ = await service(pool, tmp_path, moteurs, prives=[r"\bsant[ée]\b"])
    avant = await nb_audit(pool, "mission.etape.moteur")
    ident = await missions.lancer("projet", "Organiser la semaine", "appareil:test", attendre=True)
    await missions.executer_plan(ident)
    await missions.patienter(ident)
    lignes = await pool.fetch(
        "SELECT details FROM audit WHERE action = 'mission.etape.moteur' AND cible = $1 ORDER BY id", str(ident)
    )
    assert await nb_audit(pool, "mission.etape.moteur") - avant == 3  # préparation + deux étapes
    details = {d["details"]["etape"]: d["details"] for d in lignes}
    assert details["E2"]["raison"] == "sujet privé : IA locale seulement" and details["E2"]["moteur"] == "Faux local"
    nom = details["E1"]["moteur"]
    assert details["E1"]["raison"] == f"routeur : premier connecteur disponible ({nom})"
    m = await missions.obtenir(ident)
    assert m is not None and m["statut"] == "terminee"
    assert m["plan"]["etapes"][1]["raison"] == "sujet privé : IA locale seulement"
    assert await nb_audit(pool, "mission.etape.terminee") >= 2


@pytest.mark.base
async def test_repli_sur_la_conversation_simple(pool: Base, tmp_path: Path) -> None:
    moteur = Projet("cle", plan="Je propose de tout faire d'un coup.")
    missions, _ = await service(pool, tmp_path, {"cle": moteur})
    ident = await missions.lancer("projet", "Écrire un haïku", "appareil:test", attendre=True)
    m = await missions.obtenir(ident)
    assert m is not None and (m["plan"]["total"], m["plan"]["erreurs"]) == (0, [])
    await missions.executer_plan(ident)
    await missions.patienter(ident)
    m = await missions.obtenir(ident)
    assert m is not None and m["statut"] == "terminee" and m["plan"]["repli"] is True
    assert m["resultat"]["repli"] is True and m["resultat"]["rapport"] == "Réponse directe à la demande."
    entree = await pool.fetchval(
        "SELECT details FROM audit WHERE action = 'mission.etape.moteur' AND cible = $1 ORDER BY id DESC LIMIT 1",
        str(ident),
    )
    assert entree["repli"] is True and entree["raison"].startswith("routeur")


# --- API ------------------------------------------------------------------------------------------------------


@pytest.fixture
async def api(pool: Base) -> tuple[httpx.AsyncClient, Contexte]:
    depot = DepotConversations(pool)
    moteurs = {"faux": MoteurInstrumente(FauxMoteur(), EnregistreurBase(pool))}
    ctx = Contexte(pool, depot, moteurs, ServiceDialogue(depot, moteurs, "faux"), "faux")
    app = creer_app(Parametres(), ctx)
    app.state.ctx = ctx
    _, jeton = await appareils.creer(pool, "PC de test", "pc")
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:8765",
        headers={"Authorization": f"Bearer {jeton}"},
    )
    return client, ctx


@pytest.mark.base
async def test_routes_des_projets(api: tuple[httpx.AsyncClient, Contexte], pool: Base) -> None:
    client, ctx = api
    assert ctx.missions.approbations is ctx.approbations
    rep = await client.post("/v1/missions", json={"type": "projet", "objectif": "Organiser un voyage"})
    assert rep.status_code == 200
    ident = rep.json()["id"]
    await ctx.missions.patienter(UUID(ident))
    m = (await client.get(f"/v1/missions/{ident}")).json()
    assert m["plan"]["phase"] == "a_valider" and m["plan"]["parallele"] == 2 and m["statut"] == "en_file"
    assert (await client.get("/v1/missions")).json()["missions"][0]["plan"]["phase"] == "a_valider"

    avant = await nb_audit(pool, "mission.plan_modifie")
    cycle = {"spec": "Spec revue", "plan": "- [ ] E1 : A (après E2)\n- [ ] E2 : B (après E1)"}
    rep = await client.put(f"/v1/missions/{ident}/plan", json=cycle)
    assert rep.status_code == 200 and rep.json()["plan"]["spec"] == "Spec revue" and rep.json()["plan"]["erreurs"]
    assert await nb_audit(pool, "mission.plan_modifie") - avant == 1
    rep = await client.post(f"/v1/missions/{ident}/executer")
    assert rep.status_code == 422 and rep.json()["erreurs"][0].startswith("Cycle") and rep.json()["detail"]
    assert (await client.put(f"/v1/missions/{ident}/plan", json={"spec": "x", "plan": "y" * 20001})).status_code == 422

    assert (await client.put(f"/v1/missions/{ident}/plan", json={"spec": "", "plan": ""})).status_code == 200
    avant = await nb_audit(pool, "mission.executee")
    rep = await client.post(f"/v1/missions/{ident}/executer")
    assert rep.status_code == 200 and rep.json() == {"id": ident}
    assert await nb_audit(pool, "mission.executee") - avant == 1
    await ctx.missions.patienter(UUID(ident))
    m = (await client.get(f"/v1/missions/{ident}")).json()
    assert m["statut"] == "terminee" and m["plan"]["phase"] == "terminee" and m["plan"]["repli"] is True
    assert (await client.put(f"/v1/missions/{ident}/plan", json={"spec": "", "plan": ""})).status_code == 409
    assert (await client.post(f"/v1/missions/{ident}/executer")).status_code == 409

    inconnue = "00000000-0000-0000-0000-000000000000"
    assert (await client.put(f"/v1/missions/{inconnue}/plan", json={"spec": "", "plan": ""})).status_code == 404
    assert (await client.post(f"/v1/missions/{inconnue}/executer")).status_code == 404
    autre = (await client.post("/v1/missions", json={"type": "brainstorm", "objectif": "Des idées"})).json()["id"]
    await ctx.missions.patienter(UUID(autre))
    assert (await client.get(f"/v1/missions/{autre}")).json()["plan"] is None
    assert (await client.post(f"/v1/missions/{autre}/executer")).status_code == 409


@pytest.mark.base
async def test_reglages_des_missions(api: tuple[httpx.AsyncClient, Contexte], pool: Base) -> None:
    client, _ = api
    assert (await client.get("/v1/missions/reglages")).json() == {"parallele": 2}
    assert (await client.put("/v1/missions/reglages", json={"parallele": 0})).status_code == 422
    assert (await client.put("/v1/missions/reglages", json={"parallele": 9})).status_code == 422
    avant = await nb_audit(pool, "mission.reglages")
    rep = await client.put("/v1/missions/reglages", json={"parallele": 8})
    assert rep.status_code == 200 and rep.json() == {"parallele": 8}
    assert (await client.get("/v1/missions/reglages")).json() == {"parallele": 8}
    assert await nb_audit(pool, "mission.reglages") - avant == 1
