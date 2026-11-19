"""Lot J : ressources et contrôle du PC. Tout passe par des faux : le vrai PC n'est jamais réglé."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis2 import vision
from jarvis2.agents.recettes import Planificateur
from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import ServiceDialogue
from jarvis2.moteurs.telemetrie import EnregistreurMemoire, MoteurInstrumente
from jarvis2.ocr import assez_de_texte
from jarvis2.pc import ServicePC
from jarvis2.pc.jeu import ModeJeu, Premier, est_un_jeu
from jarvis2.pc.ollama import ErreurOllama, GestionnaireOllama
from jarvis2.pc.pilote import ErreurPilote, verifier
from jarvis2.pc.ressources import Echantillon, Historique, _ram_linux, gpu_sysfs, lire_nvidia
from jarvis2.pc.windows import PiloteWindows
from jarvis2.securite import appareils
from jarvis2.securite.urgence import ArretUrgence

from .faux_pc import PERF, FauxDetecteur, FauxLanceur, FauxMesureur, FauxOllama, FauxPilote
from .test_securite import ORIGINE, MoteurEspion, enregistrer_cle

pytestmark = pytest.mark.base


def service_pc(
    pool: Base, urgence: ArretUrgence, pilote: FauxPilote | None = None
) -> tuple[ServicePC, FauxOllama, FauxLanceur, FauxDetecteur]:
    serveur = FauxOllama()
    lanceur = FauxLanceur(serveur)
    detecteur = FauxDetecteur()
    ollama = GestionnaireOllama(
        "http://127.0.0.1:11434", lanceur=lanceur, transport=serveur.transport(), attente_demarrage=2.0
    )
    pc = ServicePC(
        pool,
        pilote if pilote is not None else FauxPilote(),
        ollama,
        Historique(FauxMesureur()),
        ModeJeu(detecteur, ("monjeu.exe",)),
        urgence,
    )
    return pc, serveur, lanceur, detecteur


@pytest.fixture
async def pc(pool: Base) -> AsyncIterator[dict[str, Any]]:
    urgence = ArretUrgence()
    pilote = FauxPilote()
    service, serveur, lanceur, detecteur = service_pc(pool, urgence, pilote)
    depot = DepotConversations(pool)
    moteurs = {"espion": MoteurInstrumente(MoteurEspion(), EnregistreurMemoire())}
    ctx = Contexte(
        pool, depot, moteurs, ServiceDialogue(depot, moteurs, "espion"), "espion", urgence=urgence, pc=service
    )
    app = creer_app(Parametres(), ctx)
    app.state.ctx = ctx
    await service.charger()
    _, jeton = await appareils.creer(pool, "PC", "pc")
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGINE,
        headers={"Authorization": f"Bearer {jeton}", "Origin": ORIGINE},
    )
    try:
        yield {
            "client": client,
            "pilote": pilote,
            "pc": service,
            "ctx": ctx,
            "ollama": serveur,
            "lanceur": lanceur,
            "detecteur": detecteur,
            "pool": pool,
        }
    finally:
        await client.aclose()


async def action(client: httpx.AsyncClient, nom: str, **parametres: Any) -> dict[str, Any]:
    r = await client.post("/v1/actions", json={"action": nom, "parametres": parametres})
    assert r.status_code == 200, r.text
    corps: dict[str, Any] = r.json()
    return corps


async def approuver(client: httpx.AsyncClient, corps: dict[str, Any]) -> httpx.Response:
    assert corps["statut"] == "en_attente", corps
    return await client.post(f"/v1/demandes/{corps['demande']['id']}/approuver", json={})


async def compter_audit(pool: Base, nom: str, resultat: str = "execute") -> int:
    return int(await pool.fetchval("SELECT count(*) FROM audit WHERE action = $1 AND resultat = $2", nom, resultat))


# --- Contrôle du PC sous 🟢🟡🔴, vérifié en relisant ------------------------------------------------------------


async def test_volume_approuve_puis_verifie(pc: dict[str, Any]) -> None:
    client, pilote = pc["client"], pc["pilote"]
    avant = await compter_audit(pc["pool"], "pc.volume")
    demande = await action(client, "pc.volume", niveau=30)
    assert demande["demande"]["niveau"] == "jaune" and pilote.volume == 50  # rien avant l'approbation
    r = await approuver(client, demande)
    assert r.status_code == 200, r.text
    resultat = r.json()["resultat"]
    assert pilote.volume == 30 and resultat["verifiee"] is True and resultat["statut"] == "vérifiée"
    assert await compter_audit(pc["pool"], "pc.volume") == avant + 1
    sourdine = (await approuver(client, await action(client, "pc.sourdine", muet=True))).json()["resultat"]
    assert pilote.muet is True and sourdine["verifiee"] is True


async def test_reglage_qui_ne_prend_pas_est_non_verifie(pc: dict[str, Any]) -> None:
    client, pilote = pc["client"], pc["pilote"]
    pilote.ignore.add("volume")  # Windows « accepte » mais rien ne change
    r = (await approuver(client, await action(client, "pc.volume", niveau=10))).json()["resultat"]
    assert r["verifiee"] is False and r["statut"] == "non vérifiée" and r["lu"] == 50
    pilote.luminosite = None  # écran sans DDC/CI : refus clair, rien n'est inventé
    echec = await approuver(client, await action(client, "pc.luminosite", niveau=40))
    assert echec.status_code == 409 and "Luminosité" in echec.json()["detail"]


async def test_verification_sans_relecture_possible() -> None:
    def impossible() -> Any:
        raise ErreurPilote("lecture refusée")

    v = await verifier(impossible, 3, pause=0)
    assert v.verifiee is False and "relecture impossible" in v.detail
    assert (await verifier(lambda: None, 3, essais=2, pause=0)).en_dict()["statut"] == "non vérifiée"


async def test_fenetres_media_et_verrouillage(pc: dict[str, Any]) -> None:
    client, pilote = pc["client"], pc["pilote"]
    etat = (await client.get("/v1/pc/etat")).json()
    assert [f["programme"] for f in etat["fenetres"]] == ["notepad.exe", "lecteur.exe"]
    assert etat["volume"] == {"niveau": 50, "muet": False} and etat["media"]["statut"] == "lecture"
    demande = await action(client, "pc.fenetre.minimiser", id=202, titre="Lecteur")
    assert demande["demande"]["toujours_possible"] is False  # agir sur une fenêtre = un clic : jamais « toujours »
    assert (await approuver(client, demande)).json()["resultat"]["verifiee"] is True
    assert pilote.fenetres()[1].reduite is True
    activer = (await approuver(client, await action(client, "pc.fenetre.activer", id=202))).json()["resultat"]
    assert activer["verifiee"] is True and pilote.fenetres()[1].active is True
    pause = (await approuver(client, await action(client, "pc.media", commande="pause"))).json()["resultat"]
    assert pause["verifiee"] is True and pilote.lecture.statut == "pause"
    suivant = (await approuver(client, await action(client, "pc.media", commande="suivant"))).json()["resultat"]
    assert suivant["verifiee"] is True and pilote.lecture.titre == "Morceau 2"
    inconnue = await client.post("/v1/actions", json={"action": "pc.media", "parametres": {"commande": "rm"}})
    assert (await approuver(client, inconnue.json())).status_code == 409
    fermer = (await approuver(client, await action(client, "pc.fenetre.fermer", id=101))).json()["resultat"]
    assert fermer["verifiee"] is True and [f.id for f in pilote.fenetres()] == [202]
    verrou = (await approuver(client, await action(client, "pc.verrouiller"))).json()["resultat"]
    assert verrou["verifiee"] is True and pilote.est_verrouille is True


async def test_extinction_rouge_annulable_et_annulee_par_l_urgence(pc: dict[str, Any]) -> None:
    client, pilote, pool = pc["client"], pc["pilote"], pc["pool"]
    demande = await action(client, "pc.eteindre", delai_s=120)
    assert demande["demande"]["niveau"] == "rouge" and "annulable" in demande["demande"]["resume"]
    clic = await approuver(client, demande)
    assert clic.status_code == 409 and pilote.extinction is None  # 🔴 : clé d'accès exigée
    cle = await enregistrer_cle(client)
    defi = (await client.post(f"/v1/demandes/{demande['demande']['id']}/options")).json()
    ok = await client.post(f"/v1/demandes/{demande['demande']['id']}/approuver", json={"credential": cle.signer(defi)})
    resultat = ok.json()["resultat"]
    assert pilote.extinction == 120 and resultat["annulable"] is True and resultat["verifiee"] is False
    assert 0 < (await client.get("/v1/pc/etat")).json()["extinction_dans_s"] <= 120
    async with pool.acquire() as conn:
        await pc["ctx"].urgence.arreter(conn, "test")  # l'arrêt d'urgence annule l'extinction tout de suite
    assert pilote.extinction is None and "annulation" in pilote.appels
    trop_court = await client.post("/v1/actions", json={"action": "pc.eteindre", "parametres": {"delai_s": 5}})
    assert trop_court.status_code == 423  # urgence active : aucune écriture


async def test_annuler_sans_extinction_prevue(pc: dict[str, Any]) -> None:
    r = await action(pc["client"], "pc.extinction.annuler")  # 🟢 : protège, exécuté tout de suite
    assert r["statut"] == "executee" and r["resultat"]["annulee"] is False


async def test_action_approuvee_n_agit_pas_pendant_l_urgence(pc: dict[str, Any]) -> None:
    client, pilote, pool = pc["client"], pc["pilote"], pc["pool"]
    demande = await action(client, "pc.volume", niveau=5)
    async with pool.acquire() as conn:
        await pc["ctx"].urgence.arreter(conn, "test")
    r = await approuver(client, demande)
    assert r.status_code == 409 and "urgence" in r.json()["detail"] and pilote.volume == 50


async def test_modes_qui_changent_windows_puis_normal(pc: dict[str, Any]) -> None:
    client, pilote, service = pc["client"], pc["pilote"], pc["pc"]
    jeu = (await approuver(client, await action(client, "pc.mode", mode="jeu"))).json()["resultat"]
    assert jeu["verifiee"] is True and {e["reglage"] for e in jeu["etapes"]} == {"plan", "notifications", "veille"}
    assert pilote.plan == PERF and pilote.notifications is False and service.jeu.en_veille
    nuit = (await approuver(client, await action(client, "pc.mode", mode="nuit"))).json()["resultat"]
    assert nuit["verifiee"] is True and pilote.sombre is True and pilote.luminosite == 30 and pilote.volume == 30
    normal = (await approuver(client, await action(client, "pc.mode", mode="normal"))).json()["resultat"]
    assert normal["verifiee"] is True
    assert (pilote.plan, pilote.notifications, pilote.sombre, pilote.luminosite, pilote.volume) == (
        "381b4222-f694-41f0-9685-ff5bb260df2e", True, False, 70, 50
    )  # fmt: skip
    assert service.jeu.reglage == "automatique" and not service.jeu.en_veille
    valeur = await pc["pool"].fetchval("SELECT valeur FROM etat_systeme WHERE cle = 'pc'")
    assert '"normal"' in str(valeur) or (isinstance(valeur, dict) and valeur["mode"] == "normal")


async def test_mode_sans_plan_performances_et_reglage_qui_ne_prend_pas(pool: Base) -> None:
    pilote = FauxPilote(plans={"381b4222-f694-41f0-9685-ff5bb260df2e": "Utilisation normale"})
    pilote.ignore.add("notifications")
    service, *_ = service_pc(pool, ArretUrgence(), pilote)
    async with pool.acquire() as conn:
        r = await service.appliquer_mode(conn, "jeu")
    assert r["ignores"] == ["aucun plan d'alimentation Performances sur ce PC"]
    assert r["verifiee"] is False and r["statut"] == "non vérifiée"


async def test_sans_ecran_le_controle_est_refuse(pc: dict[str, Any]) -> None:
    client = pc["client"]
    pc["ctx"].sans_ecran = True
    noms = {a["nom"] for a in (await client.get("/v1/actions")).json()["actions"]}
    assert "pc.volume" not in noms and "pc.fenetre.fermer" not in noms and "ollama.demarrer" in noms
    assert (await client.get("/v1/pc/etat")).status_code == 409
    refus = await client.post("/v1/actions", json={"action": "pc.volume", "parametres": {"niveau": 1}})
    assert refus.status_code == 422 and pc["pilote"].volume == 50
    assert (await client.get("/v1/pc/ressources")).json()["controle"] is False


def test_le_vrai_pilote_refuse_d_ecrire_pendant_les_tests() -> None:
    p = PiloteWindows()
    for reglage in (
        lambda: p.regler_volume(1),
        lambda: p.regler_muet(True),
        lambda: p.regler_luminosite(1),
        p.verrouiller,
        lambda: p.planifier_extinction(60, "x"),
        lambda: p.regler_theme_sombre(True),
        lambda: p.regler_notifications(False),
        lambda: p.regler_plan_alimentation(PERF),
        lambda: p.agir_fenetre(1, "fermer"),
        lambda: p.commande_media("pause"),
        p.annuler_extinction,
    ):
        with pytest.raises(ErreurPilote, match="tests"):
            reglage()


# --- Ressources -------------------------------------------------------------------------------------------------


async def test_ressources_et_alertes(pc: dict[str, Any]) -> None:
    pc["ollama"].actif, pc["ollama"].charges = True, ["qwen3.5:9b"]
    r = (await pc["client"].get("/v1/pc/ressources")).json()
    assert r["actuel"]["cpu"] == 12.5 and r["actuel"]["ram"] == 25.0 and r["actuel"]["vram"] == 83.3
    assert r["alertes"] == ["GPU à 85 %", "VRAM à 83 %"] and len(r["courbe"]) == 1
    assert r["ollama"]["modeles_charges"][0] == {
        "nom": "qwen3.5:9b", "taille_go": 2.0, "vram_go": 1.0, "expire_le": None
    }  # fmt: skip
    assert r["ollama"]["lance_par_jarvis"] is False and r["controle"] is True


def test_lectures_des_ressources(tmp_path: Path) -> None:
    assert lire_nvidia("37, 4096, 8192\n5, 100, 24576") == (5.0, 0.1, 24.0)
    assert lire_nvidia("") is None and lire_nvidia("n/a") is None
    (tmp_path / "meminfo").write_text("MemTotal:       16777216 kB\nMemAvailable:    4194304 kB\n")
    assert _ram_linux(tmp_path / "meminfo") == (12.0, 16.0)
    carte = tmp_path / "card0" / "device"
    carte.mkdir(parents=True)
    (carte / "mem_info_vram_used").write_text(str(3 * 1024**3))
    (carte / "gpu_busy_percent").write_text("42")
    assert gpu_sysfs(tmp_path) == (42.0, 3.0)
    e = Echantillon(0, 50, None, None, 81, None, None)
    assert e.ram is None and e.alertes() == ["GPU à 81 %"]


# --- Ollama à la demande ----------------------------------------------------------------------------------------


async def test_ollama_demarre_seulement_sur_demande_approuvee(pc: dict[str, Any]) -> None:
    client, serveur, lanceur = pc["client"], pc["ollama"], pc["lanceur"]
    assert (await client.get("/v1/pc/ressources")).json()["ollama"]["joignable"] is False
    assert lanceur.lances == []  # lire l'état ne démarre rien
    demande = await action(client, "ollama.demarrer")
    assert demande["demande"]["toujours_possible"] is False and lanceur.lances == []
    r = (await approuver(client, demande)).json()["resultat"]
    assert r == {"deja_demarre": False, "lance_par_jarvis": True, "verifiee": True}
    assert lanceur.lances == ["127.0.0.1:11434"] and serveur.actif
    serveur.charges = ["a", "b"]
    dech = await action(client, "ollama.decharger", modele="a")  # 🟢 : libérer protège
    assert dech["statut"] == "executee" and dech["resultat"]["verifiee"] is True and serveur.charges == ["b"]
    arret = (await approuver(client, await action(client, "ollama.arreter"))).json()["resultat"]
    assert arret["arrete"] is True and arret["verifiee"] is True and lanceur.arretes == 1


async def test_ollama_de_l_utilisateur_n_est_jamais_arrete(pool: Base) -> None:
    service, serveur, lanceur, _ = service_pc(pool, ArretUrgence())
    serveur.actif = True  # démarré par l'utilisateur, pas par JARVIS
    with pytest.raises(ErreurOllama, match="pas été démarré par JARVIS"):
        await service.ollama.arreter()
    assert (await service.ollama.demarrer())["deja_demarre"] is True and lanceur.lances == []
    await service.ollama.surveiller()
    await service.ollama.fermer()
    assert lanceur.arretes == 0 and serveur.actif


async def test_ollama_absent_ou_bloque_par_l_urgence(pool: Base) -> None:
    urgence = ArretUrgence()
    service, _, lanceur, _ = service_pc(pool, urgence)
    lanceur.installe = False
    with pytest.raises(ErreurOllama, match="pas installé"):
        await service.ollama.demarrer()
    urgence.actif = True
    with pytest.raises(ErreurOllama, match="urgence"):
        await service.ollama.demarrer()


async def test_ollama_arrete_apres_inactivite_et_a_la_fermeture(pool: Base) -> None:
    service, serveur, lanceur, _ = service_pc(pool, ArretUrgence())
    o = service.ollama
    await o.demarrer()
    serveur.charges = ["m"]
    await o.surveiller()
    assert o.depuis_inactif is None  # un modèle chargé : actif
    serveur.charges = []
    await o.surveiller()
    assert o.depuis_inactif is not None and (await o.etat())["arret_dans_s"] is not None
    o.depuis_inactif -= o.inactivite * 60 + 1  # 20 minutes passées sans modèle
    await o.surveiller()
    assert lanceur.arretes == 1 and not serveur.actif and not o.lance_par_jarvis
    await o.demarrer()
    await o.fermer()  # arrêt du Core : l'Ollama de JARVIS s'arrête avec lui
    assert lanceur.arretes == 2


# --- Mode jeu (veille stricte) ----------------------------------------------------------------------------------


def test_detection_des_jeux() -> None:
    assert est_un_jeu(Premier(r"D:\SteamLibrary\steamapps\common\Jeu\jeu.exe", False)) == "jeu.exe"
    assert est_un_jeu(Premier(r"C:\Program Files\Riot Games\VALORANT\x.exe", False)) == "x.exe"
    assert est_un_jeu(Premier(r"C:\Jeux\monjeu.exe", False), ["MonJeu.exe"]) == "monjeu.exe"
    assert est_un_jeu(Premier(r"C:\Outils\plein.exe", True)) == "plein.exe"
    assert est_un_jeu(Premier(r"C:\Program Files\Google\Chrome\chrome.exe", True)) is None  # vidéo plein écran
    assert est_un_jeu(Premier(r"C:\Windows\notepad.exe", False)) is None


async def test_veille_apres_5_s_de_jeu_et_reveil_20_s_apres(pc: dict[str, Any]) -> None:
    service, detecteur, serveur = pc["pc"], pc["detecteur"], pc["ollama"]
    jeu = service.jeu
    await service.ollama.demarrer()
    serveur.charges = ["gros-modele"]
    detecteur.premier = Premier(r"C:\Jeux\monjeu.exe", False)
    await jeu.observer(100.0)
    await jeu.observer(103.0)
    assert not jeu.en_veille
    await jeu.observer(105.5)
    assert jeu.en_veille and jeu.decrire()["jeu"] == "monjeu.exe"
    assert serveur.charges == [] and not serveur.actif  # modèles déchargés, Ollama de JARVIS arrêté
    assert (await pc["client"].get("/v1/pc/ressources")).json()["jeu"]["en_veille"] is True
    detecteur.premier = Premier(r"C:\Windows\explorer.exe", False)
    await jeu.observer(110.0)
    await jeu.observer(125.0)
    assert jeu.en_veille  # Alt+Tab : pas de réveil trop tôt
    await jeu.observer(131.0)
    assert not jeu.en_veille and pc["lanceur"].lances == ["127.0.0.1:11434"]  # rien ne redémarre seul


async def test_reglage_du_mode_jeu(pc: dict[str, Any]) -> None:
    client, service = pc["client"], pc["pc"]
    r = await action(client, "pc.jeu", reglage="force")
    assert r["statut"] == "executee" and r["resultat"]["en_veille"] is True and r["resultat"]["verifiee"]
    service.jeu.reglage = "automatique"
    await service.charger()  # relu depuis la base
    assert service.jeu.reglage == "force"
    await action(client, "pc.jeu", reglage="jamais")
    pc["detecteur"].premier = Premier(r"C:\Jeux\monjeu.exe", True)
    await service.jeu.observer(0.0)
    await service.jeu.observer(10.0)
    assert not service.jeu.en_veille
    assert (await client.post("/v1/actions", json={"action": "pc.jeu", "parametres": {"reglage": "x"}})).status_code
    pc["ctx"].sans_ecran = True  # sans écran : pas de détection, mais la veille forcée reste possible
    assert service.jeu.decrire()["detection"] is False


async def test_recettes_en_attente_pendant_la_veille(pool: Base, tmp_path: Path) -> None:
    depot = DepotConversations(pool)
    moteurs = {"espion": MoteurInstrumente(MoteurEspion(), EnregistreurMemoire())}
    planificateur = Planificateur(pool, ServiceDialogue(depot, moteurs, "espion"), tmp_path, ArretUrgence())
    service, *_ = service_pc(pool, ArretUrgence())
    planificateur.en_pause = lambda: service.jeu.en_veille
    await service.jeu.regler("force")
    assert planificateur.en_pause() is True


# --- Vision : OCR d'abord -------------------------------------------------------------------------------------


class FauxOCR:
    nom = "faux"

    def __init__(self, texte: str) -> None:
        self.texte = texte
        self.appels = 0

    def lire(self, image: bytes) -> str:
        self.appels += 1
        return self.texte


async def test_vision_ocr_d_abord(monkeypatch: pytest.MonkeyPatch) -> None:
    decrits: list[str | None] = []

    async def decrire(url: str, modele: str | None, image: bytes, question: str | None = None) -> str:
        decrits.append(question)
        return "Un chat sur un canapé."

    monkeypatch.setattr(vision, "decrire", decrire)
    texte = "Rapport mensuel des ventes : chiffre d'affaires en hausse de douze pour cent ce mois-ci."
    r = await vision.analyser("http://o", "vision", b"png", None, FauxOCR(texte))
    assert r["methode"] == "ocr" and texte in r["description"] and decrits == []  # aucun modèle réveillé

    async def arrete() -> bool:
        return False

    async def demarre() -> bool:
        return True

    peu = FauxOCR("OK")
    r = await vision.analyser("http://o", "vision", b"png", None, peu, arrete)
    assert r["ollama_requis"] is True and r["modele"] is None and decrits == []  # Ollama jamais démarré ici
    r = await vision.analyser("http://o", "vision", b"png", "Que vois-tu ?", peu, demarre)
    assert r["methode"] == "modele" and r["description"] == "Un chat sur un canapé." and "OK" in str(decrits[0])
    force = FauxOCR(texte)
    r = await vision.analyser("http://o", "vision", b"png", None, force, demarre, forcer_modele=True)
    assert r["methode"] == "modele" and force.appels == 0
    assert assez_de_texte(texte) and not assez_de_texte("Fichier Édition") and not assez_de_texte(None)
