"""Coupure quand on parle par-dessus JARVIS (« barge-in ») : décider, trame de 10 ms par trame, si l'utilisateur
parle pendant que JARVIS lit à voix haute.

Le micro entend aussi le haut-parleur : sans précaution, JARVIS se couperait lui-même. Deux voies :

1. **Annulation d'écho** (APM de WebRTC, par le paquet `livekit` s'il est installé) : le signal envoyé au
   haut-parleur sert de référence, le délai haut-parleur → micro est MESURÉ (intercorrélation des enveloppes) et
   donné à l'APM ; on décide sur le micro nettoyé.
2. **Repli sans annulation d'écho** : on compare le niveau efficace (RMS) du micro à celui du haut-parleur, décalé
   du délai mesuré et multiplié par le couplage appris (ce que le micro entend de JARVIS seul). Avec un **casque**
   (détecté par le nom du périphérique, ou par un couplage quasi nul), le haut-parleur n'atteint pas le micro :
   un seuil simple suffit.

Dans les deux cas, il faut plusieurs trames de suite au-dessus du seuil (une toux, un clic ne coupent pas).
L'interface applique le même algorithme dans le navigateur (`interface/src/synthese.ts`), où l'annulation d'écho
du navigateur (WebRTC lui aussi) remplace l'APM.
"""

from __future__ import annotations

import math
import re
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

FREQUENCE = 16_000
TRAME = FREQUENCE // 100  # 10 ms : la taille imposée par l'APM de WebRTC
DELAI_MAX_MS = 400  # au-delà, ce n'est plus un écho mais une autre source
SEUIL_PAROLE = 0.02  # RMS (échantillons dans [-1, 1]) d'une voix proche du micro
MARGE_ECHO = 2.5  # le micro doit dépasser l'écho attendu de ce facteur
TRAMES_DECISION = 12  # 120 ms de parole de suite
COUPLAGE_CASQUE = 0.03  # le micro n'entend presque rien de JARVIS : casque probable

_CASQUE = re.compile(r"casque|[ée]couteur|headset|headphone|earphone|earbud|airpods|buds|bluetooth|hands-?free", re.I)


def casque_par_nom(noms: Sequence[str]) -> bool:
    """Un périphérique de sortie ou d'entrée qui porte un nom de casque (« Casque (Realtek) », « AirPods »…)."""
    return any(_CASQUE.search(n) for n in noms)


def rms(trame: Sequence[float]) -> float:
    if not trame:
        return 0.0
    return math.sqrt(sum(x * x for x in trame) / len(trame))


def mesurer_delai(reference: Sequence[float], micro: Sequence[float], trame_ms: int = 10) -> int | None:
    """Délai (ms) entre l'enveloppe du haut-parleur et celle du micro, par intercorrélation normalisée des niveaux
    RMS trame par trame. None si le haut-parleur était silencieux ou si rien ne se ressemble (casque)."""
    n = min(len(reference), len(micro))
    if n < 10:
        return None
    ref, mic = list(reference[-n:]), list(micro[-n:])
    moy_r = sum(ref) / n
    ecart_r = math.sqrt(sum((x - moy_r) ** 2 for x in ref))
    if ecart_r < 1e-6:
        return None
    meilleur, meilleur_decalage = 0.0, None
    for decalage in range(min(DELAI_MAX_MS // trame_ms, n - 5) + 1):
        r = ref[: n - decalage]
        m = mic[decalage:]
        mr, mm = sum(r) / len(r), sum(m) / len(m)
        num = sum((a - mr) * (b - mm) for a, b in zip(r, m, strict=True))
        den = math.sqrt(sum((a - mr) ** 2 for a in r) * sum((b - mm) ** 2 for b in m))
        if den < 1e-9:
            continue
        correlation = num / den
        if correlation > meilleur:
            meilleur, meilleur_decalage = correlation, decalage
    if meilleur_decalage is None or meilleur < 0.5:
        return None
    return meilleur_decalage * trame_ms


def apm_disponible() -> bool:
    try:
        from livekit import rtc  # type: ignore[import-not-found, unused-ignore]
    except ImportError:
        return False
    return hasattr(rtc, "AudioProcessingModule")


class AnnulationEcho:
    """APM de WebRTC par livekit : trames int16 mono de 10 ms à 16 kHz, référence haut-parleur puis micro."""

    def __init__(self) -> None:
        from livekit import rtc  # type: ignore[import-not-found, unused-ignore]

        self._rtc: Any = rtc
        self._apm: Any = rtc.AudioProcessingModule(
            echo_cancellation=True, noise_suppression=True, high_pass_filter=True, auto_gain_control=False
        )

    def _trame(self, echantillons: Sequence[float]) -> Any:
        donnees = bytearray()
        for x in echantillons:
            v = max(-32768, min(32767, int(x * 32767)))
            donnees += v.to_bytes(2, "little", signed=True)
        return self._rtc.AudioFrame(bytes(donnees), FREQUENCE, 1, len(echantillons))

    def nettoyer(self, micro: Sequence[float], haut_parleur: Sequence[float], delai_ms: int) -> list[float]:
        reference = self._trame(haut_parleur)
        self._apm.process_reverse_stream(reference)
        self._apm.set_stream_delay_ms(delai_ms)
        trame = self._trame(micro)
        self._apm.process_stream(trame)  # en place
        brut = bytes(trame.data)
        return [int.from_bytes(brut[i : i + 2], "little", signed=True) / 32768.0 for i in range(0, len(brut), 2)]


@dataclass
class DetecteurCoupure:
    """`trame(micro, haut_parleur)` toutes les 10 ms pendant la lecture ; renvoie True quand l'utilisateur parle
    par-dessus. `casque` : décidé par le nom du périphérique ; le couplage mesuré peut aussi le révéler."""

    casque: bool = False
    annulation: Callable[[], AnnulationEcho] | None = None
    seuil: float = SEUIL_PAROLE
    trames_decision: int = TRAMES_DECISION
    _apm: AnnulationEcho | None = field(default=None, init=False)
    _hp: deque[float] = field(default_factory=lambda: deque(maxlen=200), init=False)  # 2 s d'enveloppe
    _mic: deque[float] = field(default_factory=lambda: deque(maxlen=200), init=False)
    _couplage: float | None = field(default=None, init=False)
    _suite: int = field(default=0, init=False)
    _trames: int = field(default=0, init=False)
    delai_ms: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        fabrique = self.annulation
        if fabrique is None and apm_disponible():
            fabrique = AnnulationEcho
        if fabrique is not None:
            try:
                self._apm = fabrique()
            except Exception:  # APM présent mais inutilisable : repli RMS
                self._apm = None

    @property
    def mode(self) -> str:
        if self.casque:
            return "casque"
        return "annulation_echo" if self._apm is not None else "rms"

    def _apprendre(self, niveau_hp: float, niveau_mic: float) -> None:
        """Couplage haut-parleur → micro appris quand JARVIS parle et que le micro n'entend que lui (min. glissant
        du rapport) ; délai remesuré toutes les 50 trames (0,5 s)."""
        if niveau_hp > self.seuil:
            rapport = niveau_mic / niveau_hp
            self._couplage = rapport if self._couplage is None else min(rapport, 0.98 * self._couplage + 0.02 * rapport)
        if self._trames % 50 == 0:
            delai = mesurer_delai(list(self._hp), list(self._mic))
            if delai is not None:
                self.delai_ms = delai

    def _hp_decale(self) -> float:
        """Niveau du haut-parleur au moment où son écho atteint le micro (délai mesuré)."""
        recul = self.delai_ms // 10
        if not self._hp:
            return 0.0
        if recul >= len(self._hp):
            return self._hp[0]
        return self._hp[-1 - recul]

    def trame(self, micro: Sequence[float], haut_parleur: Sequence[float]) -> bool:
        self._trames += 1
        niveau_hp = rms(haut_parleur)
        self._hp.append(niveau_hp)
        if self._apm is not None and not self.casque:
            propre = self._apm.nettoyer(micro, haut_parleur, self.delai_ms)
            niveau = rms(propre)
            self._mic.append(rms(micro))
            seuil = self.seuil
        else:
            niveau = rms(micro)
            self._mic.append(niveau)
            if self.casque:
                seuil = self.seuil
            else:
                echo = (self._couplage if self._couplage is not None else 1.0) * self._hp_decale()
                seuil = max(self.seuil, echo * MARGE_ECHO)
        parle = niveau > seuil
        if not parle:
            self._apprendre(niveau_hp, self._mic[-1])
            if self._couplage is not None and self._couplage < COUPLAGE_CASQUE and self._trames > 100:
                self.casque = True  # JARVIS parle fort et le micro ne l'entend pas : casque
        self._suite = self._suite + 1 if parle else 0
        if self._suite >= self.trames_decision:
            self._suite = 0
            return True
        return False
