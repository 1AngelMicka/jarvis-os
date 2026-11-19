"""Point 14 · B 9 : ateliers dans un vrai bac à sable (faux lanceurs : aucune commande réelle, ni Docker ni
Windows Sandbox)."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import shlex
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
import pytest

from jarvis2.api import Contexte, creer_app
from jarvis2.ateliers.bac_a_sable import (
    Bac,
    Detecteur,
    RefusBacASable,
    choisir,
    commande_reecrite,
    envelopper,
    executer_wsb,
    fichier_wsb,
    profil_sandbox_exec,
)
from jarvis2.ateliers.gestionnaire import ErreurAtelier, GestionnaireAteliers, Projet
from jarvis2.config import Parametres
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import ServiceDialogue
from jarvis2.securite import appareils
from jarvis2.securite.urgence import ArretUrgence

from .faux_bac import FauxLanceur, detecteur_disponible, lanceur_docker
from .test_ateliers import FAUX, attendre_fin, depot_git

EXE_WSB = r"C:\Windows\System32\WindowsSandbox.exe"


def _par_id(bacs: list[Bac]) -> dict[str, Bac]:
    return {b.id: b for b in bacs}


# --- Détection -----------------------------------------------------------------------------------------------------


async def test_detection_linux_docker_en_marche_et_bwrap() -> None:
    lanceur = lanceur_docker()
    lanceur.outils.add("bwrap")
    bacs = _par_id(await Detecteur(lanceur, plateforme="linux").detecter())
    assert list(bacs) == ["docker", "podman", "windows_sandbox", "bubblewrap", "sandbox_exec"]
    assert bacs["docker"].disponible and "en marche" in bacs["docker"].raison
    assert not bacs["podman"].disponible and "non installé" in bacs["podman"].raison
    assert not bacs["windows_sandbox"].disponible and bacs["windows_sandbox"].raison == "réservé à Windows"
    assert bacs["bubblewrap"].disponible
    assert not bacs["sandbox_exec"].disponible and bacs["sandbox_exec"].raison == "réservé à macOS"
    # Sondes en lecture seule : jamais `docker start`, `pull` ni `run`
    assert [a[:2] for a in lanceur.appels] == [["docker", "info"], ["docker", "image"]]


async def test_docker_arrete_n_est_jamais_demarre() -> None:
    lanceur = lanceur_docker(en_marche=False)
    docker = _par_id(await Detecteur(lanceur, plateforme="linux").detecter())["docker"]
    assert not docker.disponible and docker.raison == "Docker est arrêté : JARVIS ne le démarre jamais"
    assert lanceur.appels == [["docker", "info", "--format", "{{.ServerVersion}}"]]  # pas d'inspection d'image


async def test_image_absente_rien_n_est_telecharge() -> None:
    lanceur = lanceur_docker(image=False)
    docker = _par_id(await Detecteur(lanceur, plateforme="linux", image="python:3.13-slim").detecter())["docker"]
    assert not docker.disponible
    assert docker.raison == "image python:3.13-slim absente : `docker pull python:3.13-slim` à faire vous-même"
    assert not any("pull" in a for appel in lanceur.appels for a in appel)


async def test_podman_seul() -> None:
    lanceur = FauxLanceur(outils=["podman"], codes={"podman info": (0, "5.0"), "podman image inspect": (0, "")})
    bacs = await Detecteur(lanceur, plateforme="linux").detecter()
    assert choisir("auto", bacs) == _par_id(bacs)["podman"]


async def test_windows_sandbox_present_ou_non_active() -> None:
    present = Detecteur(FauxLanceur(fichiers=[EXE_WSB]), plateforme="win32", racine_systeme=r"C:\Windows")
    bacs = _par_id(await present.detecter())
    assert bacs["windows_sandbox"].disponible
    assert bacs["bubblewrap"].raison == "réservé à Linux"
    absent = Detecteur(FauxLanceur(), plateforme="win32", racine_systeme=r"C:\Windows")
    wsb = _par_id(await absent.detecter())["windows_sandbox"]
    assert not wsb.disponible and wsb.raison == "fonctionnalité Windows Sandbox non activée (JARVIS ne l'active pas)"


async def test_sandbox_exec_macos() -> None:
    bacs = _par_id(await Detecteur(FauxLanceur(outils=["sandbox-exec"]), plateforme="darwin").detecter())
    assert bacs["sandbox_exec"].disponible
    assert bacs["windows_sandbox"].raison == "réservé à Windows"
    sans = _par_id(await Detecteur(FauxLanceur(), plateforme="darwin").detecter())["sandbox_exec"]
    assert not sans.disponible and "sandbox-exec" in sans.raison


async def test_detection_en_cache_sauf_rafraichir() -> None:
    lanceur = lanceur_docker()
    d = Detecteur(lanceur, plateforme="linux")
    await d.detecter()
    await d.detecter()
    assert len(lanceur.appels) == 2
    lanceur.codes["docker info"] = (1, "arrêté")
    assert _par_id(await d.detecter())["docker"].disponible  # cache
    assert not _par_id(await d.detecter(rafraichir=True))["docker"].disponible


# --- Choix ---------------------------------------------------------------------------------------------------------


def _bacs(**disponibles: bool) -> list[Bac]:
    return [
        Bac(t, t.capitalize(), disponibles.get(t, False), f"raison {t}") for t in ("docker", "podman", "bubblewrap")
    ]


def test_choix_auto_explicite_aucun() -> None:
    assert choisir("auto", _bacs(docker=True, podman=True)).id == "docker"  # type: ignore[union-attr]
    assert choisir("auto", _bacs(podman=True)).id == "podman"  # type: ignore[union-attr]
    assert choisir("podman", _bacs(docker=True, podman=True)).id == "podman"  # type: ignore[union-attr]
    assert choisir("aucun", _bacs()) is None
    assert choisir("aucun", _bacs(docker=True)) is None


def test_refus_sans_repli() -> None:
    with pytest.raises(RefusBacASable) as refus:
        choisir("auto", _bacs())
    texte = str(refus.value)
    assert "aucun repli silencieux" in texte.lower() and "sans bac à sable" in texte
    assert all(f"raison {t}" in texte for t in ("docker", "podman", "bubblewrap"))
    # Type explicite indisponible : refus, même si un autre bac est disponible
    with pytest.raises(RefusBacASable, match="raison podman"):
        choisir("podman", _bacs(docker=True))
    with pytest.raises(ValueError):
        choisir("chroot", _bacs(docker=True))


# --- Enveloppes ----------------------------------------------------------------------------------------------------


def test_enveloppe_docker_reseau_coupe_seul_le_worktree(tmp_path: Path) -> None:
    args = envelopper("docker", "pytest -q && echo ok", tmp_path, "python:3.13-slim")
    assert args[:2] == ["docker", "run"]
    assert args[args.index("--network") + 1] == "none" and args[args.index("--pull") + 1] == "never"
    assert args[args.index("--cap-drop") + 1] == "ALL" and "no-new-privileges" in args
    assert args.count("-v") == 1 and args[args.index("-v") + 1] == f"{tmp_path}:/atelier"
    assert args[-4:] == ["python:3.13-slim", "sh", "-c", "pytest -q && echo ok"]
    ligne = commande_reecrite(args, "linux")
    assert shlex.split(ligne) == args
    assert commande_reecrite(args, "win32").startswith("MSYS_NO_PATHCONV=1 docker run")
    assert envelopper("podman", "ls", tmp_path)[0] == "podman"


def test_enveloppe_bubblewrap_et_sandbox_exec(tmp_path: Path) -> None:
    args = envelopper("bubblewrap", "make", tmp_path)
    assert args[0] == "bwrap" and "--unshare-all" in args and "--die-with-parent" in args
    i = args.index("--bind")
    assert args.count("--bind") == 1 and args[i + 1] == args[i + 2] == str(tmp_path)  # seul montage en écriture
    assert args[-3:] == ["sh", "-c", "make"]
    piege = PurePosixPath('/tmp/a"b\\c')
    profil = profil_sandbox_exec(piege)
    assert "(deny network*)" in profil and '(subpath "/tmp/a\\"b\\\\c")' in profil
    args = envelopper("sandbox_exec", "make", tmp_path)
    assert args[:2] == ["sandbox-exec", "-p"] and args[-3:] == ["sh", "-c", "make"]
    with pytest.raises(ValueError):
        envelopper("docker", "  ", tmp_path)


def _commande_du_wsb(xml: str) -> str:
    racine = ET.fromstring(xml)  # noqa: S314  (XML produit par JARVIS)
    lancement = racine.findtext("LogonCommand/Command") or ""
    script = base64.b64decode(lancement.split("-EncodedCommand ", 1)[1]).decode("utf-16-le")
    code64 = re.search(r"FromBase64String\('([A-Za-z0-9+/=]*)'\)", script)
    assert code64 is not None
    return base64.b64decode(code64.group(1)).decode("utf-8")


def test_fichier_wsb_isole_et_echappe() -> None:
    worktree = Path(r"C:\ateliers\a&b<c>")
    piege = (
        "echo </Command></LogonCommand><MappedFolders><MappedFolder><HostFolder>C:\\</HostFolder> & del /q * \"'%PATH%"
    )
    xml = fichier_wsb(worktree, piege, "abc123")
    racine = ET.fromstring(xml)  # noqa: S314  XML valide malgré la commande piégée
    for cle in ("Networking", "ClipboardRedirection", "PrinterRedirection", "AudioInput", "VideoInput", "vGPU"):
        assert racine.findtext(cle) == "Disable", cle
    assert racine.findtext("ProtectedClient") == "Enable"
    (dossier,) = racine.findall("MappedFolders/MappedFolder")  # un seul dossier partagé
    assert len(racine.findall(".//MappedFolder")) == 1
    assert dossier.findtext("HostFolder") == str(worktree)
    assert dossier.findtext("SandboxFolder") == r"C:\atelier" and dossier.findtext("ReadOnly") == "false"
    assert "del /q" not in xml and "&amp;" in xml  # la commande n'apparaît qu'encodée
    assert _commande_du_wsb(xml) == piege
    with pytest.raises(ValueError):
        fichier_wsb(worktree, "dir", "../x")


def test_enveloppe_windows_sandbox_hors_du_worktree(tmp_path: Path) -> None:
    worktree, dossier = tmp_path / "wt", tmp_path / "bac-a-sable"
    worktree.mkdir()
    args = envelopper("windows_sandbox", "python -m pytest", worktree, dossier_wsb=dossier, ident="cafe01")
    assert args == [
        sys.executable,
        "-I",
        "-m",
        "jarvis2",
        "bac-a-sable-wsb",
        str(dossier / "cafe01.wsb"),
        str(worktree),
        "cafe01",
    ]
    assert _commande_du_wsb((dossier / "cafe01.wsb").read_text(encoding="utf-8")) == "python -m pytest"
    assert not list(worktree.iterdir())  # rien d'écrit dans le worktree
    with pytest.raises(ValueError, match="trop longue"):
        envelopper("windows_sandbox", "x" * 9000, worktree, dossier_wsb=dossier)


# --- Exécution dans Windows Sandbox (faux lanceur, sans attente réelle) ---------------------------------------------


async def test_runner_wsb_attend_le_code_affiche_et_nettoie(tmp_path: Path) -> None:
    worktree, wsb = tmp_path / "wt", tmp_path / "c.wsb"
    worktree.mkdir()
    wsb.write_text("<Configuration/>", encoding="utf-8")
    lanceur = FauxLanceur(disque=True, codes={EXE_WSB: (0, "")})
    tours: list[float] = []

    async def dormir(s: float) -> None:
        tours.append(s)
        await asyncio.sleep(0)
        if len(tours) == 2:  # le bac a fini : sortie et code écrits dans le dossier partagé
            (worktree / ".jarvis-bac").mkdir()
            (worktree / ".jarvis-bac" / "id1.sortie").write_text("3 passed", encoding="utf-8")
            (worktree / ".jarvis-bac" / "id1.code").write_text("\ufeff3\r\n", encoding="utf-8")

    sorties: list[str] = []
    code = await executer_wsb(
        wsb, worktree, "id1", lanceur, Path(EXE_WSB), sondage=1.0, dormir=dormir, ecrire=sorties.append
    )
    assert code == 3 and sorties == ["3 passed"] and lanceur.appels == [[EXE_WSB, str(wsb)]]
    assert not wsb.exists() and not (worktree / ".jarvis-bac").exists()


async def test_runner_wsb_delai_et_echec_du_lancement(tmp_path: Path) -> None:
    wsb = tmp_path / "c.wsb"
    wsb.write_text("x", encoding="utf-8")

    async def dormir(_: float) -> None:
        await asyncio.sleep(0)

    sorties: list[str] = []
    lanceur = FauxLanceur(disque=True, codes={EXE_WSB: (0, "")})
    code = await executer_wsb(
        wsb, tmp_path, "id2", lanceur, Path(EXE_WSB), delai=3, dormir=dormir, ecrire=sorties.append
    )
    assert code == 124 and "Délai dépassé" in sorties[-1] and not wsb.exists()
    wsb.write_text("x", encoding="utf-8")
    lanceur = FauxLanceur(disque=True, codes={EXE_WSB: (5, "désactivé")})
    code = await executer_wsb(
        wsb, tmp_path, "id3", lanceur, Path(EXE_WSB), delai=3, dormir=dormir, ecrire=sorties.append
    )
    assert code == 5 and "n'a pas démarré" in sorties[-1]


# --- Gestionnaire -------------------------------------------------------------------------------------------------


def _gestionnaire(pool: Base, tmp_path: Path, detecteur: Detecteur) -> GestionnaireAteliers:
    projet = depot_git(tmp_path / "projet")
    return GestionnaireAteliers(
        pool,
        [Projet("essai", "Essai", projet)],
        tmp_path / "ateliers",
        "http://127.0.0.1:1",
        ArretUrgence(),
        FAUX,
        detecteur=detecteur,
    )


async def _evenements(g: GestionnaireAteliers, ident: Any) -> list[tuple[str, dict[str, Any]]]:
    return [
        (e["type"], json.loads(e["contenu"]) if isinstance(e["contenu"], str) else e["contenu"])
        for e in await g.evenements(ident)
    ]


async def _accorder(g: GestionnaireAteliers, ident: Any, appel: Any) -> dict[str, Any]:
    tache = asyncio.ensure_future(appel)
    for _ in range(100):
        if g.en_attente(ident) or tache.done():
            break
        await asyncio.sleep(0.02)
    for attente in g.en_attente(ident):
        g.repondre(attente["id"], True)
    resultat: dict[str, Any] = await tache
    return resultat


@pytest.mark.base
async def test_lancer_refuse_sans_bac_disponible(pool: Base, tmp_path: Path) -> None:
    g = _gestionnaire(pool, tmp_path, Detecteur(FauxLanceur(), plateforme="linux"))
    a = await g.creer("essai", "Essai", "appareil:pc")
    assert a["bac_a_sable"] == "auto"
    with pytest.raises(ErreurAtelier, match="Aucun bac à sable disponible"):
        await g.lancer(a["id"], "travail")
    assert a["id"] not in g.taches and (await g.obtenir(a["id"]))["statut"] == "pret"  # type: ignore[index]
    evenements = await _evenements(g, a["id"])
    assert [t for t, _ in evenements] == ["cree", "bac_a_sable_refuse"]
    assert "aucun repli silencieux" in evenements[-1][1]["raison"].lower()
    # « Sans bac à sable », choisi explicitement : l'atelier se lance, et c'est noté
    await g.choisir_bac(a["id"], "aucun")
    await g.lancer(a["id"], "travail")
    await attendre_fin(g, a["id"])
    evenements = await _evenements(g, a["id"])
    consigne = next(c for t, c in evenements if t == "consigne")
    assert consigne["bac"] is None and "sans_bac_a_sable" in [t for t, _ in evenements]
    with pytest.raises(ErreurAtelier):
        await g.choisir_bac(a["id"], "chroot")


@pytest.mark.base
async def test_bash_reecrit_web_refuse_bac_devenu_indisponible(pool: Base, tmp_path: Path) -> None:
    detecteur = detecteur_disponible()
    g = _gestionnaire(pool, tmp_path, detecteur)
    a = await g.creer("essai", "Essai", "appareil:pc", bac_a_sable="docker")
    await g.lancer(a["id"], "travail")
    await attendre_fin(g, a["id"])
    consigne = next(c for t, c in await _evenements(g, a["id"]) if t == "consigne")
    assert consigne["bac"] == "docker"

    # Exécution en cours (simulée) dans Docker
    g.jetons["j"] = a["id"]
    g.bacs[a["id"]] = "docker"
    reponse = await _accorder(g, a["id"], g.autoriser("j", "Bash", {"command": "pytest -q", "timeout": 5}))
    assert reponse["behavior"] == "allow" and reponse["updatedInput"]["timeout"] == 5
    commande = reponse["updatedInput"]["command"]
    args = shlex.split(commande.removeprefix("MSYS_NO_PATHCONV=1 "))
    assert args[:2] == ["docker", "run"] and args[args.index("--network") + 1] == "none"
    assert args[args.index("-v") + 1] == f"{a['chemin']}:/atelier" and args[-1] == "pytest -q"

    web = await g.autoriser("j", "WebFetch", {"url": "https://exemple.org"})
    assert web["behavior"] == "deny" and "réseau coupé" in web["message"] and not g.en_attente(a["id"])
    assert (await g.autoriser("j", "WebSearch", {"query": "x"}))["behavior"] == "deny"
    # L'écriture dans le worktree reste accordée par decider
    assert (await g.autoriser("j", "Write", {"file_path": "ok.txt", "content": "x"}))["behavior"] == "allow"

    # Docker s'arrête : la commande accordée est refusée, jamais exécutée hors du bac
    detecteur.lanceur.codes["docker info"] = (1, "arrêté")  # type: ignore[attr-defined]
    await detecteur.detecter(rafraichir=True)
    refus = await _accorder(g, a["id"], g.autoriser("j", "Bash", {"command": "pytest -q"}))
    assert refus["behavior"] == "deny" and "arrêté" in refus["message"] and "updatedInput" not in refus
    autorisations = [c for t, c in await _evenements(g, a["id"]) if t == "autorisation"]
    assert all(c["bac"] == "docker" for c in autorisations)
    assert [c["verdict"] for c in autorisations if c["outil"] == "Bash"] == ["allow", "deny"]


@pytest.mark.base
async def test_routes_bac_a_sable(pool: Base, tmp_path: Path) -> None:
    g = _gestionnaire(pool, tmp_path, detecteur_disponible())
    depot = DepotConversations(pool)
    ctx = Contexte(pool, depot, {}, ServiceDialogue(depot, {}, "x"), "x", ateliers=g)
    app = creer_app(Parametres(), ctx)
    app.state.ctx = ctx
    _, jeton = await appareils.creer(pool, "PC", "pc")
    entetes = {"Authorization": f"Bearer {jeton}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:8765") as client:
        bacs = (await client.get("/v1/ateliers/bacs-a-sable?rafraichir=true", headers=entetes)).json()["bacs"]
        assert bacs[0] == {"id": "docker", "nom": "Docker", "disponible": True, "raison": bacs[0]["raison"]}
        assert {b["id"] for b in bacs} == {"docker", "podman", "windows_sandbox", "bubblewrap", "sandbox_exec"}

        rep = await client.post(
            "/v1/ateliers", json={"projet": "essai", "nom": "Sans bac", "bac_a_sable": "aucun"}, headers=entetes
        )
        assert rep.status_code == 409 and "confirmation explicite" in rep.json()["detail"]
        rep = await client.post(
            "/v1/ateliers",
            json={"projet": "essai", "nom": "Sans bac", "bac_a_sable": "aucun", "confirmer_sans_bac": True},
            headers=entetes,
        )
        assert rep.status_code == 200 and rep.json()["bac_a_sable"] == "aucun"
        sans = rep.json()["id"]
        rep = await client.post("/v1/ateliers", json={"projet": "essai", "nom": "Auto"}, headers=entetes)
        assert rep.status_code == 200 and rep.json()["bac_a_sable"] == "auto"
        ident = rep.json()["id"]

        liste = (await client.get("/v1/ateliers", headers=entetes)).json()
        assert liste["bacs"][0]["id"] == "docker"
        par_id = {x["id"]: x for x in liste["ateliers"]}
        assert par_id[ident]["bac"] == {"effectif": "docker", "refus": None}
        assert par_id[sans]["bac"] == {"effectif": None, "refus": None}

        url = f"/v1/ateliers/{ident}/bac-a-sable"
        rep = await client.put(url, json={"choix": "aucun"}, headers=entetes)
        assert rep.status_code == 409 and rep.json()["detail"] == "Sans bac à sable : confirmation explicite requise"
        assert (await client.put(url, json={"choix": "chroot"}, headers=entetes)).status_code == 422
        rep = await client.put(url, json={"choix": "podman"}, headers=entetes)
        assert rep.status_code == 200 and rep.json()["bac_a_sable"] == "podman"
        liste = (await client.get("/v1/ateliers", headers=entetes)).json()
        etat = {x["id"]: x for x in liste["ateliers"]}[ident]["bac"]
        assert etat["effectif"] is None and "Podman indisponible" in etat["refus"]
        rep = await client.post(f"/v1/ateliers/{ident}/consigne", json={"consigne": "go"}, headers=entetes)
        assert rep.status_code == 409 and "Podman indisponible" in rep.json()["detail"]
        rep = await client.put(url, json={"choix": "aucun", "confirmer": True}, headers=entetes)
        assert rep.status_code == 200 and rep.json()["bac_a_sable"] == "aucun"

    lignes = await pool.fetch(
        "SELECT action, niveau, details FROM audit WHERE action IN"
        " ('atelier.bac_a_sable', 'atelier.sans_bac_a_sable') ORDER BY id DESC LIMIT 3"
    )
    vus = [
        (r["action"], r["niveau"], json.loads(r["details"]) if isinstance(r["details"], str) else r["details"])
        for r in lignes
    ]
    assert vus == [
        ("atelier.bac_a_sable", "jaune", {"choix": "aucun"}),
        ("atelier.bac_a_sable", "vert", {"choix": "podman"}),
        ("atelier.sans_bac_a_sable", "jaune", {}),
    ]
