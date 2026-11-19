"""Phase 13, lot K1 : éveil « Dis Jarvis » en deux étages, machine à états actif / veille, relance sur les
horodatages, commandes vocales, mémoire d'ambiance (désactivée par défaut, locale uniquement)."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.db import Base
from jarvis2.eveil import (
    PERIODE_AMBIANCE,
    ServiceEveil,
    commande_vocale,
    detecter,
    modele_eveil,
)
from jarvis2.securite import appareils

from .test_agents import systeme
from .test_connecteurs import Faux


class Dicte:
    """Transcripteur factice : rend les phrases prévues, dans l'ordre."""

    def __init__(self, *phrases: str) -> None:
        self.phrases = deque(phrases)

    async def transcrire(self, audio: bytes) -> tuple[str, str | None]:
        return self.phrases.popleft(), "fr"


class JugeFixe:
    def __init__(self, avis: bool | None) -> None:
        self.avis = avis
        self.appels: list[str] = []

    async def juger(self, phrase: str, avant: str) -> bool | None:
        self.appels.append(phrase)
        return self.avis


# --- Étage 1 et commandes vocales (sans base) --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texte", "commande"),
    [
        ("Dis Jarvis, quelle heure est-il ?", "quelle heure est-il ?"),
        ("Hey Jarvis ! Allume la lumière.", "Allume la lumière."),
        ("J'arvis, quel temps fait-il ?", "quel temps fait-il ?"),
        ("Djarvis météo de demain", "météo de demain"),
        ("Jar vis, mets de la musique", "mets de la musique"),
        ("Jarvice, lance un minuteur", "lance un minuteur"),
        ("Jarvis.", ""),
    ],
)
def test_eveil_certain(texte: str, commande: str) -> None:
    d = detecter(texte)
    assert d.certain and d.position == "tete" and d.commande == commande


def test_signaux_pour_le_juge() -> None:
    douteux = detecter("J'arrive dans cinq minutes")  # alias douteux : jamais certain
    assert douteux.signal and douteux.position == "tete"
    milieu = detecter("Je parlais de Jarvis hier avec Paul")
    assert milieu.signal and milieu.position == "milieu" and milieu.commande == "Je parlais de hier avec Paul"
    fin = detecter("Quelle heure est-il, Jarvis ?")
    assert fin.signal and fin.position == "fin" and fin.commande == "Quelle heure est-il"
    flou = detecter("Jarvos, ouvre la porte")
    assert flou.signal and 0.72 <= flou.score < 0.95
    assert not detecter("Bonjour tout le monde, on mange ?").trouve
    assert not detecter("").trouve


def test_commandes_vocales() -> None:
    assert commande_vocale("Stop !") == "stop"
    assert commande_vocale("Arrête-toi") == "stop"
    assert commande_vocale("Tais-toi, s'il te plaît.") == "silence"
    assert commande_vocale("Silence") == "silence"
    assert commande_vocale("Merci, c'est tout.") == "veille"
    assert commande_vocale("Stop la musique et lance la radio") is None
    assert commande_vocale("Quelle heure est-il ?") is None


# --- Machine à états --------------------------------------------------------------------------------------------


async def service(pool: Base, tmp_path: Path, juge: Any = None, texte_local: str = "OUI") -> ServiceEveil:
    s = await systeme(pool, tmp_path, {"local": Faux("local", "local", externe=False, texte=texte_local)})
    return ServiceEveil(pool, s["service"], juge=juge if juge is not None else JugeFixe(None))


async def ecouter(s: ServiceEveil, t: Dicte, debut: float, fin: float, appareil: str = "pc") -> dict[str, Any]:
    return await s.ecouter(appareil, t, b"audio", debut, fin)


@pytest.mark.base
async def test_veille_eveil_reponse_relance(pool: Base, tmp_path: Path) -> None:
    s = await service(pool, tmp_path)
    t = Dicte(
        "On mange quoi ce soir ?",
        "Dis Jarvis, quelle heure est-il ?",
        "Ah d'accord",
        "Et demain ?",
        "Et après-demain ?",
    )
    d = await ecouter(s, t, 1_000, 2_000)
    assert d["action"] == "ignorer" and d["etat"] == "veille"
    d = await ecouter(s, t, 3_000, 5_000)
    assert d["action"] == "envoyer" and d["commande"] == "quelle heure est-il ?" and d["etage"] == 1
    assert d["etat"] == "actif" and d["phase"] == "reponse"
    d = await ecouter(s, t, 6_000, 6_500)  # JARVIS répond : rien d'autre que « stop » ou « silence »
    assert d["action"] == "ignorer" and d["raison"] == "JARVIS répond"
    fin_voix = 12_000.0
    assert s.signaler("pc", "parole_fin", fin_voix)["phase"] == "relance"
    d = await ecouter(s, t, fin_voix + 2_000, fin_voix + 3_000)  # relance sans mot d'éveil, dans les 6 s
    assert d["action"] == "envoyer" and d["commande"] == "Et demain ?" and d["raison"] == "relance sans mot d'éveil"
    s.signaler("pc", "parole_fin", 20_000)
    d = await ecouter(s, t, 27_000, 28_000)  # fenêtre passée : veille
    assert d["action"] == "ignorer" and d["etat"] == "veille"
    assert s.etat("autre-appareil", 0)["etat"] == "veille"  # chaque appareil a sa conversation


@pytest.mark.base
async def test_relance_refusee_si_commencee_pendant_la_voix(pool: Base, tmp_path: Path) -> None:
    s = await service(pool, tmp_path)
    t = Dicte("Jarvis, raconte une histoire", "il était une fois", "stop")
    await ecouter(s, t, 0, 1_000)
    s.signaler("pc", "parole_fin", 10_000)
    d = await ecouter(s, t, 8_000, 10_500)  # écho de la voix de JARVIS, ou parole par-dessus (lot K2)
    assert d["action"] == "ignorer" and d["raison"] == "commencée pendant que JARVIS parlait"
    d = await ecouter(s, t, 9_000, 10_800)  # « stop » compte toujours
    assert d["action"] == "stop" and d["phase"] == "relance"


@pytest.mark.base
async def test_jarvis_seul_arme_la_phrase_suivante(pool: Base, tmp_path: Path) -> None:
    s = await service(pool, tmp_path)
    t = Dicte("Jarvis ?", "Allume la lumière du salon", "Jarvis", "Trop tard")
    d = await ecouter(s, t, 0, 600)
    assert d["action"] == "armer" and d["phase"] == "commande"
    d = await ecouter(s, t, 3_000, 4_500)
    assert d["action"] == "envoyer" and d["commande"] == "Allume la lumière du salon"
    s.signaler("pc", "annuler", 5_000)  # envoi impossible : retour en veille
    await ecouter(s, t, 6_000, 6_500)
    d = await ecouter(s, t, 6_500 + 9_000, 6_500 + 10_000)  # plus de 8 s après : la fenêtre est refermée
    assert d["action"] == "ignorer" and d["etat"] == "veille"


@pytest.mark.base
async def test_mot_eveil_coupe_en_deux_recolle_par_le_tampon(pool: Base, tmp_path: Path) -> None:
    s = await service(pool, tmp_path)
    t = Dicte("Dis jar", "vis, quelle heure est-il ?", "Dis jar", "vis, et la météo ?")
    assert (await ecouter(s, t, 0, 500))["action"] == "ignorer"
    d = await ecouter(s, t, 900, 2_000)  # 400 ms plus tard : les deux morceaux se touchent
    assert d["action"] == "envoyer" and d["commande"] == "quelle heure est-il ?"
    s.signaler("pc", "annuler", 2_100)
    await ecouter(s, t, 10_000, 10_500)
    d = await ecouter(s, t, 13_000, 14_000)  # 2,5 s d'écart : deux phrases distinctes
    assert d["action"] == "ignorer"


@pytest.mark.base
async def test_juge_seulement_sur_signal(pool: Base, tmp_path: Path) -> None:
    oui = JugeFixe(True)
    s = await service(pool, tmp_path, juge=oui)
    t = Dicte("Dis Jarvis, quelle heure est-il ?", "J'arrive, mets la musique")
    await ecouter(s, t, 0, 1_000)
    assert oui.appels == []  # éveil certain : le juge n'est pas dérangé
    s.signaler("pc", "annuler", 1_100)
    d = await ecouter(s, t, 5_000, 6_000)
    assert d["action"] == "envoyer" and d["etage"] == 2 and d["juge"] is True and len(oui.appels) == 1

    non = JugeFixe(False)
    s = await service(pool, tmp_path, juge=non)
    d = await ecouter(s, Dicte("J'ai dit à Paul que Jarvis était prêt"), 0, 1_000)
    assert d["action"] == "ignorer" and d["juge"] is False and d["raison"] == "mot d'éveil écarté"

    # Juge indisponible : vocatif en fin de phrase accepté, alias douteux refusé
    s = await service(pool, tmp_path, juge=JugeFixe(None))
    t = Dicte("Quelle heure est-il, Jarvis ?", "J'arrive dans cinq minutes")
    d = await ecouter(s, t, 0, 1_000)
    assert d["action"] == "envoyer" and d["commande"] == "Quelle heure est-il"
    s.signaler("pc", "annuler", 1_100)
    assert (await ecouter(s, t, 5_000, 6_000))["action"] == "ignorer"


@pytest.mark.base
async def test_juge_local_par_ia_locale(pool: Base, tmp_path: Path) -> None:
    from jarvis2.eveil import JugeLocal

    s = await systeme(pool, tmp_path, {"local": Faux("local", "local", externe=False, texte="Oui.")})
    assert await JugeLocal(s["service"]).juger("J'arrive, mets la musique", "") is True
    s = await systeme(pool, tmp_path, {"api": Faux("api", "api", externe=True, texte="OUI")})
    assert await JugeLocal(s["service"]).juger("J'arrive, mets la musique", "") is None  # jamais une IA externe
    s = await systeme(pool, tmp_path, {"local": Faux("local", "local", externe=False, dispo=False)})
    assert await JugeLocal(s["service"]).juger("J'arrive", "") is None  # Ollama arrêté : jamais démarré


@pytest.mark.base
async def test_commandes_silence_et_veille(pool: Base, tmp_path: Path) -> None:
    s = await service(pool, tmp_path)
    t = Dicte("Jarvis, raconte une blague", "Tais-toi", "Stop", "Jarvis, stop", "Jarvis, c'est tout")
    await ecouter(s, t, 0, 1_000)
    d = await ecouter(s, t, 2_000, 2_500)
    assert d["action"] == "silence" and d["etat"] == "veille"
    assert (await ecouter(s, t, 4_000, 4_500))["action"] == "ignorer"  # en veille, « stop » seul ne compte pas
    assert (await ecouter(s, t, 6_000, 6_500))["action"] == "stop"
    d = await ecouter(s, t, 7_000, 7_500)
    assert d["action"] == "veille" and d["etat"] == "veille"


# --- Réglages, mémoire d'ambiance ---------------------------------------------------------------------------------


@pytest.mark.base
async def test_reglages_par_defaut_et_bornes(pool: Base, tmp_path: Path) -> None:
    s = await service(pool, tmp_path)
    assert await s.lire_reglages() == {"ambiance": False, "openwakeword": False, "relance_s": 6}
    assert (await s.regler(relance_s=99, ambiance=True))["relance_s"] == 20
    autre = await service(pool, tmp_path)
    assert (await autre.lire_reglages())["ambiance"] is True  # gardé en base


@pytest.mark.base
async def test_ambiance_desactivee_par_defaut_puis_locale(pool: Base, tmp_path: Path) -> None:
    s = await service(pool, tmp_path)
    await ecouter(s, Dicte("Il faudra rappeler le garagiste demain matin"), 0, 1_000)
    assert len(s.ambiance.phrases) == 0  # désactivée : rien n'est gardé
    await s.regler(ambiance=True)
    s.exclu = lambda texte: "secret" in texte
    t = Dicte("Il faudra rappeler le garagiste demain matin", "Le projet secret avance", "Dis Jarvis, l'heure ?")
    await ecouter(s, t, 0, 1_000)
    await ecouter(s, t, 3_000, 4_000)
    await ecouter(s, t, 6_000, 7_000)
    assert [p for _, p in s.ambiance.phrases] == ["Il faudra rappeler le garagiste demain matin"]
    await s.regler(ambiance=False)
    assert len(s.ambiance.phrases) == 0  # désactivée : oubliée tout de suite


@pytest.mark.base
async def test_distillation_ambiance_en_souvenirs_prives(pool: Base, tmp_path: Path) -> None:
    reponse = '[{"contenu": "L\'utilisateur doit rappeler le garagiste demain.", "type": "note", "importance": 0.6}]'
    s = await service(pool, tmp_path, texte_local=reponse)
    debut = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)
    s.ambiance.noter("Il faudra rappeler le garagiste demain matin", debut)
    assert not s.ambiance.a_distiller(debut + timedelta(minutes=5))
    assert s.ambiance.a_distiller(debut + PERIODE_AMBIANCE)
    r = await s.ambiance.distiller(pool, s.dialogue, debut + PERIODE_AMBIANCE)
    assert r["statut"] == "ok" and r["ajoutes"] == 1 and len(s.ambiance.phrases) == 0  # texte brut oublié
    ligne = await pool.fetchrow("SELECT contenu, confidentialite, origine, tags FROM memoires")
    assert ligne is not None and ligne["confidentialite"] == "local_uniquement" and ligne["origine"] == "ecoute"
    assert "garagiste" in ligne["contenu"]

    # Sans IA locale : rien ne quitte le PC, le texte brut est oublié au bout de 30 min sans rien en retenir
    externe = await systeme(pool, tmp_path, {"api": Faux("api", "api", externe=True)})
    eveil = ServiceEveil(pool, externe["service"], juge=JugeFixe(None))
    eveil.ambiance.noter("Une idée pour le jardin partagé", debut)
    r = await eveil.ambiance.distiller(pool, externe["service"], debut + timedelta(minutes=40))
    assert r["statut"] == "ignoree" and len(eveil.ambiance.phrases) == 0
    assert externe["moteurs"]["api"].recus == []
    eveil.ambiance.noter("Penser à arroser les tomates ce soir", debut + timedelta(minutes=25))
    assert not eveil.ambiance.a_distiller(debut + timedelta(minutes=41))  # nouvel essai dans 3 min seulement
    assert eveil.ambiance.a_distiller(debut + timedelta(minutes=44))


# --- Option openWakeWord et routes -------------------------------------------------------------------------------


def test_modele_openwakeword_declare_sans_telechargement(tmp_path: Path) -> None:
    m = modele_eveil(tmp_path)
    assert m.id == "eveil" and m.dossier == tmp_path / "eveil" / "dis-jarvis"
    assert not m.dossier.exists()  # déclarer le modèle ne télécharge rien


async def client(pool: Base, tmp_path: Path, *phrases: str) -> tuple[httpx.AsyncClient, Contexte]:
    s = await systeme(pool, tmp_path, {"local": Faux("local", "local", externe=False)})
    ctx = Contexte(
        pool, s["depot"], s["connecteurs"].moteurs, s["service"], "local", connecteurs=s["connecteurs"],
        transcripteur=Dicte(*phrases),
    )  # fmt: skip
    ctx.eveil.juge = JugeFixe(None)
    app = creer_app(Parametres(JARVIS2_DOSSIER_DONNEES=str(tmp_path)), ctx)
    app.state.ctx = ctx
    _, jeton = await appareils.creer(pool, "PC", "pc")
    c = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost:8765",
        headers={"Authorization": f"Bearer {jeton}"},
    )
    return c, ctx


@pytest.mark.base
async def test_routes_eveil(pool: Base, tmp_path: Path) -> None:
    c, ctx = await client(pool, tmp_path, "Dis Jarvis, quelle heure est-il ?", "Et demain ?")
    etat = (await c.get("/v1/voix/eveil")).json()
    assert etat["reglages"] == {"ambiance": False, "openwakeword": False, "relance_s": 6}
    assert etat["conversation"]["etat"] == "veille" and etat["telechargement"]["statut"] == "absent"
    assert etat["acoustique"]["utilisee"] is False

    rep = await c.post("/v1/voix/ecoute", content=b"audio", headers={"X-Debut": "1000", "X-Fin": "2500"})
    assert rep.json()["action"] == "envoyer" and rep.json()["commande"] == "quelle heure est-il ?"
    rep = await c.post("/v1/voix/ecoute/evenement", json={"evenement": "parole_fin", "t": 9000})
    assert rep.json()["phase"] == "relance"
    rep = await c.post("/v1/voix/ecoute", content=b"audio", headers={"X-Debut": "10000", "X-Fin": "11000"})
    assert rep.json()["action"] == "envoyer" and rep.json()["commande"] == "Et demain ?"
    assert (await c.post("/v1/voix/ecoute", content=b"")).status_code == 422
    assert (await c.post("/v1/voix/ecoute/evenement", json={"evenement": "nimporte"})).status_code == 422

    rep = await c.put("/v1/voix/eveil", json={"ambiance": True, "relance_s": 8})
    assert rep.json()["reglages"] == {"ambiance": True, "openwakeword": False, "relance_s": 8}
    assert (await c.put("/v1/voix/eveil", json={"relance_s": 60})).status_code == 422
    audit = await pool.fetchval("SELECT count(*) FROM audit WHERE action = 'voix.eveil.regle'")
    assert audit >= 1
    rep = await c.post("/v1/voix/ambiance/oublier")
    assert rep.json()["ambiance"]["phrases"] == 0
    assert ctx.eveil.acoustique.dossier == tmp_path / "modeles" / "eveil" / "dis-jarvis"


@pytest.mark.base
async def test_openwakeword_indisponible_whisper_decide(pool: Base, tmp_path: Path) -> None:
    s = await service(pool, tmp_path)
    s.acoustique.dossier = tmp_path / "eveil"
    await s.regler(openwakeword=True)
    assert s.etat_acoustique() == {"active": True, "paquet": s.acoustique.paquet, "modele": False, "utilisee": False}
    d = await ecouter(s, Dicte("Dis Jarvis, l'heure ?"), 0, 1_000)
    assert d["action"] == "envoyer" and d["etage"] == 1  # sans modèle : l'étage acoustique est sauté
