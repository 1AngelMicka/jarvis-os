"""Transcription robuste (lot K3) : Whisper int8 sur la carte graphique ou le processeur, VAD Silero, préchauffage,
filtres d'hallucinations, disjoncteur et transcription anticipée.

- **Appareil** : CUDA (NVIDIA) ou ROCm (AMD, selon la version de CTranslate2 installée : à mesurer) quand
  CTranslate2 voit une carte, sinon le processeur. Une carte qui échoue (bibliothèques CUDA absentes…) fait
  repasser sur le processeur, avec la raison, sans perdre la phrase.
- **VAD Silero** (fourni avec faster-whisper, aucun téléchargement) : un enregistrement sans parole n'est jamais
  confié à Whisper, qui « entend » alors des phrases toutes faites.
- **Filtres d'hallucinations** : génériques de sous-titres (« Sous-titres réalisés par la communauté d'Amara.org »),
  appels à s'abonner, invite recopiée, répétitions en boucle, segments que Whisper lui-même juge sans parole.
- **Disjoncteur** : après 3 échecs de suite du modèle, la transcription se met en pause 60 s (réponse immédiate et
  claire au lieu d'attendre chaque fois un échec) ; un essai est permis à la fin de la pause.
- **Transcription anticipée** : l'interface envoie la phrase dès le début du silence ; si l'enregistrement final
  n'est que cette phrase suivie de silence (même début d'octets, aucune parole dans la fin), le texte déjà prêt
  sert tout de suite.
- Le modèle n'est jamais téléchargé ici : seulement sur accord, par `telechargements.py`.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from .voix import INVITE_WHISPER, TAILLE_MAX, decoder_audio, sans_accents

journal = logging.getLogger("jarvis2.transcription")

TAUX = 16000
MODELES_CONSEILLES = ("small", "medium")  # int8 : bon compromis précision / vitesse en français
SEUIL_DISJONCTEUR = 3
PAUSE_DISJONCTEUR = 60.0
DUREE_CACHE = 90.0  # secondes pendant lesquelles une transcription anticipée peut resservir
TAILLE_CACHE = 6
PAROLE_MIN_COURTE = 0.6  # en dessous, « Merci. » ou « Au revoir. » seuls sont presque toujours inventés

Famille = Literal["cuda", "rocm", "processeur"]


# --- Appareil ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Appareil:
    famille: Famille
    device: str  # « cuda » (ROCm passe aussi par ce nom dans CTranslate2) ou « cpu »
    type_calcul: str
    raison: str | None = None

    @property
    def libelle(self) -> str:
        return {
            "cuda": "carte graphique NVIDIA (CUDA)",
            "rocm": "carte graphique AMD (ROCm)",
            "processeur": "processeur",
        }[self.famille]

    def en_dict(self) -> dict[str, Any]:
        return {
            "famille": self.famille,
            "libelle": self.libelle,
            "type_calcul": self.type_calcul,
            "raison": self.raison,
        }


PROCESSEUR = Appareil("processeur", "cpu", "int8")


def _ct2_cartes() -> tuple[int, set[str]]:
    try:
        import ctranslate2  # type: ignore[import-untyped]

        n = int(ctranslate2.get_cuda_device_count())
        types = set(ctranslate2.get_supported_compute_types("cuda")) if n else set()
        return n, types
    except Exception:  # CTranslate2 sans prise en charge des cartes, pilote absent…
        return 0, set()


def fabricant_carte() -> str | None:
    """« nvidia », « amd » ou None, d'après la détection du matériel (sans rien installer)."""
    try:
        from .materiel import detecter

        carte = (detecter().carte or "").lower()
    except Exception:
        return None
    if "nvidia" in carte or "geforce" in carte or "rtx" in carte:
        return "nvidia"
    if "amd" in carte or "radeon" in carte:
        return "amd"
    return None


def detecter_appareil(
    voulu: str = "auto",
    cartes: Callable[[], tuple[int, set[str]]] = _ct2_cartes,
    fabricant: Callable[[], str | None] = fabricant_carte,
) -> Appareil:
    """`voulu` : « auto » (carte si possible), « cpu » ou « cuda » (JARVIS2_VOIX_APPAREIL)."""
    if voulu == "cpu":
        return PROCESSEUR
    n, types = cartes()
    marque = fabricant()
    if n <= 0:
        raison = None
        if marque == "amd":
            raison = "carte AMD : cette installation de CTranslate2 n'a pas ROCm, transcription sur le processeur"
        elif voulu == "cuda":
            raison = "aucune carte vue par CTranslate2 (pilote ou bibliothèques CUDA absents)"
        return Appareil("processeur", "cpu", "int8", raison)
    type_calcul = next((t for t in ("int8_float16", "int8", "float16") if t in types), "default")
    return Appareil("rocm" if marque == "amd" else "cuda", "cuda", type_calcul)


# --- Filtres d'hallucinations ---------------------------------------------------------------------------------

HALLUCINATIONS = [
    re.compile(m, re.IGNORECASE)
    for m in (
        r"sous[- ]?titr(?:e|es|age|ages)\b",  # « Sous-titres réalisés par… », « Sous-titrage ST' 501 »
        r"amara\.org",
        r"radio[- ]canada",
        r"merci d'avoir regarde",
        r"merci (?:a tous )?(?:de|d'avoir) (?:votre attention|suivi|ecoute) (?:cette|la) video",
        r"abonnez[- ]vous",
        r"n'oubliez pas de (?:vous abonner|liker|like|commenter|partager)",
        r"(?:like|likez|liker)(?:z)? et (?:abonne|partage)",
        r"a (?:la|une) prochaine (?:video|fois sur (?:la|ma) chaine)",
        r"(?:thanks|thank you) for watching",
        r"please subscribe",
        r"subtitles by",
        r"transcri(?:ption|t) (?:realisee )?par",
        r"traduction (?:et sous-titr\w* )?par",
        r"conversation en francais avec jarvis",  # l'invite recopiée
    )
]
COURTES_SUSPECTES = {"merci", "au revoir", "bonne journee", "bonsoir", "salut", "ok", "d'accord", "voila", "oui"}
REPETITION = re.compile(r"(\b[^.!?]{2,60}?)(?:[\s,.;!?…-]+\1\b){3,}", re.IGNORECASE)


def _propre(texte: str) -> str:
    return " ".join(re.sub(r"[^\w' -]", " ", sans_accents(texte).lower()).split())


def est_hallucination(texte: str) -> bool:
    norme = _propre(texte)
    if not norme:
        return True
    return any(m.search(norme) for m in HALLUCINATIONS)


def sans_repetitions(texte: str) -> str:
    """« oui oui oui oui oui » → « oui » ; une boucle de Whisper n'est gardée qu'une fois."""
    precedent = None
    while precedent != texte:
        precedent = texte
        texte = REPETITION.sub(r"\1", texte)
    return texte


@dataclass(frozen=True)
class Segment:
    texte: str
    sans_parole: float = 0.0  # no_speech_prob
    log_prob: float = 0.0  # avg_logprob
    compression: float = 1.0  # compression_ratio


def filtrer(segments: list[Segment], duree_parole: float) -> tuple[str, list[str]]:
    """Texte gardé et raisons des segments écartés."""
    gardes: list[str] = []
    ecartes: list[str] = []
    for s in segments:
        texte = s.texte.strip()
        if not texte:
            continue
        if s.sans_parole > 0.6 and s.log_prob < -0.7:
            ecartes.append("sans parole selon Whisper")
        elif s.compression > 2.4:
            ecartes.append("texte répétitif (boucle de Whisper)")
        elif est_hallucination(texte):
            ecartes.append("phrase toute faite (hallucination connue)")
        else:
            gardes.append(texte)
    texte = sans_repetitions(" ".join(gardes).strip())
    if texte and duree_parole < PAROLE_MIN_COURTE and _propre(texte) in COURTES_SUSPECTES:
        return "", [*ecartes, "mot isolé sur un bruit trop court"]
    return texte, ecartes


# --- Disjoncteur --------------------------------------------------------------------------------------------


class TranscriptionEnPause(RuntimeError):
    def __init__(self, reste: float) -> None:
        super().__init__(
            f"Transcription en pause après {SEUIL_DISJONCTEUR} échecs de suite : "
            f"nouvel essai dans {max(1, round(reste))} s"
        )
        self.reste = reste


@dataclass
class Disjoncteur:
    seuil: int = SEUIL_DISJONCTEUR
    pause: float = PAUSE_DISJONCTEUR
    horloge: Callable[[], float] = time.monotonic
    echecs: int = 0
    ouvert_le: float | None = None
    derniere_erreur: str | None = None

    def avant(self) -> None:
        if self.ouvert_le is None:
            return
        reste = self.ouvert_le + self.pause - self.horloge()
        if reste > 0:
            raise TranscriptionEnPause(reste)
        self.ouvert_le = None  # fin de la pause : un essai (un nouvel échec rouvre tout de suite)
        self.echecs = self.seuil - 1

    def succes(self) -> None:
        self.echecs, self.ouvert_le = 0, None

    def echec(self, erreur: BaseException) -> None:
        self.echecs += 1
        self.derniere_erreur = f"{type(erreur).__name__} : {str(erreur)[:200]}"
        if self.echecs >= self.seuil:
            self.ouvert_le = self.horloge()
            journal.warning("Transcription en pause %.0f s : %s", self.pause, self.derniere_erreur)

    def en_dict(self) -> dict[str, Any]:
        reste = None
        if self.ouvert_le is not None:
            reste = max(0.0, round(self.ouvert_le + self.pause - self.horloge(), 1))
        return {"ouvert": bool(reste), "reste_s": reste, "echecs": self.echecs, "derniere_erreur": self.derniere_erreur}


# --- Transcripteur -----------------------------------------------------------------------------------------


class ModeleWhisper(Protocol):
    def transcribe(self, audio: Any, **options: Any) -> tuple[Any, Any]: ...


Chargeur = Callable[[Path | str, Appareil, Path], ModeleWhisper]
Vad = Callable[[Any], list[tuple[int, int]]]


def charger_faster_whisper(source: Path | str, appareil: Appareil, cache: Path) -> ModeleWhisper:
    from faster_whisper import WhisperModel

    options: dict[str, Any] = {"device": appareil.device, "compute_type": appareil.type_calcul}
    if isinstance(source, str):  # ancien cache d'une installation antérieure : jamais de téléchargement
        options |= {"download_root": str(cache), "local_files_only": True}
    modele: ModeleWhisper = WhisperModel(str(source), **options)
    return modele


def vad_silero(echantillons: Any) -> list[tuple[int, int]]:
    """Plages de parole (échantillons) selon Silero, fourni avec faster-whisper."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps  # type: ignore[import-untyped]

    plages = get_speech_timestamps(
        echantillons, VadOptions(threshold=0.5, min_speech_duration_ms=200, min_silence_duration_ms=500)
    )
    return [(int(p["start"]), int(p["end"])) for p in plages]


@dataclass
class Resultat:
    texte: str
    langue: str | None
    duree_audio: float
    duree_parole: float
    ecartes: list[str] = field(default_factory=list)
    anticipe: bool = False  # texte repris d'une transcription anticipée
    etapes_ms: dict[str, float] = field(default_factory=dict)
    echantillons: Any = None  # gardés en mémoire le temps de l'appel (reconnaissance du propriétaire)
    plages: list[tuple[int, int]] = field(default_factory=list)

    def en_dict(self) -> dict[str, Any]:
        return {
            "texte": self.texte,
            "langue": self.langue,
            "duree_audio_s": round(self.duree_audio, 2),
            "duree_parole_s": round(self.duree_parole, 2),
            "ecartes": self.ecartes,
            "anticipe": self.anticipe,
            "etapes_ms": {k: round(v, 1) for k, v in self.etapes_ms.items()},
        }


@dataclass
class _EnCache:
    audio: bytes
    resultat: Resultat
    instant: float


Observateur = Callable[[Resultat], Awaitable[None]]


class TranscripteurRobuste:
    """Remplace `voix.TranscripteurWhisper` (même interface `transcrire`), avec le détail en plus."""

    def __init__(
        self,
        dossier_modeles: Path,
        modele: str = "base",
        appareil: str = "auto",
        *,
        chargeur: Chargeur = charger_faster_whisper,
        vad: Vad = vad_silero,
        detecteur: Callable[[str], Appareil] = detecter_appareil,
        decodeur: Callable[[bytes], Any] = decoder_audio,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self.dossier_modeles = dossier_modeles
        self.modele = modele
        self.voulu = appareil
        self.chargeur = chargeur
        self.vad = vad
        self.detecteur = detecteur
        self.decodeur = decodeur
        self.horloge = horloge
        self.disjoncteur = Disjoncteur(horloge=horloge)
        self.appareil: Appareil | None = None
        self.prechauffe = False
        self.duree_chargement_ms: float | None = None
        self.observateur: Observateur | None = None  # reconnaissance du propriétaire, attestations (ServiceVoix)
        self._charge: ModeleWhisper | None = None
        self._verrou = threading.Lock()
        self._cache: list[_EnCache] = []
        self._prevu: Appareil | None = None

    # -- chargement ------------------------------------------------------------------------------------------

    def _source(self) -> Path | str:
        from .telechargements import ModeleAbsent, dossier_whisper, est_pret

        propre = dossier_whisper(self.dossier_modeles, self.modele)
        if est_pret(propre):
            return propre
        ancien = self.dossier_modeles / "whisper"
        if ancien.is_dir() and any(ancien.glob(f"*{self.modele}*")):
            return self.modele
        raise ModeleAbsent(
            f"Modèle de voix Whisper « {self.modele} » non téléchargé : acceptez son téléchargement dans le "
            "diagnostic (ou `jarvis2 docteur --reparer`)"
        )

    def _charger(self) -> ModeleWhisper:
        with self._verrou:
            if self._charge is not None:
                return self._charge
            source = self._source()
            appareil = self.detecteur(self.voulu) if self._prevu is None else self._prevu
            debut = time.perf_counter()
            try:
                self._charge = self.chargeur(source, appareil, self.dossier_modeles / "whisper")
            except Exception as exc:
                if appareil.device == "cpu":
                    raise
                journal.warning("Whisper sur la carte impossible (%s) : repli sur le processeur", exc)
                appareil = Appareil("processeur", "cpu", "int8", f"carte inutilisable ({type(exc).__name__})")
                self._charge = self.chargeur(source, appareil, self.dossier_modeles / "whisper")
                self._prevu = PROCESSEUR
            self.appareil = appareil
            self.duree_chargement_ms = (time.perf_counter() - debut) * 1000
            journal.info("Whisper %s chargé sur %s en %.0f ms", self.modele, appareil.libelle, self.duree_chargement_ms)
            return self._charge

    def _repli_processeur(self, exc: BaseException) -> bool:
        """Échec de la carte pendant le calcul (cuBLAS absent…) : on recharge sur le processeur, une fois."""
        if self.appareil is None or self.appareil.device == "cpu":
            return False
        journal.warning("Whisper a échoué sur la carte (%s) : repli sur le processeur", exc)
        with self._verrou:
            self._charge = None
        self.voulu, self._prevu = "cpu", PROCESSEUR
        self._charger()
        if self.appareil is not None:
            self.appareil = Appareil("processeur", "cpu", "int8", f"carte en échec ({type(exc).__name__})")
        return True

    # -- calcul ----------------------------------------------------------------------------------------------

    def _whisper(self, echantillons: Any) -> tuple[list[Segment], str | None]:
        modele = self._charger()
        sur_carte = self.appareil is not None and self.appareil.device != "cpu"
        segments, info = modele.transcribe(
            echantillons,
            language="fr",
            vad_filter=True,
            beam_size=5 if sur_carte else 1,
            condition_on_previous_text=False,  # évite les boucles d'un segment à l'autre
            initial_prompt=INVITE_WHISPER,
        )
        sortie = [
            Segment(
                str(getattr(s, "text", "")),
                float(getattr(s, "no_speech_prob", 0.0) or 0.0),
                float(getattr(s, "avg_logprob", 0.0) or 0.0),
                float(getattr(s, "compression_ratio", 1.0) or 1.0),
            )
            for s in segments
        ]
        return sortie, getattr(info, "language", None)

    def _depuis_cache(self, audio: bytes) -> _EnCache | None:
        maintenant = self.horloge()
        self._cache = [c for c in self._cache if maintenant - c.instant < DUREE_CACHE]
        for c in reversed(self._cache):
            if audio.startswith(c.audio):
                return c
        return None

    def _transcrire(self, audio: bytes, anticipation: bool) -> Resultat:
        etapes: dict[str, float] = {}
        t0 = time.perf_counter()
        echantillons = self.decodeur(audio)
        etapes["decodage"] = (time.perf_counter() - t0) * 1000
        duree = len(echantillons) / TAUX
        en_cache = None if anticipation else self._depuis_cache(audio)
        t1 = time.perf_counter()
        if en_cache is not None:
            r = en_cache.resultat
            meme = len(audio) == len(en_cache.audio)
            # rien de plus n'a été dit depuis l'anticipation : le texte est déjà prêt
            if meme or not self.vad(echantillons[int(r.duree_audio * TAUX) :]):
                etapes["vad"] = (time.perf_counter() - t1) * 1000
                return Resultat(r.texte, r.langue, duree, r.duree_parole, list(r.ecartes), True, etapes,
                                echantillons, r.plages)  # fmt: skip
        plages = self.vad(echantillons)
        etapes["vad"] = (time.perf_counter() - t1) * 1000
        parole = sum(f - d for d, f in plages) / TAUX
        if not plages:
            return Resultat("", None, duree, 0.0, ["aucune parole (VAD)"], False, etapes, echantillons, plages)
        self.disjoncteur.avant()
        t2 = time.perf_counter()
        try:
            try:
                segments, langue = self._whisper(echantillons)
            except Exception as exc:
                from .telechargements import ModeleAbsent

                if isinstance(exc, ModeleAbsent) or not self._repli_processeur(exc):
                    raise
                segments, langue = self._whisper(echantillons)
        except Exception as exc:
            from .telechargements import ModeleAbsent

            if not isinstance(exc, ModeleAbsent):
                self.disjoncteur.echec(exc)
            raise
        self.disjoncteur.succes()
        etapes["whisper"] = (time.perf_counter() - t2) * 1000
        texte, ecartes = filtrer(segments, parole)
        resultat = Resultat(texte, langue, duree, parole, ecartes, False, etapes, echantillons, plages)
        if anticipation:
            self._cache.append(_EnCache(audio, resultat, self.horloge()))
            del self._cache[:-TAILLE_CACHE]
        return resultat

    async def transcrire_detail(self, audio: bytes, *, anticipation: bool = False) -> Resultat:
        if len(audio) > TAILLE_MAX:
            raise ValueError("Enregistrement trop long (25 Mo au plus)")
        resultat = await asyncio.to_thread(self._transcrire, audio, anticipation)
        if self.observateur is not None and not anticipation:
            try:
                await self.observateur(resultat)
            except Exception:  # la reconnaissance du propriétaire ne fait jamais échouer la transcription
                journal.exception("Observation de la transcription")
        resultat.echantillons = None
        return resultat

    def _analyser(self, audio: bytes) -> Resultat:
        echantillons = self.decodeur(audio)
        plages = self.vad(echantillons)
        parole = sum(f - d for d, f in plages) / TAUX
        return Resultat("", None, len(echantillons) / TAUX, parole, [], False, {}, echantillons, plages)

    async def analyser(self, audio: bytes) -> Resultat:
        """Décodage et VAD seulement (empreinte de voix) : rien n'est confié à Whisper."""
        if len(audio) > TAILLE_MAX:
            raise ValueError("Enregistrement trop long (25 Mo au plus)")
        return await asyncio.to_thread(self._analyser, audio)

    async def transcrire(self, audio: bytes) -> tuple[str, str | None]:
        r = await self.transcrire_detail(audio)
        return r.texte, r.langue

    # -- préchauffage et état --------------------------------------------------------------------------------

    def _prechauffer(self) -> float:
        import numpy as np

        debut = time.perf_counter()
        modele = self._charger()
        bruit = (np.random.default_rng(0).standard_normal(TAUX) * 0.01).astype(np.float32)
        segments, _ = modele.transcribe(bruit, language="fr", beam_size=1, vad_filter=False)
        for _ in segments:  # le calcul n'a lieu qu'à la lecture des segments
            pass
        self.prechauffe = True
        return (time.perf_counter() - debut) * 1000

    async def prechauffer(self) -> float:
        """Charge le modèle et fait un premier calcul : la première vraie phrase n'attend plus. Durée (ms)."""
        return await asyncio.to_thread(self._prechauffer)

    def appareil_prevu(self) -> Appareil:
        """L'appareil chargé, sinon celui qui le serait (détecté une fois)."""
        if self.appareil is None and self._prevu is None:
            self._prevu = self.detecteur(self.voulu)
        return self.appareil or self._prevu or PROCESSEUR

    def etat(self) -> dict[str, Any]:
        from .telechargements import dossier_whisper, est_pret

        return {
            "modele": self.modele,
            "conseille": self.modele in MODELES_CONSEILLES,
            "telecharge": est_pret(dossier_whisper(self.dossier_modeles, self.modele)),
            "charge": self._charge is not None,
            "prechauffe": self.prechauffe,
            "chargement_ms": round(self.duree_chargement_ms) if self.duree_chargement_ms is not None else None,
            "appareil": self.appareil_prevu().en_dict(),
            "disjoncteur": self.disjoncteur.en_dict(),
        }
