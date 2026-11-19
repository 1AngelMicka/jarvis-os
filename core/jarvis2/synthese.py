"""Synthèse vocale au choix : voix du navigateur (locale), Piper (neuronale, locale) ou ElevenLabs (en ligne).

- **Navigateur** (défaut) : l'interface lit avec les voix LOCALES du système ; rien ne passe par ici.
- **Piper** : voix neuronale française sur le PC, dans un **processus séparé** (un par phrase, au plus
  `PIPER_SIMULTANES` à la fois) : un plantage ou une lenteur de Piper n'atteint jamais le Core. Le programme
  `piper` est cherché (`JARVIS2_PIPER`, dossier des modèles, PATH) ; la voix (`.onnx` + `.onnx.json`) n'est
  téléchargée que sur accord, par `telechargements.py`.
- **ElevenLabs** : voix en ligne, avec la clé de l'utilisateur rangée dans le coffre local (jamais renvoyée).
  Avant l'envoi : secrets ET données personnelles masqués, et une phrase bâtie sur un sujet ou des souvenirs
  privés ne part pas (lue par une voix locale à la place) : la même barrière que pour les IA externes.

Les secrets sont masqués avant TOUTE lecture à voix haute, locale comprise (une clé lue à voix haute s'entend).
L'interface garde la voix du système en secours : si le moteur choisi échoue, la phrase est dite quand même.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import sys
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import httpx

from . import telechargements
from .securite.filtre import _ETIQUETTES, masquer, masquer_secrets

if TYPE_CHECKING:
    from .db import Base
    from .securite.coffre import Coffre

journal = logging.getLogger("jarvis2.synthese")

Moteur = Literal["navigateur", "piper", "elevenlabs"]
MOTEURS: tuple[Moteur, ...] = ("navigateur", "piper", "elevenlabs")
CLE_COFFRE = "elevenlabs"  # nom de la clé ElevenLabs dans le coffre local
URL_ELEVENLABS = "https://api.elevenlabs.io"
MODELE_ELEVENLABS = "eleven_multilingual_v2"  # parle français avec n'importe quelle voix
VOIX_ELEVENLABS_DEFAUT = "21m00Tcm4TlvDq8ikWAM"  # voix prédéfinie de la bibliothèque ElevenLabs
DEPOT_PIPER = "rhasspy/piper-voices"
PIPER_SIMULTANES = 2  # phrases synthétisées en parallèle (l'interface les lit dans l'ordre)
DELAI_PIPER = 30.0
DELAI_ELEVENLABS = 20.0
LONGUEUR_MAX = 1200  # une phrase, pas un livre : au-delà, l'interface découpe
SECRET_DIT = "(secret masqué)"  # noqa: S105 (texte dit à la place d'un secret)


@dataclass(frozen=True)
class VoixPiper:
    id: str
    nom: str
    chemin: str  # dans le dépôt rhasspy/piper-voices
    taille: int  # octets, environ (modèle + description)


# Voix françaises de Piper (qualité « medium », ~63 Mo chacune)
VOIX_PIPER: dict[str, VoixPiper] = {
    v.id: v
    for v in (
        VoixPiper("fr_FR-siwis-medium", "Siwis (femme)", "fr/fr_FR/siwis/medium", 63_500_000),
        VoixPiper("fr_FR-tom-medium", "Tom (homme)", "fr/fr_FR/tom/medium", 63_500_000),
        VoixPiper("fr_FR-upmc-medium", "UPMC (deux voix)", "fr/fr_FR/upmc/medium", 76_800_000),
    )
}
VOIX_PIPER_DEFAUT = "fr_FR-siwis-medium"

REGLAGES_DEFAUT: dict[str, Any] = {
    "moteur": "navigateur",
    "voix_piper": VOIX_PIPER_DEFAUT,
    "voix_elevenlabs": VOIX_ELEVENLABS_DEFAUT,
    "coupure": True,  # couper la lecture quand l'utilisateur parle par-dessus (mains libres)
}
_ID_VOIX_ELEVENLABS = re.compile(r"^[A-Za-z0-9]{8,40}$")


class ErreurSynthese(Exception):
    """La phrase n'a pas pu être synthétisée par ce moteur : l'interface la dit avec la voix du système."""


class PhrasePrivee(ErreurSynthese):
    """Phrase bâtie sur un sujet ou des souvenirs privés : elle ne part pas vers une voix en ligne."""


# --- Texte lu à voix haute -----------------------------------------------------------------------------------------


def _dire_etiquettes(texte: str) -> str:
    """« [SECRET : clé OpenAI] » se dit « (secret masqué) » : jamais la valeur, ni un crochet épelé."""
    return _ETIQUETTES.sub(SECRET_DIT, texte)


def texte_a_dire(texte: str, *, externe: bool = False) -> str:
    """Texte prêt à lire : mise en forme retirée, secrets masqués (et données personnelles pour une voix en ligne)."""
    # Masquer AVANT de retirer la mise en forme : « ghp_… » ou « sk_live_… » perdraient sinon leur forme reconnaissable
    propre = re.sub(r"\*\*|__|`", "", texte)
    masque = masquer(propre).texte if externe else masquer_secrets(propre)
    dit = _dire_etiquettes(masque)
    return " ".join(re.sub(r"[*_`#>|]", " ", dit).split())


# --- Réglages (etat_systeme, clé « synthese ») ---------------------------------------------------------------------


def normaliser(valeur: Any) -> dict[str, Any]:
    reglages = dict(REGLAGES_DEFAUT)
    if isinstance(valeur, dict):
        if valeur.get("moteur") in MOTEURS:
            reglages["moteur"] = valeur["moteur"]
        if valeur.get("voix_piper") in VOIX_PIPER:
            reglages["voix_piper"] = valeur["voix_piper"]
        voix = valeur.get("voix_elevenlabs")
        if isinstance(voix, str) and _ID_VOIX_ELEVENLABS.match(voix):
            reglages["voix_elevenlabs"] = voix
        if isinstance(valeur.get("coupure"), bool):
            reglages["coupure"] = valeur["coupure"]
    return reglages


async def lire_reglages(base: Base) -> dict[str, Any]:
    valeur = await base.fetchval("SELECT valeur FROM etat_systeme WHERE cle = 'synthese'")
    if isinstance(valeur, str):
        valeur = json.loads(valeur)
    return normaliser(valeur)


async def ecrire_reglages(base: Base, reglages: dict[str, Any]) -> dict[str, Any]:
    propre = normaliser(reglages)
    await base.execute(
        "UPDATE etat_systeme SET valeur = $1::text::jsonb, maj_le = now() WHERE cle = 'synthese'", json.dumps(propre)
    )
    return propre


# --- Piper : programme et voix --------------------------------------------------------------------------------------


def dossier_voix_piper(dossier_modeles: Path, ident: str) -> Path:
    return dossier_modeles / "piper" / ident


def modele_piper(dossier_modeles: Path, ident: str, hub: str = telechargements.HUB) -> telechargements.Modele:
    """Voix Piper téléchargeable (modèle ONNX + description) : seulement sur accord de l'utilisateur."""
    voix = VOIX_PIPER[ident]
    motifs = [f"{voix.chemin}/{ident}.onnx", f"{voix.chemin}/{ident}.onnx.json"]
    resoudre_hub = telechargements.fichiers_hugging_face(DEPOT_PIPER, motifs, hub)

    def resoudre(client: httpx.Client) -> list[telechargements.Fichier]:
        # Rangés à plat dans le dossier de la voix (« fr_FR-siwis-medium.onnx »), sans l'arborescence du dépôt
        return [telechargements.Fichier(Path(f.chemin).name, f.url, f.taille, f.sha256) for f in resoudre_hub(client)]

    return telechargements.Modele(
        "piper",
        f"Voix Piper ({voix.nom})",
        ident,
        dossier_voix_piper(dossier_modeles, ident),
        resoudre,
        taille_estimee=voix.taille,
    )


def trouver_piper(commande: str, dossier_modeles: Path) -> Path | None:
    """Le programme Piper : `JARVIS2_PIPER`, sinon `<modèles>/piper/piper[.exe]`, sinon le PATH. Jamais téléchargé
    ni installé par JARVIS (c'est un exécutable : l'utilisateur choisit de l'installer)."""
    nom = "piper.exe" if sys.platform == "win32" else "piper"
    candidats: list[Path] = []
    if commande:
        candidats.append(Path(commande))
    candidats += [dossier_modeles / "piper" / nom, dossier_modeles / "piper" / "piper" / nom]
    for c in candidats:
        if c.is_file():
            return c
    trouve = shutil.which("piper")
    return Path(trouve) if trouve else None


Executeur = Callable[[list[str], bytes, float], Awaitable[tuple[int, bytes]]]


async def _executer(arguments: list[str], entree: bytes, delai: float) -> tuple[int, bytes]:
    """Lance Piper dans son propre processus ; le texte part sur l'entrée standard (jamais dans la ligne de
    commande : il n'apparaît pas dans la liste des processus)."""
    options: dict[str, Any] = {}
    if sys.platform == "win32":
        options["creationflags"] = 0x08000000  # CREATE_NO_WINDOW : pas de console qui clignote
    processus = await asyncio.create_subprocess_exec(
        *arguments,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        **options,
    )
    try:
        _, erreur = await asyncio.wait_for(processus.communicate(entree), delai)
    except TimeoutError:
        processus.kill()
        await processus.wait()
        raise ErreurSynthese("Piper n'a pas répondu à temps") from None
    return processus.returncode or 0, erreur


# --- Service ----------------------------------------------------------------------------------------------------------


@dataclass
class Audio:
    donnees: bytes
    type: str  # « audio/wav », « audio/mpeg »
    moteur: Moteur


class ServiceSynthese:
    def __init__(
        self,
        base: Base,
        coffre: Coffre,
        dossier_modeles: Path,
        commande_piper: str = "",
        *,
        est_prive: Callable[[str], Awaitable[bool]] | None = None,
        executeur: Executeur = _executer,
        client: Callable[[], httpx.AsyncClient] | None = None,
        url_elevenlabs: str = URL_ELEVENLABS,
    ) -> None:
        self.base = base
        self.coffre = coffre
        self.dossier_modeles = dossier_modeles
        self.commande_piper = commande_piper
        self.est_prive = est_prive
        self.executeur = executeur
        self.fabrique_client = client or (lambda: httpx.AsyncClient(timeout=DELAI_ELEVENLABS))
        self.url_elevenlabs = url_elevenlabs
        self._piper = asyncio.Semaphore(PIPER_SIMULTANES)

    # -- État ----------------------------------------------------------------------------------------------------

    def programme_piper(self) -> Path | None:
        return trouver_piper(self.commande_piper, self.dossier_modeles)

    def voix_piper_prete(self, ident: str) -> bool:
        dossier = dossier_voix_piper(self.dossier_modeles, ident)
        return (dossier / f"{ident}.onnx").is_file() and (dossier / f"{ident}.onnx.json").is_file()

    def piper_pret(self, ident: str) -> bool:
        return self.programme_piper() is not None and self.voix_piper_prete(ident)

    def cle_elevenlabs(self) -> bool:
        return self.coffre.lire(CLE_COFFRE) is not None

    async def decrire(self, telechargeur: telechargements.Telechargeur) -> dict[str, Any]:
        """État pour l'interface : jamais la clé (seulement « enregistrée » et ses 4 derniers caractères), jamais
        le chemin du programme Piper."""
        reglages = await lire_reglages(self.base)
        modele = modele_piper(self.dossier_modeles, reglages["voix_piper"])
        return {
            "reglages": reglages,
            "piper": {
                "programme": self.programme_piper() is not None,
                "voix": [
                    {"id": v.id, "nom": v.nom, "taille": v.taille, "prete": self.voix_piper_prete(v.id)}
                    for v in VOIX_PIPER.values()
                ],
                "telechargement": telechargeur.etat(modele).en_dict(),
            },
            "elevenlabs": {"cle": self.cle_elevenlabs(), "apercu": self.coffre.apercu(CLE_COFFRE)},
            "annulation_echo": apm_disponible(),
        }

    # -- Synthèse ------------------------------------------------------------------------------------------------

    async def dire(self, texte: str, moteur: Moteur | None = None) -> Audio:
        """Une phrase en audio, par le moteur demandé (ou celui des réglages). « navigateur » n'a rien à faire ici."""
        reglages = await lire_reglages(self.base)
        choisi = moteur or reglages["moteur"]
        if choisi == "piper":
            return await self._dire_piper(texte_a_dire(texte), reglages["voix_piper"])
        if choisi == "elevenlabs":
            return await self._dire_elevenlabs(texte, reglages["voix_elevenlabs"])
        raise ErreurSynthese("La voix du navigateur est lue par l'interface")

    async def _dire_piper(self, texte: str, ident: str) -> Audio:
        if not texte:
            raise ErreurSynthese("Rien à dire")
        programme = self.programme_piper()
        if programme is None:
            raise ErreurSynthese("Programme Piper introuvable")
        if not self.voix_piper_prete(ident):
            raise ErreurSynthese("Voix Piper non téléchargée")
        modele = dossier_voix_piper(self.dossier_modeles, ident) / f"{ident}.onnx"
        async with self._piper:
            with tempfile.TemporaryDirectory(prefix="jarvis2-piper-") as dossier:
                sortie = Path(dossier) / "phrase.wav"
                code, erreur = await self.executeur(
                    [str(programme), "--model", str(modele), "--output_file", str(sortie)],
                    texte.encode("utf-8"),
                    DELAI_PIPER,
                )
                if code != 0 or not sortie.is_file() or sortie.stat().st_size <= 44:
                    # La sortie d'erreur peut citer la phrase : seulement le code dans le journal
                    journal.warning("Piper a échoué (code %s, %d octets d'erreur)", code, len(erreur))
                    raise ErreurSynthese("Piper a échoué")
                return Audio(sortie.read_bytes(), "audio/wav", "piper")

    async def _dire_elevenlabs(self, texte: str, voix: str) -> Audio:
        cle = self.coffre.lire(CLE_COFFRE)
        if not cle:
            raise ErreurSynthese("Clé ElevenLabs absente")
        # Dernière barrière, comme pour les IA externes : un sujet ou des souvenirs privés ne partent pas
        if self.est_prive is not None and await self.est_prive(texte):
            raise PhrasePrivee("Phrase privée : lue par une voix locale")
        propre = texte_a_dire(texte, externe=True)
        if not propre:
            raise ErreurSynthese("Rien à dire")
        try:
            async with self.fabrique_client() as client:
                r = await client.post(
                    f"{self.url_elevenlabs}/v1/text-to-speech/{voix}",
                    params={"output_format": "mp3_44100_128"},
                    headers={"xi-api-key": cle, "Accept": "audio/mpeg"},
                    json={"text": propre, "model_id": MODELE_ELEVENLABS},
                )
        except httpx.HTTPError as exc:
            raise ErreurSynthese(f"ElevenLabs injoignable ({type(exc).__name__})") from exc
        if r.status_code in (401, 403):
            raise ErreurSynthese("Clé ElevenLabs refusée")
        if r.status_code == 429:
            raise ErreurSynthese("Quota ElevenLabs atteint")
        if r.status_code != 200 or not r.content:
            raise ErreurSynthese(f"ElevenLabs : réponse HTTP {r.status_code}")
        return Audio(r.content, r.headers.get("content-type", "audio/mpeg").split(";")[0], "elevenlabs")


def apm_disponible() -> bool:
    """Annulation d'écho de livekit (APM de WebRTC) importable ? Sinon : repli RMS (voir `coupure.py`)."""
    from . import coupure

    return coupure.apm_disponible()
