"""Voix : transcription LOCALE (faster-whisper) et mot d'éveil « Jarvis ».

L'audio enregistré par l'interface (micro du PC ou du téléphone) est transcrit sur le PC ; rien ne part vers un
service de reconnaissance vocale. Le modèle (`JARVIS2_MODELE_VOIX`, « base » par défaut, « small » plus précis) est
téléchargé une fois dans le dossier des modèles. La synthèse vocale est faite par l'interface avec les voix LOCALES du
système (jamais une voix en ligne).
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

journal = logging.getLogger("jarvis2.voix")

# « Jarvis » et ses transcriptions approchées les plus fréquentes (j'arvi, jarvi, djarvis, jarvice…)
EVEIL = re.compile(
    r"^\s*(?:(?:hey|he|eh|dis|ok|okay|bonjour)\s*,?\s*)?(?:d|g)?j\s?'?\s?arr?vi(?:s|ce|ss|z)?\b[\s,.!?:;-]*",
    re.IGNORECASE,
)
INVITE_WHISPER = "Conversation en français avec Jarvis, l'assistant personnel."
TAILLE_MAX = 25 * 1024 * 1024


@dataclass(frozen=True)
class Transcription:
    texte: str
    eveil: bool
    commande: str
    langue: str | None = None

    def en_dict(self) -> dict[str, Any]:
        return {"texte": self.texte, "eveil": self.eveil, "commande": self.commande, "langue": self.langue}


def sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texte) if not unicodedata.combining(c))


def analyser_eveil(texte: str) -> Transcription:
    """« Jarvis, quelle heure est-il ? » → éveil, commande « quelle heure est-il ? »."""
    propre = " ".join(texte.split())
    trouve = EVEIL.match(sans_accents(propre))
    if trouve is None:
        return Transcription(propre, False, propre)
    return Transcription(propre, True, propre[trouve.end() :].strip())


def decoder_audio(audio: bytes) -> Any:
    """Enregistrement (webm/opus du navigateur, ogg, wav…) → échantillons float32 mono à 16 kHz pour Whisper.

    Décodé ici avec PyAV (plutôt que par faster-whisper, dont l'appel n'est plus compatible avec PyAV ≥ 15).
    """
    import av
    import numpy as np

    morceaux = []
    with av.open(io.BytesIO(audio), mode="r") as conteneur:
        reechantillonneur = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for trame in conteneur.decode(audio=0):
            for sortie in reechantillonneur.resample(trame):
                morceaux.append(sortie.to_ndarray().reshape(-1))
        for sortie in reechantillonneur.resample(None):  # fin du flux
            morceaux.append(sortie.to_ndarray().reshape(-1))
    if not morceaux:
        raise ValueError("Enregistrement sans son")
    return np.concatenate(morceaux).astype(np.float32) / 32768.0


class Transcripteur(Protocol):
    async def transcrire(self, audio: bytes) -> tuple[str, str | None]: ...


class TranscripteurWhisper:
    def __init__(self, dossier_modeles: Path, modele: str = "base") -> None:
        self.dossier = dossier_modeles / "whisper"
        self.modele = modele
        self._charge: Any = None
        self._verrou = threading.Lock()

    def _charger(self) -> Any:
        with self._verrou:
            if self._charge is None:
                from faster_whisper import WhisperModel

                from .telechargements import ModeleAbsent, dossier_whisper, est_pret

                propre = dossier_whisper(self.dossier.parent, self.modele)
                journal.info("Chargement du modèle de voix Whisper %s…", self.modele)
                if est_pret(propre):  # téléchargé par jarvis2.telechargements
                    self._charge = WhisperModel(str(propre), device="cpu", compute_type="int8")
                else:  # ancien cache (installations antérieures) ; jamais de téléchargement implicite
                    try:
                        self._charge = WhisperModel(
                            self.modele,
                            device="cpu",
                            compute_type="int8",
                            download_root=str(self.dossier),
                            local_files_only=True,
                        )
                    except Exception as exc:
                        raise ModeleAbsent(
                            f"Modèle de voix Whisper « {self.modele} » non téléchargé : acceptez son "
                            "téléchargement dans le diagnostic (ou `jarvis2 docteur --reparer`)"
                        ) from exc
            return self._charge

    def _transcrire(self, audio: bytes) -> tuple[str, str | None]:
        echantillons = decoder_audio(audio)
        segments, info = self._charger().transcribe(
            echantillons, language="fr", vad_filter=True, beam_size=1, initial_prompt=INVITE_WHISPER
        )
        return " ".join(s.text.strip() for s in segments).strip(), getattr(info, "language", None)

    async def transcrire(self, audio: bytes) -> tuple[str, str | None]:
        if len(audio) > TAILLE_MAX:
            raise ValueError("Enregistrement trop long (25 Mo au plus)")
        return await asyncio.to_thread(self._transcrire, audio)


async def transcrire(transcripteur: Transcripteur, audio: bytes) -> Transcription:
    texte, langue = await transcripteur.transcrire(audio)
    t = analyser_eveil(texte)
    return Transcription(t.texte, t.eveil, t.commande, langue)
