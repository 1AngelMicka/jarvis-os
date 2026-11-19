"""Protocole Wyoming : la transcription et la synthèse de JARVIS offertes à Home Assistant et aux satellites.

Le PC reste le cerveau : Home Assistant (intégration Wyoming) et les satellites lui envoient l'audio, JARVIS
transcrit (`transcription.py`, Whisper local), répond et parle (`synthese.py`, Piper local ou la voix choisie).

Protocole (wyoming 1.x) : chaque événement est une ligne JSON `{"type", "data_length", "payload_length"}`, suivie de
`data_length` octets de données JSON et de `payload_length` octets de charge (audio PCM). Événements servis :
`describe` → `info` ; `transcribe` + `audio-start` / `audio-chunk` / `audio-stop` → `transcript` ;
`synthesize` → `audio-start` / `audio-chunk` / `audio-stop` ; `ping` → `pong`.

**Désactivé par défaut** (clé `wyoming` de `etat_systeme`, migration 026) ; écoute sur 127.0.0.1 tant que
l'utilisateur ne choisit pas une autre adresse du réseau local.

Qui peut parler au serveur :
- **Home Assistant** (ou tout client Wyoming sans extension) : seulement depuis une adresse autorisée par
  l'utilisateur (`clients`), ou depuis ce PC ;
- **un satellite** : premier événement `jarvis-satellite` `{"id", "cle"}` (extension de JARVIS) — une clé par
  appareil, vérifiée par son empreinte. Sinon la connexion est fermée.

Session d'un satellite :
- **seul l'audio après l'éveil compte** : le satellite détecte le mot d'éveil lui-même (`detection` ou
  `run-pipeline`) ; tout `audio-chunk` reçu avant est jeté sans être lu ni gardé ;
- **déblocage après 25 s** : sans fin de phrase (`audio-stop`) 25 s après l'éveil, la session repart en veille et le
  satellite reçoit `error` (code `delai`), pour ne jamais rester bloqué en écoute ;
- **présence par pièce** : chaque phrase note la pièce, l'heure et la personne reconnue à la voix ;
- **plafond de volume** : la voix renvoyée est atténuée au plus bas des plafonds (satellite, profil) ;
- **minuteurs sur le satellite d'origine** : « minuteur de 5 minutes » est compris sur place (sans IA), et
  `timer-started` puis `timer-finished` partent vers CE satellite, pas ailleurs.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import ipaddress
import json
import logging
import re
import secrets
import time
import wave
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .. import __version__
from ..voix import sans_accents

if TYPE_CHECKING:
    from ..db import Base
    from .satellites import ServiceSatellites

journal = logging.getLogger("jarvis2.wyoming")

CLE_ETAT = "wyoming"
REGLAGES_DEFAUT: dict[str, Any] = {"actif": False, "hote": "127.0.0.1", "port": 10300, "clients": []}
VERSION = "1.5.4"
LIGNE_MAX = 64 * 1024
DONNEES_MAX = 64 * 1024
CHARGE_MAX = 1024 * 1024
AUDIO_MAX_S = 30.0  # une phrase : 30 s au plus
DEBLOCAGE_S = 25.0
INACTIVITE_S = 300.0  # sans aucun événement pendant 5 minutes : connexion fermée
MORCEAU = 2048  # échantillons par audio-chunk envoyé

Repondre = Callable[[str, dict[str, Any], str | None], Awaitable[str]]


@dataclass
class Evenement:
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    payload: bytes | None = None


class ErreurWyoming(Exception):
    pass


async def lire(lecteur: asyncio.StreamReader) -> Evenement | None:
    """Un événement, ou None à la fin du flux. Tailles bornées : une ligne trop longue ferme la connexion."""
    try:
        ligne = await lecteur.readuntil(b"\n")
    except asyncio.IncompleteReadError as exc:
        if not exc.partial.strip():
            return None
        raise ErreurWyoming("Événement tronqué") from exc
    except asyncio.LimitOverrunError as exc:
        raise ErreurWyoming("En-tête trop long") from exc
    try:
        entete = json.loads(ligne)
    except ValueError as exc:
        raise ErreurWyoming("En-tête illisible") from exc
    if not isinstance(entete, dict) or not isinstance(entete.get("type"), str):
        raise ErreurWyoming("En-tête sans type")
    data = entete.get("data") if isinstance(entete.get("data"), dict) else {}
    longueur_donnees = int(entete.get("data_length") or 0)
    longueur_charge = int(entete.get("payload_length") or 0)
    if not 0 <= longueur_donnees <= DONNEES_MAX or not 0 <= longueur_charge <= CHARGE_MAX:
        raise ErreurWyoming("Événement trop gros")
    if longueur_donnees:
        try:
            supplement = json.loads(await lecteur.readexactly(longueur_donnees))
        except ValueError as exc:
            raise ErreurWyoming("Données illisibles") from exc
        if isinstance(supplement, dict):
            data = {**data, **supplement}
    charge = await lecteur.readexactly(longueur_charge) if longueur_charge else None
    return Evenement(str(entete["type"])[:64], data, charge)


def encoder(ev: Evenement) -> bytes:
    donnees = json.dumps(ev.data, ensure_ascii=False).encode() if ev.data else b""
    entete: dict[str, Any] = {"type": ev.type, "version": VERSION}
    if donnees:
        entete["data_length"] = len(donnees)
    if ev.payload:
        entete["payload_length"] = len(ev.payload)
    return json.dumps(entete).encode() + b"\n" + donnees + (ev.payload or b"")


def wav(pcm: bytes, taux: int, largeur: int, canaux: int) -> bytes:
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as w:
        w.setnchannels(canaux)
        w.setsampwidth(largeur)
        w.setframerate(taux)
        w.writeframes(pcm)
    return tampon.getvalue()


def pcm_depuis_audio(donnees: bytes) -> tuple[bytes, int]:
    """Audio de la synthèse → PCM 16 bits mono et son taux. WAV lu directement ; autre format (MP3) par PyAV."""
    try:
        with wave.open(io.BytesIO(donnees), "rb") as w:
            if w.getsampwidth() == 2 and w.getnchannels() == 1:
                return w.readframes(w.getnframes()), w.getframerate()
    except (wave.Error, EOFError):
        pass
    import numpy as np

    from ..voix import decoder_audio

    echantillons = decoder_audio(donnees)  # 16 kHz mono, flottants
    return (np.clip(echantillons, -1, 1) * 32767).astype("<i2").tobytes(), 16000


def attenuer(pcm: bytes, volume: int) -> bytes:
    """Plafond de volume : échantillons 16 bits multipliés par volume / 100."""
    if volume >= 100:
        return pcm
    import numpy as np

    echantillons = np.frombuffer(pcm, dtype="<i2").astype(np.float32) * (max(0, volume) / 100)
    return echantillons.astype("<i2").tobytes()


# --- Minuteurs (compris sans IA) ----------------------------------------------------------------------------------

UNITES = {"seconde": 1, "minute": 60, "heure": 3600}
NOMBRES = {"une": 1, "un": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "dix": 10, "quinze": 15}
MINUTEUR = re.compile(
    r"\b(?:minuteur|timer|chrono|compte a rebours)\b(?:\s+de|\s+pour|\s+dans)?\s+(\d{1,3}|"
    + "|".join(NOMBRES)
    + r")\s*(seconde|minute|heure)s?\b"
)


def minuteur(texte: str) -> int | None:
    """« Jarvis, minuteur de 5 minutes » → 300 (secondes) ; None si la phrase n'en demande pas."""
    trouve = MINUTEUR.search(sans_accents(texte).lower())
    if trouve is None:
        return None
    nombre = int(trouve.group(1)) if trouve.group(1).isdigit() else NOMBRES[trouve.group(1)]
    total = nombre * UNITES[trouve.group(2)]
    return total if 0 < total <= 24 * 3600 else None


def duree_lisible(secondes: int) -> str:
    if secondes % 3600 == 0:
        n, unite = secondes // 3600, "heure"
    elif secondes % 60 == 0:
        n, unite = secondes // 60, "minute"
    else:
        n, unite = secondes, "seconde"
    return f"{n} {unite}{'s' if n > 1 else ''}"


# --- Réglages ----------------------------------------------------------------------------------------------------


def adresse_ecoute(hote: str) -> str:
    """Adresse d'écoute : ce PC ou une adresse du réseau local (jamais une adresse publique)."""
    try:
        ip = ipaddress.ip_address(hote.strip())
    except ValueError as exc:
        raise ErreurWyoming("Adresse d'écoute invalide (ex. 127.0.0.1 ou l'adresse du PC sur le réseau local)") from exc
    if not (ip.is_loopback or ip.is_private or ip.is_unspecified):
        raise ErreurWyoming("Adresse d'écoute refusée : ce PC ou le réseau local seulement")
    return str(ip)


def adresse_client(hote: str) -> str:
    try:
        ip = ipaddress.ip_address(hote.strip())
    except ValueError as exc:
        raise ErreurWyoming("Adresse de client invalide : une adresse IP est attendue") from exc
    if not (ip.is_loopback or ip.is_private) or ip.is_unspecified:
        raise ErreurWyoming("Client refusé : seulement une adresse du réseau local")
    return str(ip)


# --- Serveur -----------------------------------------------------------------------------------------------------


@dataclass
class _Session:
    ecrivain: asyncio.StreamWriter
    satellite: dict[str, Any] | None = None
    eveille: bool = False
    limite: float | None = None  # échéance du déblocage (25 s après l'éveil)
    audio: bytearray = field(default_factory=bytearray)
    format: tuple[int, int, int] = (16000, 2, 1)
    jetes: int = 0  # morceaux reçus avant l'éveil : jetés sans être lus

    async def envoyer(self, ev: Evenement) -> None:
        self.ecrivain.write(encoder(ev))
        await self.ecrivain.drain()


class ServeurWyoming:
    def __init__(
        self,
        pool: Base,
        satellites: ServiceSatellites,
        transcripteur: Any,
        synthese: Any,
        *,
        proprietaire: Any = None,
        repondre: Repondre | None = None,
        horloge: Callable[[], float] = time.monotonic,
        deblocage_s: float = DEBLOCAGE_S,
    ) -> None:
        self.pool = pool
        self.satellites = satellites
        self.transcripteur = transcripteur
        self.synthese = synthese
        self.proprietaire = proprietaire
        self.repondre = repondre
        self.horloge = horloge
        self.deblocage_s = deblocage_s
        self.reglages: dict[str, Any] = dict(REGLAGES_DEFAUT)
        self.serveur: asyncio.Server | None = None
        self.port_reel: int | None = None
        self._ecoute: str | None = None
        self._connectes: dict[str, _Session] = {}  # satellite → session ouverte (minuteurs)
        self._minuteurs: dict[str, asyncio.Task[None]] = {}

    # -- réglages ----------------------------------------------------------------------------------------------------

    async def charger(self) -> dict[str, Any]:
        brut = await self.pool.fetchval("SELECT valeur FROM etat_systeme WHERE cle = $1", CLE_ETAT)
        valeur = json.loads(brut) if isinstance(brut, str) else (brut or {})
        self.reglages = {**REGLAGES_DEFAUT, **{k: v for k, v in dict(valeur).items() if k in REGLAGES_DEFAUT}}
        return self.reglages

    async def regler(
        self,
        actif: bool | None = None,
        hote: str | None = None,
        port: int | None = None,
        clients: list[str] | None = None,
    ) -> dict[str, Any]:
        reglages = dict(self.reglages)
        if hote is not None:
            reglages["hote"] = adresse_ecoute(hote)
        if port is not None:
            if not 1024 <= int(port) <= 65535:
                raise ErreurWyoming("Port : de 1024 à 65535")
            reglages["port"] = int(port)
        if clients is not None:
            if len(clients) > 10:
                raise ErreurWyoming("10 clients au plus")
            reglages["clients"] = sorted({adresse_client(c) for c in clients})
        if actif is not None:
            reglages["actif"] = bool(actif)
        # Ligne créée par la migration 026 : le rôle applicatif n'écrit que par UPDATE
        await self.pool.execute(
            "UPDATE etat_systeme SET valeur = $2::text::jsonb, maj_le = now() WHERE cle = $1",
            CLE_ETAT,
            json.dumps(reglages),
        )
        self.reglages = reglages
        await self.appliquer()
        return reglages

    def decrire(self) -> dict[str, Any]:
        return {
            **self.reglages,
            "en_ecoute": self.serveur is not None,
            "port_reel": self.port_reel,
            "satellites_connectes": sorted(self._connectes),
        }

    # -- cycle de vie ------------------------------------------------------------------------------------------------

    async def appliquer(self) -> None:
        """Démarre ou arrête l'écoute selon les réglages (relancée si l'adresse ou le port change)."""
        voulu = (self.reglages["hote"], int(self.reglages["port"])) if self.reglages["actif"] else None
        actuel = (self._ecoute, self.port_reel) if self.serveur is not None else None
        if self.serveur is not None and (voulu is None or voulu != actuel):
            await self.arreter()
        if voulu is not None and self.serveur is None:
            try:
                self.serveur = await asyncio.start_server(self._client, voulu[0], voulu[1], limit=LIGNE_MAX)
            except OSError as exc:
                raise ErreurWyoming(f"Écoute impossible sur le port {voulu[1]} : {exc.strerror or exc}") from exc
            self.port_reel = int(self.serveur.sockets[0].getsockname()[1])
            self._ecoute = voulu[0]
            journal.info("Wyoming : écoute sur %s:%s", voulu[0], self.port_reel)

    async def arreter(self) -> None:
        for tache in self._minuteurs.values():
            tache.cancel()
        self._minuteurs.clear()
        if self.serveur is not None:
            self.serveur.close()
            for session in list(self._connectes.values()):
                session.ecrivain.close()
            self._connectes.clear()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.serveur.wait_closed(), 2)
        self.serveur, self.port_reel, self._ecoute = None, None, None

    # -- connexion ---------------------------------------------------------------------------------------------------

    def _client_autorise(self, hote: str) -> bool:
        try:
            ip = ipaddress.ip_address(hote)
        except ValueError:
            return False
        return ip.is_loopback or str(ip) in self.reglages.get("clients", [])

    async def _client(self, lecteur: asyncio.StreamReader, ecrivain: asyncio.StreamWriter) -> None:
        pair = ecrivain.get_extra_info("peername")
        hote = str(pair[0]) if pair else ""
        session = _Session(ecrivain)
        try:
            premier = await asyncio.wait_for(lire(lecteur), 10)
            if premier is None:
                return
            if premier.type == "jarvis-satellite":
                satellite = await self.satellites.authentifier(
                    str(premier.data.get("id", "")), str(premier.data.get("cle", ""))
                )
                if satellite is None:
                    journal.warning("Wyoming : satellite refusé (clé ou identifiant inconnu)")
                    await session.envoyer(Evenement("error", {"text": "Satellite non autorisé", "code": "refuse"}))
                    return
                session.satellite = satellite
                ancien = self._connectes.get(satellite["id"])
                if ancien is not None:
                    ancien.ecrivain.close()
                self._connectes[satellite["id"]] = session
                await session.envoyer(Evenement("jarvis-satellite-ok", {"piece": satellite["piece"]}))
            elif not self._client_autorise(hote):
                journal.warning("Wyoming : client refusé (adresse non autorisée)")
                await session.envoyer(Evenement("error", {"text": "Client non autorisé", "code": "refuse"}))
                return
            else:
                await self._traiter(session, premier)
            while True:
                delai = INACTIVITE_S
                if session.limite is not None:
                    delai = max(0.0, session.limite - self.horloge())
                try:
                    ev = await asyncio.wait_for(lire(lecteur), delai)
                except TimeoutError:
                    if session.limite is None:
                        return  # inactivité
                    await self._debloquer(session)
                    continue
                if ev is None:
                    return
                if session.limite is not None and self.horloge() >= session.limite:
                    await self._debloquer(session)
                await self._traiter(session, ev)
        except (ErreurWyoming, asyncio.IncompleteReadError, ConnectionError, TimeoutError) as exc:
            journal.info("Wyoming : connexion fermée (%s)", type(exc).__name__)
        finally:
            if session.satellite is not None and self._connectes.get(session.satellite["id"]) is session:
                del self._connectes[session.satellite["id"]]
            ecrivain.close()

    async def _debloquer(self, session: _Session) -> None:
        """Déblocage : 25 s sans fin de phrase après l'éveil → retour en veille, le satellite est prévenu."""
        session.eveille, session.limite = False, None
        session.audio.clear()
        await session.envoyer(Evenement("error", {"text": "Délai dépassé : retour en veille", "code": "delai"}))

    async def _traiter(self, session: _Session, ev: Evenement) -> None:
        t = ev.type
        if t == "describe":
            await session.envoyer(Evenement("info", self.info()))
        elif t == "ping":
            await session.envoyer(Evenement("pong", {"text": ev.data.get("text")} if ev.data.get("text") else {}))
        elif t in ("detection", "run-pipeline") and session.satellite is not None:
            session.eveille, session.limite = True, self.horloge() + self.deblocage_s
            session.audio.clear()
        elif t == "transcribe" and session.satellite is None:
            session.eveille = True  # Home Assistant : l'éveil a eu lieu de son côté
        elif t == "audio-start":
            session.format = (
                int(ev.data.get("rate", 16000)),
                int(ev.data.get("width", 2)),
                int(ev.data.get("channels", 1)),
            )
            session.audio.clear()
        elif t == "audio-chunk":
            if not session.eveille:
                session.jetes += 1  # avant l'éveil : jeté sans être lu ni gardé
                return
            taux, largeur, canaux = session.format
            if len(session.audio) + len(ev.payload or b"") > AUDIO_MAX_S * taux * largeur * canaux:
                await self._debloquer(session)
                return
            session.audio.extend(ev.payload or b"")
        elif t == "audio-stop":
            if not session.eveille:
                return
            await self._fin_de_phrase(session)
        elif t == "synthesize" and session.satellite is None:
            await self._dire(session, str(ev.data.get("text", ""))[:2000], 100)
        elif t == "timer-cancelled" and session.satellite is not None:
            tache = self._minuteurs.pop(str(ev.data.get("id", "")), None)
            if tache is not None:
                tache.cancel()

    def info(self) -> dict[str, Any]:
        attribution = {"name": "JARVIS 2", "url": "https://github.com/1AngelMicka/jarvis-os"}
        return {
            "asr": [
                {
                    "name": "jarvis2-transcription",
                    "description": "Transcription de JARVIS 2 (Whisper, sur le PC)",
                    "attribution": attribution,
                    "installed": True,
                    "version": __version__,
                    "models": [
                        {
                            "name": "whisper",
                            "description": "Whisper (faster-whisper), local",
                            "attribution": attribution,
                            "installed": True,
                            "version": __version__,
                            "languages": ["fr", "en"],
                        }
                    ],
                }
            ],
            "tts": [
                {
                    "name": "jarvis2-synthese",
                    "description": "Voix de JARVIS 2 (Piper sur le PC, ou la voix choisie)",
                    "attribution": attribution,
                    "installed": True,
                    "version": __version__,
                    "voices": [
                        {
                            "name": "jarvis2",
                            "description": "Voix choisie dans Voix & écoute",
                            "attribution": attribution,
                            "installed": True,
                            "version": __version__,
                            "languages": ["fr"],
                        }
                    ],
                }
            ],
        }

    async def _fin_de_phrase(self, session: _Session) -> None:
        taux, largeur, canaux = session.format
        audio = wav(bytes(session.audio), taux, largeur, canaux)
        session.audio.clear()
        session.eveille, session.limite = False, None
        try:
            resultat = await self.transcripteur.transcrire_detail(audio)
            texte = str(resultat.texte or "")
        except Exception as exc:
            journal.warning("Wyoming : transcription impossible (%s)", type(exc).__name__)
            await session.envoyer(Evenement("error", {"text": "Transcription impossible", "code": "transcription"}))
            return
        await session.envoyer(Evenement("transcript", {"text": texte}))
        if session.satellite is None or not texte:
            return
        await self._phrase_du_satellite(session, session.satellite, texte)

    async def _phrase_du_satellite(self, session: _Session, satellite: dict[str, Any], texte: str) -> None:
        """Présence, minuteur ou réponse de JARVIS, dite sur le satellite d'origine au plafond de volume."""
        personne, volume = None, int(satellite["volume_max"])
        attestation = self.proprietaire.attestation(texte) if self.proprietaire is not None else None
        if attestation is not None:
            if attestation.profil:
                personne = attestation.profil
            elif attestation.verdict == "reconnu":
                personne = "proprietaire"
        profil = await self.satellites.profil(personne) if personne and personne != "proprietaire" else None
        if profil is not None:
            volume = min(volume, int(profil["volume_max"]))
        await self.satellites.vu(satellite["id"], personne)
        secondes = minuteur(texte)
        if secondes is not None:
            await self.lancer_minuteur(satellite["id"], secondes)
            await self._dire(session, f"Minuteur de {duree_lisible(secondes)} lancé.", volume)
            return
        if self.repondre is None:
            return
        try:
            reponse = await self.repondre(texte, satellite, personne)
        except Exception:
            journal.exception("Wyoming : réponse impossible")
            reponse = "Désolé, je n'ai pas pu répondre."
        if reponse:
            await self._dire(session, reponse, volume)

    async def _dire(self, session: _Session, texte: str, volume: int) -> None:
        if not texte.strip():
            return
        try:
            audio = await self.synthese.dire(texte)
            pcm, taux = pcm_depuis_audio(audio.donnees)
        except Exception as exc:
            journal.warning("Wyoming : synthèse impossible (%s)", type(exc).__name__)
            await session.envoyer(Evenement("error", {"text": "Synthèse impossible", "code": "synthese"}))
            return
        pcm = attenuer(pcm, volume)
        await session.envoyer(Evenement("audio-start", {"rate": taux, "width": 2, "channels": 1}))
        pas = MORCEAU * 2
        for debut in range(0, len(pcm), pas):
            await session.envoyer(
                Evenement("audio-chunk", {"rate": taux, "width": 2, "channels": 1}, pcm[debut : debut + pas])
            )
        await session.envoyer(Evenement("audio-stop"))

    # -- minuteurs ---------------------------------------------------------------------------------------------------

    async def lancer_minuteur(self, satellite: str, secondes: int) -> str:
        ident = secrets.token_hex(6)
        session = self._connectes.get(satellite)
        if session is not None:
            await session.envoyer(
                Evenement(
                    "timer-started",
                    {
                        "id": ident,
                        "total_seconds": secondes,
                        "name": duree_lisible(secondes),
                        "start_hours": secondes // 3600,
                        "start_minutes": secondes % 3600 // 60,
                        "start_seconds": secondes % 60,
                    },
                )
            )

        async def sonner() -> None:
            await asyncio.sleep(secondes)
            self._minuteurs.pop(ident, None)
            cible = self._connectes.get(satellite)  # le satellite d'origine, même reconnecté entre-temps
            if cible is not None:
                with contextlib.suppress(ConnectionError, OSError):
                    await cible.envoyer(Evenement("timer-finished", {"id": ident}))

        self._minuteurs[ident] = asyncio.create_task(sonner())
        return ident
