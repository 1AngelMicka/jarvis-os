"""Phase 13, lot I : ateliers — pause réelle, relance, choix du modèle, conflits de fichiers, clôture avec notes,
résumé de ce qui tourne dans le contexte de JARVIS."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis2.api import Contexte, creer_app
from jarvis2.ateliers import gestionnaire as module_gestionnaire
from jarvis2.ateliers.gestionnaire import ErreurAtelier, GestionnaireAteliers, Projet, git
from jarvis2.ateliers.veille import EtatSession, VeilleClaudeCode
from jarvis2.config import Parametres
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import ServiceDialogue, SourceMemoire
from jarvis2.memoire import Expurgateur, ReglagesRecherche
from jarvis2.securite import appareils
from jarvis2.securite.urgence import ArretUrgence

from .test_ateliers import FAUX, attendre_fin, depot_git
from .test_memoire import EncodeurFactice

pytestmark = pytest.mark.base


@pytest.fixture
async def ateliers(pool: Base, tmp_path: Path) -> GestionnaireAteliers:
    projet = depot_git(tmp_path / "projet")
    return GestionnaireAteliers(
        pool, [Projet("essai", "Essai", projet)], tmp_path / "ateliers", "http://127.0.0.1:1", ArretUrgence(), FAUX
    )


async def attendre_session(g: GestionnaireAteliers, ident: Any) -> None:
    for _ in range(200):
        atelier = await g.obtenir(ident)
        if atelier and atelier["session"] and ident in g.processus:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("session jamais ouverte")


async def types(g: GestionnaireAteliers, ident: Any) -> list[str]:
    return [e["type"] for e in await g.evenements(ident)]


async def test_choix_du_modele(ateliers: GestionnaireAteliers, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    args = tmp_path / "args.json"
    monkeypatch.setenv("FAUX_ATELIER_ARGS", str(args))
    a = await ateliers.creer("essai", "Avec Opus", "appareil:pc", "opus")
    assert a["modele"] == "opus"
    await ateliers.lancer(a["id"], "travail")
    await attendre_fin(ateliers, a["id"])
    vus = json.loads(args.read_text(encoding="utf-8"))
    assert vus[vus.index("--model") + 1] == "opus"
    assert (await ateliers.choisir_modele(a["id"], "claude-sonnet-5-5"))["modele"] == "claude-sonnet-5-5"
    assert (await ateliers.choisir_modele(a["id"], ""))["modele"] is None  # réglage de Claude Code
    await ateliers.lancer(a["id"], "suite", reprendre=True)
    await attendre_fin(ateliers, a["id"])
    assert "--model" not in json.loads(args.read_text(encoding="utf-8"))
    for invalide in ("opus; rm -rf /", "--dangerously-skip-permissions", "x" * 90):
        with pytest.raises(ErreurAtelier):
            await ateliers.creer("essai", "Mauvais", "appareil:pc", invalide)


async def test_relance_automatique_apres_un_plantage(
    ateliers: GestionnaireAteliers, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module_gestionnaire, "DELAI_RELANCE", 0.01)
    monkeypatch.setenv("FAUX_ATELIER_MARQUEUR", str(tmp_path / "deja-plante"))
    a = await ateliers.creer("essai", "Fragile", "appareil:pc")
    await ateliers.lancer(a["id"], "travail fragile")
    await attendre_fin(ateliers, a["id"])
    atelier = await ateliers.obtenir(a["id"])
    assert atelier is not None and atelier["statut"] == "pret" and atelier["session"] == "session-reprise"
    evenements = await ateliers.evenements(a["id"])
    erreur = next(e for e in evenements if e["type"] == "erreur")
    assert "code 1" in erreur["contenu"]["message"] and "plantage simulé" in erreur["contenu"]["journal"]
    relance = next(e for e in evenements if e["type"] == "relance")
    assert relance["contenu"] == {"automatique": True, "essai": 1}


async def test_relance_a_la_main_apres_un_echec(
    ateliers: GestionnaireAteliers, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAUX_ATELIER", "echec")
    a = await ateliers.creer("essai", "Échoue", "appareil:pc")
    with pytest.raises(ErreurAtelier, match="échec"):
        await ateliers.relancer(a["id"])  # rien à relancer : il n'a pas échoué
    await ateliers.lancer(a["id"], "objectif initial")
    await attendre_fin(ateliers, a["id"])
    assert (await ateliers.obtenir(a["id"]))["statut"] == "erreur"  # type: ignore[index]
    monkeypatch.delenv("FAUX_ATELIER")
    await ateliers.relancer(a["id"])
    await attendre_fin(ateliers, a["id"])
    atelier = await ateliers.obtenir(a["id"])
    assert atelier is not None and atelier["statut"] == "pret"
    consignes = [e["contenu"] for e in await ateliers.evenements(a["id"]) if e["type"] == "consigne"]
    assert [c["texte"] for c in consignes] == ["objectif initial", "objectif initial"] and consignes[1]["reprise"]
    assert "relance" in await types(ateliers, a["id"])


async def test_pause_reelle_puis_reprise(ateliers: GestionnaireAteliers, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAUX_ATELIER", "lent")
    a = await ateliers.creer("essai", "Long", "appareil:pc")
    await ateliers.lancer(a["id"], "travail long")
    await attendre_session(ateliers, a["id"])
    assert await ateliers.mettre_en_pause(a["id"])
    assert ateliers.en_pause(a["id"]) and not await ateliers.mettre_en_pause(a["id"])
    pause = next(e for e in await ateliers.evenements(a["id"]) if e["type"] == "pause")
    assert pause["contenu"]["suspendu"] is True  # le processus est vraiment suspendu
    assert "en pause" in await ateliers.resume()
    # En pause, une demande d'outil attend la reprise
    ateliers.jetons["jeton-pause"] = a["id"]
    demande = asyncio.create_task(ateliers.autoriser("jeton-pause", "Write", {"file_path": "a.txt"}))
    await asyncio.sleep(0.3)
    assert not demande.done()
    assert await ateliers.reprendre(a["id"]) and not ateliers.en_pause(a["id"])
    assert (await asyncio.wait_for(demande, 5))["behavior"] == "allow"
    # Pause puis arrêt : le processus suspendu est réveillé et arrêté
    assert await ateliers.mettre_en_pause(a["id"])
    assert await ateliers.arreter(a["id"])
    assert (await ateliers.obtenir(a["id"]))["statut"] == "arrete"  # type: ignore[index]
    assert not ateliers.en_pause(a["id"]) and a["id"] not in ateliers.processus


async def test_conflits_de_fichiers_puis_cloture(ateliers: GestionnaireAteliers) -> None:
    a = await ateliers.creer("essai", "Atelier A", "appareil:pc")
    b = await ateliers.creer("essai", "Atelier B", "appareil:pc")
    ateliers.jetons["ja"], ateliers.jetons["jb"] = a["id"], b["id"]
    assert (await ateliers.autoriser("ja", "Edit", {"file_path": "src/commun.py"}))["behavior"] == "allow"
    assert await ateliers.conflits() == {}
    assert (await ateliers.autoriser("jb", "Write", {"file_path": str(Path(b["chemin"]) / "src" / "commun.py")}))[
        "behavior"
    ] == "allow"
    conflits = await ateliers.conflits()
    assert conflits[str(a["id"])] == [
        {"fichier": "src/commun.py", "ateliers": [{"id": str(b["id"]), "nom": "Atelier B"}]}
    ]
    assert str(b["id"]) in conflits
    assert "conflit" in await types(ateliers, a["id"]) and "conflit" in await types(ateliers, b["id"])
    resume = await ateliers.resume()
    assert "« Atelier A »" in resume and "conflit de fichiers" in resume and "src/commun.py" in resume

    # Fichier modifié par une commande (hors Write/Edit) : git le voit après l'exécution
    (Path(a["chemin"]) / "README.md").write_text("modifié par une commande\n", encoding="utf-8")
    (Path(b["chemin"]) / "README.md").write_text("autre modification\n", encoding="utf-8")
    await ateliers.noter_fichiers_modifies(a["id"])
    nouveaux = await ateliers.noter_fichiers_modifies(b["id"])
    assert [c["fichier"] for c in nouveaux] == ["README.md"]

    # Clôture avec notes : travail commité sur la branche, worktree retiré, plus de conflit ni de résumé
    clos = await ateliers.cloturer(b["id"], "  Piste abandonnée, voir A.  ")
    assert clos["notes"] == "Piste abandonnée, voir A." and clos["clos_le"] is not None
    assert not Path(b["chemin"]).exists()
    _, log = await git(ateliers.projets["essai"].chemin, "log", "--oneline", b["branche"])
    assert "Atelier JARVIS (clôturé) : Atelier B" in log
    assert await ateliers.conflits() == {}
    assert "Atelier B" not in await ateliers.resume()
    for appel in (ateliers.lancer(b["id"], "encore"), ateliers.cloturer(b["id"], ""), ateliers.relancer(b["id"])):
        with pytest.raises(ErreurAtelier, match="clôturé"):
            await appel


async def test_routes_et_resume_dans_le_contexte(ateliers: GestionnaireAteliers, pool: Base) -> None:
    class Source:
        def lire(self) -> list[EtatSession]:
            return [
                EtatSession("s1", "Refonte", "/projets/site", "permission", "approve Bash: npm test"),
                EtatSession("s2", "Projet Interdit", "/projets/interdit", "travaille"),
            ]

    exclus = Expurgateur((re.compile("interdit", re.IGNORECASE),))
    veille = VeilleClaudeCode(pool, Source(), exclus.mentionne)
    depot = DepotConversations(pool)
    memoire = SourceMemoire(pool, EncodeurFactice(), ReglagesRecherche(expurgateur=exclus))
    service = ServiceDialogue(depot, {}, "x", memoire)
    ctx = Contexte(pool, depot, {}, service, "x", memoire, ateliers=ateliers, veille=veille)
    app = creer_app(Parametres(), ctx)
    app.state.ctx = ctx
    appareil, jeton = await appareils.creer(pool, "PC", "pc")
    entetes = {"Authorization": f"Bearer {jeton}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:8765") as client:
        rep = await client.post(
            "/v1/ateliers", json={"projet": "essai", "nom": "Interdit aussi", "modele": "haiku"}, headers=entetes
        )
        assert rep.status_code == 200 and rep.json()["modele"] == "haiku"
        ident = rep.json()["id"]
        rep = await client.post(
            "/v1/ateliers", json={"projet": "essai", "nom": "Échec", "modele": "a b"}, headers=entetes
        )
        assert rep.status_code == 409
        liste = (await client.get("/v1/ateliers", headers=entetes)).json()
        assert {m["id"] for m in liste["modeles"]} == {"sonnet", "opus", "haiku"}
        (atelier,) = liste["ateliers"]
        assert atelier["en_pause"] is False and atelier["conflits"] == [] and atelier["clos_le"] is None
        assert (await client.put(f"/v1/ateliers/{ident}/modele", json={"modele": "opus"}, headers=entetes)).json()[
            "modele"
        ] == "opus"
        assert (await client.post(f"/v1/ateliers/{ident}/pause", headers=entetes)).json() == {"fait": False}
        assert (await client.post(f"/v1/ateliers/{ident}/relancer", headers=entetes)).status_code == 409

        # Veille : désactivée par défaut, elle ne montre rien ; activée, états sans les sujets exclus
        v = (await client.get("/v1/veille-claude", headers=entetes)).json()
        assert v["reglages"]["actif"] is False and v["sessions"] == []
        await client.put("/v1/veille-claude", json={"actif": True}, headers=entetes)
        v = (await client.get("/v1/veille-claude", headers=entetes)).json()
        assert [s["id"] for s in v["sessions"]] == ["s1"] and v["sessions"][0]["etat"] == "permission"
        assert v["alertes"][0]["texte"] == "Claude Code attend votre permission dans « Refonte »."

        # Résumé de ce qui tourne, injecté dans les consignes ; les sujets exclus en sont retirés
        ateliers.jetons["j"] = atelier["id"]
        await ateliers.declarer_fichiers(atelier["id"], ["a.py"])
        consignes, _ = await service.consignes("bonjour", externe=True)
        assert "Sessions Claude Code de l'utilisateur" in consignes and "« Refonte » (site)" in consignes
        assert "interdit" not in consignes.lower()

        rep = await client.post(f"/v1/ateliers/{ident}/cloturer", json={"notes": "fini"}, headers=entetes)
        assert rep.status_code == 200 and rep.json()["notes"] == "fini"
    _ = appareil
