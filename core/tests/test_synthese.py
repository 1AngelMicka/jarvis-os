"""Lot 13 · K2 : synthèse vocale (Piper en processus séparé, ElevenLabs avec la clé du coffre), secrets masqués,
coupure quand on parle par-dessus. Aucun appel réseau réel, aucun vrai programme Piper."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis2 import coupure, synthese, telechargements
from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import ServiceDialogue
from jarvis2.moteurs.telemetrie import EnregistreurMemoire, MoteurInstrumente
from jarvis2.securite import appareils
from jarvis2.securite.coffre import Coffre

from .test_securite import ORIGINE, MoteurEspion

CLE_EL = "el-cle-de-test-" + "z" * 24
CLE_OPENAI = "sk-proj-" + "a" * 30
WAV = b"RIFF" + b"\x00" * 60


# --- Texte lu à voix haute ------------------------------------------------------------------------------------------


def test_secrets_masques_avant_lecture() -> None:
    dit = synthese.texte_a_dire(f"Votre **clé** est {CLE_OPENAI}, et le mot de passe : Hunter2024!")
    assert CLE_OPENAI not in dit and "Hunter2024" not in dit
    assert "(secret masqué)" in dit and "[" not in dit and "*" not in dit


def test_donnees_personnelles_masquees_pour_une_voix_en_ligne() -> None:
    texte = "Écrivez à marie.dupont@example.org demain."
    assert "marie.dupont" in synthese.texte_a_dire(texte)  # voix locale : rien ne sort du PC
    assert "marie.dupont" not in synthese.texte_a_dire(texte, externe=True)


def test_reglages_normalises() -> None:
    r = synthese.normaliser({"moteur": "inconnu", "voix_piper": "../../x", "voix_elevenlabs": "a/b", "coupure": 1})
    assert r == synthese.REGLAGES_DEFAUT
    r = synthese.normaliser({"moteur": "piper", "voix_piper": "fr_FR-tom-medium", "coupure": False})
    assert r["moteur"] == "piper" and r["voix_piper"] == "fr_FR-tom-medium" and r["coupure"] is False


# --- Piper : processus séparé ---------------------------------------------------------------------------------------


class FauxPiper:
    """Remplace le lancement du processus : note les arguments, l'entrée et le parallélisme, écrit un WAV."""

    def __init__(self, code: int = 0) -> None:
        self.appels: list[tuple[list[str], bytes]] = []
        self.en_cours = 0
        self.max_en_cours = 0
        self.code = code

    async def __call__(self, arguments: list[str], entree: bytes, delai: float) -> tuple[int, bytes]:
        self.appels.append((arguments, entree))
        self.en_cours += 1
        self.max_en_cours = max(self.max_en_cours, self.en_cours)
        await asyncio.sleep(0.02)
        self.en_cours -= 1
        if self.code == 0:
            Path(arguments[arguments.index("--output_file") + 1]).write_bytes(WAV)
        return self.code, b"erreur"


def _installer_piper(dossier_modeles: Path, ident: str = synthese.VOIX_PIPER_DEFAUT) -> Path:
    dossier = synthese.dossier_voix_piper(dossier_modeles, ident)
    dossier.mkdir(parents=True)
    (dossier / f"{ident}.onnx").write_bytes(b"onnx")
    (dossier / f"{ident}.onnx.json").write_text("{}", encoding="utf-8")
    programme = dossier_modeles / "piper" / "piper.exe"
    programme.write_bytes(b"")
    return programme


@pytest.mark.base
async def test_piper_en_processus_separe_et_en_parallele(pool: Base, tmp_path: Path) -> None:
    programme = _installer_piper(tmp_path)
    faux = FauxPiper()
    service = synthese.ServiceSynthese(
        pool, Coffre(tmp_path / "c.json", chiffrement=False), tmp_path, str(programme), executeur=faux
    )
    audios = await asyncio.gather(*(service.dire(f"Phrase {i}.", "piper") for i in range(5)))
    assert all(a.donnees == WAV and a.type == "audio/wav" and a.moteur == "piper" for a in audios)
    assert faux.max_en_cours == synthese.PIPER_SIMULTANES  # en parallèle, mais borné
    arguments, entree = faux.appels[0]
    assert arguments[0] == str(programme) and "--model" in arguments
    assert entree.decode().startswith("Phrase") and not any("Phrase" in a for a in arguments)  # texte sur stdin


@pytest.mark.base
async def test_piper_absent_ou_en_echec(pool: Base, tmp_path: Path) -> None:
    coffre = Coffre(tmp_path / "c.json", chiffrement=False)
    service = synthese.ServiceSynthese(pool, coffre, tmp_path, str(tmp_path / "absent.exe"), executeur=FauxPiper())
    service.programme_piper = lambda: None  # type: ignore[method-assign]  # ni chemin, ni PATH
    with pytest.raises(synthese.ErreurSynthese, match="introuvable"):
        await service.dire("Bonjour.", "piper")
    programme = _installer_piper(tmp_path)
    service = synthese.ServiceSynthese(pool, coffre, tmp_path, str(programme), executeur=FauxPiper(code=1))
    with pytest.raises(synthese.ErreurSynthese, match="échoué"):
        await service.dire("Bonjour.", "piper")


def test_voix_piper_resolue_depuis_le_hub(tmp_path: Path) -> None:
    def hub(requete: httpx.Request) -> httpx.Response:
        assert requete.url.path == "/api/models/rhasspy/piper-voices/revision/main"
        base = "fr/fr_FR/siwis/medium/fr_FR-siwis-medium"
        return httpx.Response(
            200,
            json={
                "sha": "abc",
                "siblings": [
                    {"rfilename": f"{base}.onnx", "lfs": {"size": 10, "sha256": "e" * 64}},
                    {"rfilename": f"{base}.onnx.json", "size": 5},
                    {"rfilename": "fr/fr_FR/tom/medium/fr_FR-tom-medium.onnx", "size": 9},
                ],
            },
        )

    modele = synthese.modele_piper(tmp_path, synthese.VOIX_PIPER_DEFAUT, hub="https://hub.test")
    with httpx.Client(transport=httpx.MockTransport(hub)) as client:
        fichiers = modele.resoudre(client)
    assert [f.chemin for f in fichiers] == ["fr_FR-siwis-medium.onnx", "fr_FR-siwis-medium.onnx.json"]
    assert fichiers[0].sha256 == "e" * 64 and fichiers[0].url.endswith(
        "/resolve/abc/fr/fr_FR/siwis/medium/" + fichiers[0].chemin
    )
    assert modele.dossier == tmp_path / "piper" / "fr_FR-siwis-medium"
    assert not telechargements.est_pret(modele)  # rien n'est téléchargé sans accord


# --- API : réglages, clé ElevenLabs, phrase en audio ----------------------------------------------------------------


@pytest.fixture
async def systeme(pool: Base, tmp_path: Path) -> AsyncIterator[dict[str, Any]]:
    envoyes: list[httpx.Request] = []
    prives: list[str] = []

    def elevenlabs(requete: httpx.Request) -> httpx.Response:
        envoyes.append(requete)
        if requete.headers.get("xi-api-key") != CLE_EL:
            return httpx.Response(401)
        return httpx.Response(200, content=b"ID3mp3", headers={"content-type": "audio/mpeg"})

    async def est_prive(texte: str) -> bool:
        prives.append(texte)
        return "médecin" in texte

    coffre = Coffre(tmp_path / "coffre.json", chiffrement=False)
    programme = _installer_piper(tmp_path / "modeles")
    service_synthese = synthese.ServiceSynthese(
        pool,
        coffre,
        tmp_path / "modeles",
        str(programme),
        est_prive=est_prive,
        executeur=FauxPiper(),
        client=lambda: httpx.AsyncClient(transport=httpx.MockTransport(elevenlabs)),
        url_elevenlabs="https://el.test",
    )
    depot = DepotConversations(pool)
    moteurs = {"espion": MoteurInstrumente(MoteurEspion(), EnregistreurMemoire())}
    ctx = Contexte(pool, depot, moteurs, ServiceDialogue(depot, moteurs, "espion"), "espion", synthese=service_synthese)
    app = creer_app(Parametres(dossier_donnees=tmp_path), ctx)
    app.state.ctx = ctx
    _, jeton = await appareils.creer(pool, "PC", "pc")
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGINE,
        headers={"Authorization": f"Bearer {jeton}", "Origin": ORIGINE},
    )
    try:
        yield {"client": client, "coffre": coffre, "envoyes": envoyes, "prives": prives, "pool": pool}
    finally:
        await client.aclose()


@pytest.mark.base
async def test_reglages_et_cle_elevenlabs(systeme: dict[str, Any]) -> None:
    client, pool = systeme["client"], systeme["pool"]
    etat = (await client.get("/v1/synthese")).json()
    assert etat["reglages"]["moteur"] == "navigateur" and etat["elevenlabs"] == {"cle": False, "apercu": None}
    assert etat["piper"]["programme"] is True and etat["piper"]["voix"][0]["prete"] is True
    assert "piper.exe" not in json.dumps(etat)  # jamais le chemin du programme

    r = await client.put("/v1/synthese/cle", json={"cle": CLE_EL})
    assert r.status_code == 200 and r.json()["elevenlabs"]["cle"] is True
    assert CLE_EL not in r.text and systeme["coffre"].lire("elevenlabs") == CLE_EL
    r = await client.put("/v1/synthese", json={"moteur": "elevenlabs", "coupure": False})
    assert r.json()["reglages"]["moteur"] == "elevenlabs" and r.json()["reglages"]["coupure"] is False
    assert (await client.put("/v1/synthese", json={"voix_piper": "inconnue"})).status_code == 422
    audits = " ".join(str(x["details"]) + x["action"] for x in await pool.fetch("SELECT action, details FROM audit"))
    assert "synthese.cle_definie" in audits and CLE_EL not in audits

    # Carte « Où partent mes données » : ElevenLabs actif, vers Internet, sans la clé
    flux = {f["id"]: f for f in (await client.get("/v1/donnees/flux")).json()["flux"]}
    assert flux["elevenlabs"]["etat"] == "actif" and flux["elevenlabs"]["destination"] == "internet"
    # Clé retirée : retour à une voix locale, le flux s'éteint
    r = await client.delete("/v1/synthese/cle")
    assert r.json()["elevenlabs"]["cle"] is False and r.json()["reglages"]["moteur"] == "navigateur"
    flux = {f["id"]: f for f in (await client.get("/v1/donnees/flux")).json()["flux"]}
    assert flux["elevenlabs"]["etat"] == "inactif"


@pytest.mark.base
async def test_dire_par_piper_et_par_elevenlabs(systeme: dict[str, Any]) -> None:
    client, envoyes = systeme["client"], systeme["envoyes"]
    r = await client.post("/v1/synthese/dire", json={"texte": "Bonjour.", "moteur": "piper"})
    assert r.status_code == 200 and r.content == WAV and r.headers["x-voix"] == "piper"

    # Sans clé : rien ne part, l'interface lira avec la voix du système
    r = await client.post("/v1/synthese/dire", json={"texte": "Bonjour.", "moteur": "elevenlabs"})
    assert r.status_code == 409 and not envoyes
    await client.put("/v1/synthese/cle", json={"cle": CLE_EL})
    r = await client.post(
        "/v1/synthese/dire", json={"texte": f"Clé {CLE_OPENAI}, écrivez à a.b@example.org.", "moteur": "elevenlabs"}
    )
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.headers["x-voix"] == "elevenlabs"
    corps = json.loads(envoyes[-1].content)
    assert CLE_OPENAI not in corps["text"] and "a.b@example.org" not in corps["text"]
    assert corps["model_id"] == synthese.MODELE_ELEVENLABS
    assert envoyes[-1].url.path == f"/v1/text-to-speech/{synthese.VOIX_ELEVENLABS_DEFAUT}"

    # Phrase privée : elle ne part pas (barrière des IA externes)
    avant = len(envoyes)
    r = await client.post("/v1/synthese/dire", json={"texte": "Rendez-vous chez le médecin.", "moteur": "elevenlabs"})
    assert r.status_code == 409 and len(envoyes) == avant

    # Clé refusée par le service : 409, l'interface prend le relais
    systeme["coffre"].definir("elevenlabs", "mauvaise-cle-123")
    r = await client.post("/v1/synthese/dire", json={"texte": "Bonjour.", "moteur": "elevenlabs"})
    assert r.status_code == 409 and "refusée" in r.json()["detail"]


@pytest.mark.base
async def test_telechargement_piper_sur_accord_seulement(systeme: dict[str, Any]) -> None:
    client = systeme["client"]
    etat = (await client.get("/v1/synthese")).json()
    assert etat["piper"]["telechargement"]["statut"] in ("pret", "absent")
    # La voix par défaut est déjà là : le clic ne relance rien
    r = await client.post("/v1/synthese/piper/telecharger")
    assert r.status_code == 200
    audits = [x["action"] for x in await systeme["pool"].fetch("SELECT action FROM audit")]
    assert "telechargement.lancer" not in audits


# --- Coupure quand on parle par-dessus ------------------------------------------------------------------------------


def _sinus(amplitude: float, frequence: float = 220.0, debut: int = 0) -> list[float]:
    return [
        amplitude * math.sin(2 * math.pi * frequence * (debut + i) / coupure.FREQUENCE) for i in range(coupure.TRAME)
    ]


def test_trames_de_10_ms() -> None:
    assert coupure.TRAME == 160


def test_delai_mesure_par_intercorrelation() -> None:
    enveloppe = [0.1 if (i // 7) % 2 else 0.0 for i in range(120)]
    micro = [0.0] * 8 + [x * 0.3 for x in enveloppe[:-8]]  # écho 80 ms plus tard, atténué
    assert coupure.mesurer_delai(enveloppe, micro) == 80
    assert coupure.mesurer_delai([0.0] * 50, micro[:50]) is None  # haut-parleur muet : rien à mesurer


def test_casque_detecte_par_le_nom() -> None:
    assert coupure.casque_par_nom(["Haut-parleurs (Realtek)", "Casque (WH-1000XM4)"])
    assert coupure.casque_par_nom(["AirPods Pro"])
    assert not coupure.casque_par_nom(["Haut-parleurs (Realtek)", "Microphone (USB)"])


def test_repli_rms_ne_se_coupe_pas_sur_son_propre_echo() -> None:
    d = coupure.DetecteurCoupure(annulation=None)
    d._apm = None  # repli forcé, même si livekit est installé
    for i in range(300):  # JARVIS parle seul : le micro entend son écho (30 %)
        hp = _sinus(0.3, debut=i * coupure.TRAME)
        assert not d.trame([x * 0.3 for x in hp], hp)
    assert d.mode == "rms"
    coupe = False
    for i in range(30):  # l'utilisateur parle fort par-dessus
        hp = _sinus(0.3, debut=i * coupure.TRAME)
        voix = _sinus(0.4, 440.0, i * coupure.TRAME)
        coupe = coupe or d.trame([a * 0.3 + b for a, b in zip(hp, voix, strict=True)], hp)
    assert coupe


def test_un_bruit_bref_ne_coupe_pas() -> None:
    d = coupure.DetecteurCoupure(casque=True, annulation=None)
    silence = [0.0] * coupure.TRAME
    resultats = [d.trame(_sinus(0.5), silence) for _ in range(5)]  # 50 ms : une toux
    resultats += [d.trame(silence, silence) for _ in range(20)]
    assert not any(resultats) and d.mode == "casque"


def test_casque_devine_par_le_couplage() -> None:
    d = coupure.DetecteurCoupure(annulation=None)
    d._apm = None
    for i in range(150):  # JARVIS parle fort, le micro n'entend presque rien
        hp = _sinus(0.5, debut=i * coupure.TRAME)
        d.trame([x * 0.005 for x in hp], hp)
    assert d.casque


class FausseAnnulation:
    """APM simulée : retire exactement l'écho (30 % du haut-parleur), garde le délai reçu."""

    def __init__(self) -> None:
        self.delais: list[int] = []

    def nettoyer(self, micro: list[float], haut_parleur: list[float], delai_ms: int) -> list[float]:
        self.delais.append(delai_ms)
        return [m - 0.3 * h for m, h in zip(micro, haut_parleur, strict=True)]


def test_annulation_echo_utilisee_si_disponible() -> None:
    apm = FausseAnnulation()
    d = coupure.DetecteurCoupure(annulation=lambda: apm)  # type: ignore[arg-type, return-value]
    assert d.mode == "annulation_echo"
    for i in range(100):
        hp = _sinus(0.6, debut=i * coupure.TRAME)
        assert not d.trame([x * 0.3 for x in hp], hp)
    coupe = any(
        d.trame([0.3 * a + b for a, b in zip(_sinus(0.6), _sinus(0.1, 440.0), strict=True)], _sinus(0.6))
        for _ in range(20)
    )
    assert coupe and len(apm.delais) == 100 + coupure.TRAMES_DECISION  # coupé dès la 12ᵉ trame
