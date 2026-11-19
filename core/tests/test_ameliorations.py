"""Phase 13, lot O : amélioration continue — suggestion, atelier sur sa branche, aperçu (diff + tests), mise en
service 🟡 liée au contenu vu, retour arrière 🟡 au commit d'avant, arrêt d'urgence."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis2.ameliorations import ErreurAmelioration, ServiceAmeliorations
from jarvis2.api import Contexte, creer_app
from jarvis2.ateliers.gestionnaire import GestionnaireAteliers, Projet, git
from jarvis2.config import Parametres
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import ServiceDialogue
from jarvis2.pilotage import ErreurPilotage, ServicePilotage
from jarvis2.securite import appareils
from jarvis2.securite.actions import creer_registre
from jarvis2.securite.appareils import Appareil
from jarvis2.securite.permissions import Approbations, ErreurAction
from jarvis2.securite.urgence import ArretUrgence

from .test_ateliers import FAUX, attendre_fin, depot_git

pytestmark = pytest.mark.base

# Tests du projet : réussis s'il n'y a pas de fichier CASSE ; « lent » : attend (pour l'arrêt d'urgence)
TESTS = (sys.executable, "-c", "import pathlib, sys; sys.exit(1 if pathlib.Path('CASSE').exists() else 0)")
ECRIT = (sys.executable, "-c", "import pathlib; pathlib.Path('trace.txt').write_text('x')")
TESTS_LENTS = (sys.executable, "-c", "import time; time.sleep(30)")


def gestionnaire(pool: Base, tmp_path: Path, urgence: ArretUrgence, tests: tuple[str, ...] = TESTS) -> Any:
    projet = depot_git(tmp_path / "projet")
    return GestionnaireAteliers(
        pool, [Projet("essai", "Essai", projet, tests)], tmp_path / "ateliers", "http://127.0.0.1:1", urgence, FAUX
    )


@pytest.fixture
def urgence() -> ArretUrgence:
    return ArretUrgence()


@pytest.fixture
def ateliers(pool: Base, tmp_path: Path, urgence: ArretUrgence) -> GestionnaireAteliers:
    g: GestionnaireAteliers = gestionnaire(pool, tmp_path, urgence)
    return g


@pytest.fixture
def service(pool: Base, ateliers: GestionnaireAteliers, urgence: ArretUrgence) -> ServiceAmeliorations:
    return ServiceAmeliorations(pool, ateliers, urgence)


async def approuver(approbations: Approbations, appareil: Appareil, nom: str, params: dict[str, Any]) -> Any:
    demande = await approbations.demander(nom, params, appareil)
    assert demande["statut"] == "en_attente" and demande["demande"]["niveau"] == "jaune"
    assert demande["demande"]["toujours_possible"] is False  # jamais « toujours autorisé »
    return await approbations.decider(demande["demande"]["id"], appareil, True, "clic")


async def lancer_tests(service: ServiceAmeliorations, ident: Any) -> dict[str, Any]:
    await service.tester(ident)
    await service.attendre_tests(ident)
    a = await service.obtenir(ident)
    assert a is not None
    essai: dict[str, Any] = a["tests"]["atelier"]
    return essai


async def test_cycle_complet(
    service: ServiceAmeliorations, ateliers: GestionnaireAteliers, pool: Base, urgence: ArretUrgence
) -> None:
    projet = ateliers.projets["essai"].chemin
    a = await service.proposer("essai", "Ajouter un fichier", "Le projet en a besoin", "", "jarvis", "appareil:pc")
    assert a["statut"] == "proposee" and a["origine"] == "jarvis" and a["raison"] == "Le projet en a besoin"
    with pytest.raises(ErreurAmelioration, match="déjà proposée"):
        await service.proposer("essai", "ajouter un  fichier", "doublon", "", "utilisateur", "appareil:pc")
    with pytest.raises(ErreurAmelioration, match="Projet inconnu"):
        await service.proposer("autre", "X", "Y", "", "utilisateur", "appareil:pc")

    # Réalisée dans un atelier, sur sa branche : le projet n'est pas touché
    a = await service.ouvrir_atelier(a["id"], "appareil:pc", lancer=True)
    assert a["statut"] == "en_atelier" and a["atelier_id"] is not None
    await attendre_fin(ateliers, a["atelier_id"])
    _, branche = await git(projet, "branch", "--show-current")
    assert branche == "main" and not list(projet.glob("travail-*.txt"))

    # Aperçu : le fichier non commité de l'atelier apparaît, l'index de l'atelier n'est pas modifié
    vue = await service.apercu(a["id"])
    (fichier,) = vue["fichiers"]
    assert fichier["etat"] == "ajoute" and fichier["chemin"].startswith("travail-") and fichier["ajouts"]
    assert "Amélioration à réaliser : Ajouter un fichier" in vue["diff"] and vue["branche"].startswith("jarvis/")
    assert vue["tests"] == {} and vue["tests_a_jour"] is False and vue["commande_tests"]
    worktree = Path((await ateliers.obtenir(a["atelier_id"]))["chemin"])  # type: ignore[index]
    _, index = await git(worktree, "diff", "--cached", "--name-only")
    assert index == ""

    approbations = Approbations(pool, creer_registre(urgence, None, ateliers, None, service))
    appareil, _ = await appareils.creer(pool, "PC", "pc")
    with pytest.raises(ErreurAmelioration, match="tests doivent avoir réussi"):
        await service.parametres_mise_en_service(a["id"])

    # Tests en échec : mise en service refusée ; tests réussis : demande 🟡 possible
    (worktree / "CASSE").write_text("x", encoding="utf-8")
    essai = await lancer_tests(service, a["id"])
    assert essai["reussi"] is False and essai["code"] == 1 and essai["empreinte"]
    with pytest.raises(ErreurAmelioration, match="tests doivent avoir réussi"):
        await service.parametres_mise_en_service(a["id"])
    (worktree / "CASSE").unlink()
    # Des tests qui écrivent un fichier non ignoré dans l'atelier : l'essai ne vaut pas pour le contenu vu
    ateliers.projets["essai"] = Projet("essai", "Essai", projet, ECRIT)
    essai = await lancer_tests(service, a["id"])
    assert essai["reussi"] is True and essai["contenu_change"] is True and essai["empreinte"] == ""
    assert (await service.apercu(a["id"]))["tests_a_jour"] is False
    (worktree / "trace.txt").unlink()
    ateliers.projets["essai"] = Projet("essai", "Essai", projet, TESTS)
    essai = await lancer_tests(service, a["id"])
    assert essai["reussi"] is True and (await service.apercu(a["id"]))["tests_a_jour"] is True
    params = await service.parametres_mise_en_service(a["id"])

    # Le contenu change après la demande : l'approbation tombe (échec), rien n'est fusionné
    demande = await approbations.demander("amelioration.mettre_en_service", params, appareil)
    (worktree / "ajout-tardif.txt").write_text("après la demande", encoding="utf-8")
    with pytest.raises(ErreurAction, match="a changé depuis la demande"):
        await approbations.decider(demande["demande"]["id"], appareil, True, "clic")
    assert not list(projet.glob("travail-*.txt"))
    (worktree / "ajout-tardif.txt").unlink()

    # Mise en service approuvée : fusion locale, commit d'avant noté
    _, avant = await git(projet, "rev-parse", "HEAD")
    fait = await approuver(approbations, appareil, "amelioration.mettre_en_service", params)
    assert fait["statut"] == "executee" and fait["resultat"]["commit_avant"] == avant
    assert len(list(projet.glob("travail-*.txt"))) == 1
    a = await service.obtenir(a["id"])  # type: ignore[assignment]
    assert a["statut"] == "en_service" and a["commit_avant"] == avant and a["en_service_le"] is not None
    assert (await ateliers.obtenir(a["atelier_id"]))["statut"] == "fusionne"  # type: ignore[index]
    _, remotes = await git(projet, "remote")
    assert remotes == ""  # aucun push possible ni tenté

    # Retour arrière refusé sur un projet modifié, puis approuvé : retour exact à l'arbre d'avant, tests relancés
    (projet / "brouillon.txt").write_text("en cours", encoding="utf-8")
    demande = await approbations.demander("amelioration.revenir", {"amelioration_id": str(a["id"])}, appareil)
    with pytest.raises(ErreurAction, match="non commitées"):
        await approbations.decider(demande["demande"]["id"], appareil, True, "clic")
    (projet / "brouillon.txt").unlink()
    fait = await approuver(approbations, appareil, "amelioration.revenir", {"amelioration_id": str(a["id"])})
    assert fait["statut"] == "executee" and fait["resultat"]["identique_a_avant"] is True
    assert not list(projet.glob("travail-*.txt"))
    _, arbre = await git(projet, "rev-parse", "HEAD^{tree}")
    _, arbre_avant = await git(projet, "rev-parse", f"{avant}^{{tree}}")
    assert arbre == arbre_avant
    _, log = await git(projet, "log", "--oneline")
    assert "Revert" in log and "Atelier JARVIS : Ajouter un fichier" in log  # historique gardé
    await service.attendre_tests(a["id"])
    a = await service.obtenir(a["id"])  # type: ignore[assignment]
    assert a["statut"] == "retiree" and a["commit_retour"] and a["tests"]["retour"]["reussi"] is True
    with pytest.raises(ErreurAmelioration):
        await service.revenir(a["id"])  # déjà retirée


async def test_rejet_et_atelier_requis(service: ServiceAmeliorations, ateliers: GestionnaireAteliers) -> None:
    a = await service.proposer("essai", "Idée", "Pourquoi pas", "détails", "utilisateur", "appareil:pc")
    with pytest.raises(ErreurAmelioration, match="Aucun atelier"):
        await service.apercu(a["id"])
    with pytest.raises(ErreurAmelioration):
        await service.tester(a["id"])
    a = await service.ouvrir_atelier(a["id"], "appareil:pc", lancer=False)
    with pytest.raises(ErreurAmelioration, match="rien changé"):
        await service.parametres_mise_en_service(a["id"])
    a = await service.rejeter(a["id"])
    assert a["statut"] == "rejetee"
    assert (await ateliers.obtenir(a["atelier_id"]))["statut"] == "abandonne"  # type: ignore[index]
    with pytest.raises(ErreurAmelioration):
        await service.rejeter(a["id"])
    # Rejetée : la même idée peut être reproposée
    assert (await service.proposer("essai", "Idée", "Encore", "", "utilisateur", "appareil:pc"))["statut"] == "proposee"


async def test_arret_d_urgence(pool: Base, tmp_path: Path, urgence: ArretUrgence) -> None:
    ateliers = gestionnaire(pool, tmp_path, urgence, TESTS_LENTS)
    service = ServiceAmeliorations(pool, ateliers, urgence)
    a = await service.proposer("essai", "Longue", "Tests longs", "", "utilisateur", "appareil:pc")
    a = await service.ouvrir_atelier(a["id"], "appareil:pc", lancer=True)
    await attendre_fin(ateliers, a["atelier_id"])
    await service.tester(a["id"])
    for _ in range(100):  # le processus de tests a démarré
        if urgence.en_cours:
            break
        await asyncio.sleep(0.02)
    assert urgence.en_cours == 1
    await urgence.arreter(pool, "test")  # interrompt les tests en cours
    await service.attendre_tests(a["id"])
    essai = (await service.obtenir(a["id"]))["tests"]["atelier"]  # type: ignore[index]
    assert essai["reussi"] is False and "arrêt d'urgence" in essai["sortie"]
    with pytest.raises(ErreurAmelioration, match="Arrêt d'urgence"):
        await service.tester(a["id"])
    with pytest.raises(ErreurAmelioration, match="Arrêt d'urgence"):
        await service.mettre_en_service(a["id"], "x")
    with pytest.raises(ErreurAmelioration, match="Arrêt d'urgence"):
        await service.revenir(a["id"])


async def test_pilotage_propose_sans_jamais_mettre_en_service(
    pool: Base, service: ServiceAmeliorations, ateliers: GestionnaireAteliers, urgence: ArretUrgence
) -> None:
    registre = creer_registre(urgence, None, ateliers, None, service)
    pilotage = ServicePilotage(pool, lambda: dict(registre.actions), lambda: {"essai": "Essai"})
    action = await pilotage.valider(
        {"type": "proposer_amelioration", "projet": "essai", "titre": "Plus rapide", "raison": "Lent au démarrage"}
    )
    assert action["genre"] == "proposition" and action["parametres"]["raison"] == "Lent au démarrage"
    with pytest.raises(ErreurPilotage):
        await pilotage.valider({"type": "proposer_amelioration", "projet": "inconnu", "titre": "X", "raison": "Y"})
    for nom in ("amelioration.mettre_en_service", "amelioration.revenir"):
        with pytest.raises(ErreurPilotage):
            await pilotage.valider({"type": "demander_action", "action": nom, "parametres": {}})
    assert "amelioration.mettre_en_service" not in await pilotage.consignes()


async def test_routes(pool: Base, ateliers: GestionnaireAteliers) -> None:
    depot = DepotConversations(pool)
    service = ServiceDialogue(depot, {}, "x")
    ctx = Contexte(pool, depot, {}, service, "x", ateliers=ateliers)
    app = creer_app(Parametres(), ctx)
    app.state.ctx = ctx
    _, jeton = await appareils.creer(pool, "PC", "pc")
    entetes = {"Authorization": f"Bearer {jeton}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:8765") as client:
        liste = (await client.get("/v1/ameliorations", headers=entetes)).json()
        assert liste["disponible"] is True and liste["projets"][0]["id"] == "essai" and liste["ameliorations"] == []
        rep = await client.post(
            "/v1/ameliorations",
            json={"projet": "essai", "titre": "Raccourci", "raison": "Gagner du temps", "origine": "utilisateur"},
            headers=entetes,
        )
        assert rep.status_code == 200, rep.text
        ident = rep.json()["id"]
        assert (
            await client.post("/v1/ameliorations", json={"projet": "essai", "titre": "X"}, headers=entetes)
        ).status_code == 422
        assert (await client.get(f"/v1/ameliorations/{ident}/apercu", headers=entetes)).status_code == 409
        assert (await client.post(f"/v1/ameliorations/{ident}/mise-en-service", headers=entetes)).status_code == 409
        assert (await client.post(f"/v1/ameliorations/{ident}/retour", headers=entetes)).status_code == 409
        rep = await client.post(f"/v1/ameliorations/{ident}/atelier", json={"lancer": False}, headers=entetes)
        assert rep.status_code == 200 and rep.json()["statut"] == "en_atelier"
        assert (await client.get(f"/v1/ameliorations/{ident}/apercu", headers=entetes)).json()["fichiers"] == []
        actions = [r["action"] for r in await pool.fetch("SELECT action FROM audit ORDER BY id")]
        assert "amelioration.proposee" in actions and "amelioration.atelier" in actions
        # Arrêt d'urgence : toute écriture refusée
        await ctx.urgence.arreter(pool, "test")
        rep = await client.post(f"/v1/ameliorations/{ident}/rejeter", headers=entetes)
        assert rep.status_code == 423
