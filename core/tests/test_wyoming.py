"""Lot 14-D18 : serveur Wyoming, satellites, pièces, profils (faux satellites et faux Home Assistant, 127.0.0.1)."""

from __future__ import annotations

import asyncio
import io
import wave
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from jarvis2 import proprietaire, transcription
from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import ServiceDialogue
from jarvis2.maison.satellites import ServiceSatellites, empreinte
from jarvis2.maison.wyoming import (
    ErreurWyoming,
    Evenement,
    ServeurWyoming,
    adresse_client,
    adresse_ecoute,
    attenuer,
    encoder,
    lire,
    minuteur,
    pcm_depuis_audio,
    wav,
)
from jarvis2.moteurs.telemetrie import EnregistreurMemoire, MoteurInstrumente
from jarvis2.securite import appareils

from .test_securite import ORIGINE, MoteurEspion
from .test_transcription import FauxEmpreinteur

pytestmark = pytest.mark.base


def wav_synthese(niveau: int = 20000, n: int = 5000, taux: int = 22050) -> bytes:
    return wav(np.full(n, niveau, dtype="<i2").tobytes(), taux, 2, 1)


class FauxTranscripteur:
    """Le « texte » entendu est donné d'avance ; l'audio reçu est gardé pour vérifier ce qui est arrivé au PC."""

    def __init__(self, s: proprietaire.ServiceProprietaire | None = None) -> None:
        self.texte = "Jarvis, quelle heure est-il ?"
        self.niveau = 0.5
        self.recus: list[bytes] = []
        self.proprietaire = s

    async def transcrire_detail(self, audio: bytes) -> transcription.Resultat:
        self.recus.append(audio)
        n = 4 * 16000
        r = transcription.Resultat(
            self.texte, "fr", 4.0, 4.0, [], False, {}, np.full(n, self.niveau, dtype=np.float32), [(0, n)]
        )
        if self.proprietaire is not None:  # comme TranscripteurRobuste : chaque phrase est observée
            await self.proprietaire.observer(r)
        return r


class FausseSynthese:
    def __init__(self) -> None:
        self.textes: list[str] = []

    async def dire(self, texte: str) -> Any:
        self.textes.append(texte)

        class Audio:
            donnees = wav_synthese()
            type = "audio/wav"

        return Audio()


class Client:
    """Faux satellite (ou faux Home Assistant) : parle Wyoming sur une vraie connexion TCP locale."""

    def __init__(self, lecteur: asyncio.StreamReader, ecrivain: asyncio.StreamWriter) -> None:
        self.lecteur, self.ecrivain = lecteur, ecrivain

    @classmethod
    async def ouvrir(cls, port: int) -> Client:
        lecteur, ecrivain = await asyncio.open_connection("127.0.0.1", port)
        return cls(lecteur, ecrivain)

    async def envoyer(self, type_: str, data: dict[str, Any] | None = None, charge: bytes | None = None) -> None:
        self.ecrivain.write(encoder(Evenement(type_, data or {}, charge)))
        await self.ecrivain.drain()

    async def recevoir(self, delai: float = 3) -> Evenement | None:
        return await asyncio.wait_for(lire(self.lecteur), delai)

    async def jusqu_a(self, type_: str, delai: float = 3) -> tuple[Evenement, list[Evenement]]:
        vus: list[Evenement] = []
        while True:
            ev = await self.recevoir(delai)
            assert ev is not None, f"connexion fermée avant {type_} ({[v.type for v in vus]})"
            vus.append(ev)
            if ev.type == type_:
                return ev, vus

    async def phrase(self, eveil: bool = True, morceaux: int = 3) -> None:
        if eveil:
            await self.envoyer("detection", {"name": "dis_jarvis"})
        await self.envoyer("audio-start", {"rate": 16000, "width": 2, "channels": 1})
        for _ in range(morceaux):
            await self.envoyer("audio-chunk", {"rate": 16000, "width": 2, "channels": 1}, b"\x01\x00" * 1024)
        await self.envoyer("audio-stop")

    def fermer(self) -> None:
        self.ecrivain.close()


@pytest.fixture
async def wy(pool: Base, tmp_path: Path) -> AsyncIterator[dict[str, Any]]:
    s = proprietaire.ServiceProprietaire(pool, tmp_path, tmp_path, empreinteur=FauxEmpreinteur())
    satellites = ServiceSatellites(pool)
    t, synthese = FauxTranscripteur(s), FausseSynthese()
    reponses: list[tuple[str, str, str | None]] = []

    async def repondre(texte: str, satellite: dict[str, Any], personne: str | None) -> str:
        reponses.append((texte, satellite["id"], personne))
        return "Il est midi."

    serveur = ServeurWyoming(pool, satellites, t, synthese, proprietaire=s, repondre=repondre, deblocage_s=0.6)
    await serveur.charger()
    serveur.reglages.update(actif=True, port=0)  # port éphémère (les vrais réglages : 1024 à 65535)
    await serveur.appliquer()
    assert serveur.port_reel
    try:
        yield {
            "serveur": serveur,
            "satellites": satellites,
            "t": t,
            "synthese": synthese,
            "reponses": reponses,
            "proprietaire": s,
            "port": serveur.port_reel,
        }
    finally:
        await serveur.arreter()


async def satellite_connecte(wy: dict[str, Any], volume: int = 70) -> tuple[Client, dict[str, Any]]:
    fiche, cle = await wy["satellites"].ajouter("Voix du salon", "Salon", volume)
    c = await Client.ouvrir(wy["port"])
    await c.envoyer("jarvis-satellite", {"id": fiche["id"], "cle": cle})
    ok = await c.recevoir()
    assert ok is not None and ok.type == "jarvis-satellite-ok" and ok.data["piece"] == "Salon"
    return c, fiche


# --- Home Assistant comme client Wyoming ------------------------------------------------------------------------


async def test_home_assistant_transcription_et_synthese(wy: dict[str, Any]) -> None:
    c = await Client.ouvrir(wy["port"])  # depuis ce PC : autorisé
    await c.envoyer("describe")
    info = await c.recevoir()
    assert info is not None and info.type == "info"
    assert info.data["asr"][0]["installed"] and "fr" in info.data["asr"][0]["models"][0]["languages"]
    assert info.data["tts"][0]["voices"][0]["name"] == "jarvis2"
    await c.envoyer("transcribe", {"language": "fr"})
    await c.phrase(eveil=False)
    transcript, _ = await c.jusqu_a("transcript")
    assert transcript.data == {"text": "Jarvis, quelle heure est-il ?"}
    with wave.open(io.BytesIO(wy["t"].recus[-1])) as w:  # le PC a reçu un WAV 16 kHz mono de 3 morceaux
        assert w.getframerate() == 16000 and w.getnframes() == 3 * 1024
    await c.envoyer("synthesize", {"text": "Bonjour", "voice": {"name": "jarvis2"}})
    debut, _ = await c.jusqu_a("audio-start")
    assert debut.data["rate"] == 22050
    _, vus = await c.jusqu_a("audio-stop")
    pcm = b"".join(v.payload or b"" for v in vus if v.type == "audio-chunk")
    assert len(pcm) == 5000 * 2 and np.frombuffer(pcm, dtype="<i2").max() == 20000  # Home Assistant : pas de plafond
    assert wy["reponses"] == []  # Home Assistant décide lui-même de la suite
    c.fermer()


async def test_client_non_autorise_et_cle_fausse(wy: dict[str, Any]) -> None:
    wy["serveur"].reglages["clients"] = []
    # Un client distant non listé est refusé (adresse simulée)
    assert wy["serveur"]._client_autorise("192.168.1.50") is False
    wy["serveur"].reglages["clients"] = ["192.168.1.50"]
    assert wy["serveur"]._client_autorise("192.168.1.50") is True
    fiche, _ = await wy["satellites"].ajouter("Cuisine", "Cuisine")
    c = await Client.ouvrir(wy["port"])
    await c.envoyer("jarvis-satellite", {"id": fiche["id"], "cle": "pas-la-bonne"})
    refus = await c.recevoir()
    assert refus is not None and refus.type == "error" and refus.data["code"] == "refuse"
    assert await c.recevoir() is None  # connexion fermée
    # Satellite coupé par l'utilisateur : sa clé ne sert plus
    chambre, cle = await wy["satellites"].ajouter("Chambre", "Chambre")
    assert await wy["satellites"].authentifier(chambre["id"], cle) is not None
    await wy["satellites"].modifier(chambre["id"], actif=False)
    assert await wy["satellites"].authentifier(chambre["id"], cle) is None
    c.fermer()


# --- Satellites ------------------------------------------------------------------------------------------------


async def test_audio_avant_l_eveil_jete(wy: dict[str, Any]) -> None:
    c, _ = await satellite_connecte(wy)
    await c.phrase(eveil=False)  # pas d'éveil : rien n'est transcrit
    await c.envoyer("ping")
    _, vus = await c.jusqu_a("pong")
    assert [v.type for v in vus] == ["pong"] and wy["t"].recus == []
    await c.phrase(eveil=True)
    transcript, _ = await c.jusqu_a("transcript")
    assert transcript.data["text"].startswith("Jarvis") and len(wy["t"].recus) == 1
    c.fermer()


async def test_reponse_presence_et_plafond_de_volume(wy: dict[str, Any], pool: Base) -> None:
    s: proprietaire.ServiceProprietaire = wy["proprietaire"]
    await s.regler(actif=True)
    n = 4 * 16000
    inscription = transcription.Resultat("", "fr", 4, 4, [], False, {}, np.full(n, 0.5, dtype=np.float32), [(0, n)])
    await s.inscrire(inscription)
    c, fiche = await satellite_connecte(wy, volume=50)
    await c.phrase()
    await c.jusqu_a("transcript")
    await c.jusqu_a("audio-start")
    _, vus = await c.jusqu_a("audio-stop")
    pcm = b"".join(v.payload or b"" for v in vus if v.type == "audio-chunk")
    assert int(np.frombuffer(pcm, dtype="<i2").max()) == 10000  # 50 % de 20000
    assert wy["reponses"] == [("Jarvis, quelle heure est-il ?", fiche["id"], "proprietaire")]
    assert wy["synthese"].textes == ["Il est midi."]
    pieces = await wy["satellites"].pieces()
    assert pieces[0]["piece"] == "Salon" and pieces[0]["occupee"] and pieces[0]["personne"] == "Propriétaire"

    # Une autre personne (profil) : présence à son nom, plafond du profil s'il est plus bas
    profil = await wy["satellites"].ajouter_profil("Léa", 20)
    voix_lea = transcription.Resultat("", "fr", 4, 4, [], False, {}, np.full(n, 0.3, dtype=np.float32), [(0, n)])
    await s.inscrire(voix_lea, profil=profil["id"])
    wy["t"].niveau = 0.3
    await c.phrase()
    await c.jusqu_a("transcript")
    _, vus = await c.jusqu_a("audio-stop")
    pcm = b"".join(v.payload or b"" for v in vus if v.type == "audio-chunk")
    assert int(np.frombuffer(pcm, dtype="<i2").max()) == 4000  # 20 % de 20000
    assert wy["reponses"][-1][2] == profil["id"]
    assert (await wy["satellites"].pieces())[0]["personne"] == "Léa"
    # Rien de ce qui a été dit n'est gardé en base : seulement l'heure et la personne
    ligne = await pool.fetchrow("SELECT * FROM satellites_maison WHERE id = $1", fiche["id"])
    assert ligne is not None and "midi" not in str(dict(ligne)) and "heure" not in str(dict(ligne))
    c.fermer()


async def test_deblocage_apres_le_delai(wy: dict[str, Any]) -> None:
    c, _ = await satellite_connecte(wy)
    await c.envoyer("detection", {"name": "dis_jarvis"})
    await c.envoyer("audio-start", {"rate": 16000, "width": 2, "channels": 1})
    await c.envoyer("audio-chunk", {"rate": 16000, "width": 2, "channels": 1}, b"\x00\x00" * 512)
    erreur, _ = await c.jusqu_a("error", delai=3)  # pas d'audio-stop : débloqué (0,6 s dans ce test, 25 s sinon)
    assert erreur.data["code"] == "delai"
    await c.envoyer("audio-stop")  # arrive trop tard : ignoré, rien n'est transcrit
    await c.envoyer("ping")
    await c.jusqu_a("pong")
    assert wy["t"].recus == []
    c.fermer()


async def test_minuteur_sur_le_satellite_d_origine(wy: dict[str, Any]) -> None:
    salon, fiche = await satellite_connecte(wy)
    fiche_cuisine, cle = await wy["satellites"].ajouter("Cuisine", "Cuisine")
    cuisine = await Client.ouvrir(wy["port"])
    await cuisine.envoyer("jarvis-satellite", {"id": fiche_cuisine["id"], "cle": cle})
    await cuisine.recevoir()
    wy["t"].texte = "Jarvis, mets un minuteur de 2 secondes"
    await salon.phrase()
    depart, _ = await salon.jusqu_a("timer-started")
    assert depart.data["total_seconds"] == 2 and depart.data["start_seconds"] == 2
    await salon.jusqu_a("audio-stop")
    assert wy["synthese"].textes == ["Minuteur de 2 secondes lancé."] and wy["reponses"] == []
    fini, _ = await salon.jusqu_a("timer-finished", delai=5)
    assert fini.data["id"] == depart.data["id"]
    await cuisine.envoyer("ping")
    _, vus_cuisine = await cuisine.jusqu_a("pong")
    assert [v.type for v in vus_cuisine] == ["pong"]  # rien n'a sonné dans la cuisine
    salon.fermer()
    cuisine.fermer()
    assert fiche["piece"] == "Salon"


# --- API ------------------------------------------------------------------------------------------------------


async def test_api_satellites_pieces_profils(pool: Base, tmp_path: Path) -> None:
    depot = DepotConversations(pool)
    moteurs = {"espion": MoteurInstrumente(MoteurEspion(), EnregistreurMemoire())}
    ctx = Contexte(
        pool, depot, moteurs, ServiceDialogue(depot, moteurs, "espion"), "espion",
        dossier_donnees=tmp_path, dossier_modeles=tmp_path,
    )  # fmt: skip
    app = creer_app(Parametres(), ctx)
    app.state.ctx = ctx
    _, jeton = await appareils.creer(pool, "PC", "pc")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGINE,
        headers={"Authorization": f"Bearer {jeton}", "Origin": ORIGINE},
    ) as client:
        etat = (await client.get("/v1/maison/wyoming")).json()
        assert etat["actif"] is False and etat["en_ecoute"] is False and etat["hote"] == "127.0.0.1"
        publique = await client.put("/v1/maison/wyoming", json={"hote": "8.8.8.8"})
        assert publique.status_code == 422
        assert (await client.put("/v1/maison/wyoming", json={"clients": ["93.184.216.34"]})).status_code == 422
        ok = await client.put("/v1/maison/wyoming", json={"clients": ["192.168.1.30"], "port": 10399})
        assert ok.status_code == 200 and ok.json()["clients"] == ["192.168.1.30"] and not ok.json()["en_ecoute"]

        ajout = (await client.post("/v1/maison/satellites", json={"nom": "Voix du salon", "piece": "Salon"})).json()
        cle, ident = ajout["cle"], ajout["satellite"]["id"]
        assert len(cle) >= 40 and ajout["satellite"]["volume_max"] == 70
        liste = await client.get("/v1/maison/satellites")
        assert cle not in liste.text and liste.json()["satellites"][0]["id"] == ident
        ligne = await pool.fetchrow("SELECT empreinte_cle FROM satellites_maison WHERE id = $1", ident)
        assert ligne is not None and ligne["empreinte_cle"] == empreinte(cle)
        assert (await client.put(f"/v1/maison/satellites/{ident}", json={"volume_max": 40})).json()["satellite"][
            "volume_max"
        ] == 40
        assert (await client.put(f"/v1/maison/satellites/{ident}", json={"volume_max": 140})).status_code == 422
        pieces = (await client.get("/v1/maison/pieces")).json()["pieces"]
        assert pieces == [{"piece": "Salon", "satellites": 1, "vu_le": None, "personne": None, "occupee": False}]

        profil = (await client.post("/v1/maison/profils", json={"nom": "Léa", "volume_max": 30})).json()["profil"]
        liste_profils = (await client.get("/v1/maison/profils")).json()
        assert liste_profils["profils"][0]["empreintes"] == 0 and liste_profils["reconnaissance"]["actif"] is False
        assert (await client.delete(f"/v1/maison/profils/{profil['id']}")).status_code == 200
        assert (await client.delete(f"/v1/maison/satellites/{ident}")).status_code == 200
        assert (await client.delete(f"/v1/maison/satellites/{ident}")).status_code == 404
        details = [str(r["details"]) for r in await pool.fetch("SELECT details FROM audit")]
        assert not any(cle in d for d in details)


# --- Fonctions pures -------------------------------------------------------------------------------------------


async def test_protocole_et_fonctions_pures() -> None:
    lecteur = asyncio.StreamReader()
    lecteur.feed_data(encoder(Evenement("audio-chunk", {"rate": 16000}, b"abcd")))
    lecteur.feed_data(b'{"type": "describe"}\n')
    lecteur.feed_data(b'{"type": "transcript", "data": {"text": "inline"}}\n')
    lecteur.feed_eof()
    a = await lire(lecteur)
    assert a is not None and a.type == "audio-chunk" and a.data == {"rate": 16000} and a.payload == b"abcd"
    b = await lire(lecteur)
    assert b is not None and b.type == "describe"
    c = await lire(lecteur)
    assert c is not None and c.data == {"text": "inline"}
    assert await lire(lecteur) is None
    trop = asyncio.StreamReader()
    trop.feed_data(b'{"type": "audio-chunk", "payload_length": 99999999}\n')
    with pytest.raises(ErreurWyoming):
        await lire(trop)

    assert minuteur("Jarvis, minuteur de 5 minutes") == 300
    assert minuteur("mets un timer de deux heures") == 7200
    assert minuteur("Minuteur pour 30 secondes s'il te plaît") == 30
    assert minuteur("quelle heure est-il") is None
    pcm, taux = pcm_depuis_audio(wav_synthese(n=10))
    assert taux == 22050 and len(pcm) == 20
    assert np.frombuffer(attenuer(pcm, 25), dtype="<i2").tolist() == [5000] * 10
    assert attenuer(pcm, 100) == pcm
    assert adresse_ecoute("0.0.0.0") == "0.0.0.0"  # noqa: S104 and adresse_client("192.168.1.30") == "192.168.1.30"
    for mauvaise in ("8.8.8.8", "pc.exemple.com"):
        with pytest.raises(ErreurWyoming):
            adresse_ecoute(mauvaise)
    with pytest.raises(ErreurWyoming):
        adresse_client("0.0.0.0")  # noqa: S104
