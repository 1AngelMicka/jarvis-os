"""Mode jeu = VEILLE stricte : pendant une partie, JARVIS ne fait plus rien d'autre que ce qu'on active à la main.

Réglage (gardé en base) : `automatique` (défaut : veille quand un jeu est au premier plan), `force` (veille
forcée), `jamais`. Détection toutes les 3 s, en lecture seule : la fenêtre au premier plan est-elle un jeu ?
- son programme est dans un dossier de jeux connu (Steam, Epic, Riot, Ubisoft, EA, GOG, Xbox) ou dans la liste
  `[pc] jeux` de la configuration locale ;
- ou elle couvre tout l'écran, hors navigateurs et lecteurs vidéo.
Veille après 5 s de jeu, réveil 20 s après la fin (pas de bascule à chaque Alt+Tab).

En veille : modèles Ollama déchargés et Ollama arrêté (s'il a été lancé par JARVIS), recettes planifiées en
attente, l'interface se tait (ni son ni notification). Rien ne redémarre seul au réveil : Ollama reste à la demande.
"""

from __future__ import annotations

import asyncio
import logging
import ntpath
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Literal, Protocol

journal = logging.getLogger("jarvis2.pc.jeu")

Reglage = Literal["automatique", "force", "jamais"]
REGLAGES: tuple[Reglage, ...] = ("automatique", "force", "jamais")
ENTREE_S = 5.0
SORTIE_S = 20.0
INTERVALLE_S = 3.0

DOSSIERS_JEUX = (
    "\\steamapps\\common\\",
    "\\epic games\\",
    "\\riot games\\",
    "\\ubisoft game launcher\\games\\",
    "\\ea games\\",
    "\\electronic arts\\",
    "\\gog games\\",
    "\\gog galaxy\\games\\",
    "\\xboxgames\\",
    "\\battle.net\\",
)
# Plein écran sans être un jeu : navigateurs, lecteurs vidéo, présentations
PAS_DES_JEUX = frozenset({
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "vlc.exe", "mpc-hc64.exe",
    "mpc-be64.exe", "mpv.exe", "potplayermini64.exe", "jellyfin.exe", "jellyfinmediaplayer.exe", "plex.exe",
    "powerpnt.exe", "explorer.exe", "applicationframehost.exe", "jarvis.exe", "jarvis 2.exe", "obs64.exe",
})  # fmt: skip


@dataclass(frozen=True)
class Premier:
    """Fenêtre au premier plan, telle que lue par le détecteur."""

    chemin: str  # chemin complet de l'exécutable
    plein_ecran: bool


class Detecteur(Protocol):
    def premier_plan(self) -> Premier | None: ...


def est_un_jeu(p: Premier, jeux: Iterable[str] = ()) -> str | None:
    """Nom du jeu (exécutable) si la fenêtre au premier plan en est un, sinon None."""
    chemin = p.chemin.replace("/", "\\").lower()
    nom = ntpath.basename(chemin)
    if not nom:
        return None
    if nom in {j.lower() for j in jeux}:
        return nom
    if any(d in chemin for d in DOSSIERS_JEUX):
        return nom
    if p.plein_ecran and nom not in PAS_DES_JEUX:
        return nom
    return None


class DetecteurWindows:
    def premier_plan(self) -> Premier | None:
        from . import windows

        if not windows.disponible():
            return None
        h = windows.premier_plan()
        if h is None:
            return None
        return Premier(windows.programme_de(h), windows.plein_ecran(h))


@dataclass
class ModeJeu:
    detecteur: Detecteur | None
    jeux: tuple[str, ...] = ()
    reglage: Reglage = "automatique"
    actif_detection: Callable[[], bool] = lambda: True  # faux en mode sans écran
    a_l_entree: list[Callable[[str], Awaitable[None]]] = field(default_factory=list)
    jeu: str | None = None  # jeu qui a déclenché la veille
    _vu: str | None = None
    _vu_depuis: float | None = None
    _absent_depuis: float | None = None
    _veille_auto: bool = False

    @property
    def en_veille(self) -> bool:
        return self.reglage == "force" or (self.reglage == "automatique" and self._veille_auto)

    def decrire(self) -> dict[str, object]:
        return {
            "reglage": self.reglage,
            "en_veille": self.en_veille,
            "jeu": self.jeu if self._veille_auto else None,
            "detection": self.detecteur is not None and self.actif_detection(),
        }

    async def _entrer(self, motif: str) -> None:
        journal.info("Veille stricte (%s)", motif)
        for rappel in self.a_l_entree:
            try:
                await rappel(motif)
            except Exception:  # une étape ratée (Ollama injoignable…) n'empêche pas la veille
                journal.exception("Entrée en veille : étape en échec")

    async def regler(self, reglage: Reglage) -> None:
        avant = self.en_veille
        self.reglage = reglage
        if self.en_veille and not avant:
            await self._entrer("veille forcée" if reglage == "force" else f"jeu : {self.jeu}")

    async def observer(self, maintenant: float | None = None) -> None:
        """Un passage de détection (toutes les 3 s)."""
        if self.reglage != "automatique" or self.detecteur is None or not self.actif_detection():
            self._veille_auto, self._vu, self._vu_depuis = False, None, None
            return
        t = time.monotonic() if maintenant is None else maintenant
        premier = await asyncio.to_thread(self.detecteur.premier_plan)
        jeu = est_un_jeu(premier, self.jeux) if premier is not None else None
        if jeu is not None:
            self._absent_depuis = None
            if jeu != self._vu:
                self._vu, self._vu_depuis = jeu, t
            if not self._veille_auto and self._vu_depuis is not None and t - self._vu_depuis >= ENTREE_S:
                self._veille_auto, self.jeu = True, jeu
                await self._entrer(f"jeu : {jeu}")
            return
        self._vu, self._vu_depuis = None, None
        if self._veille_auto:
            if self._absent_depuis is None:
                self._absent_depuis = t
            elif t - self._absent_depuis >= SORTIE_S:
                journal.info("Fin de la veille stricte (plus de jeu au premier plan)")
                self._veille_auto, self.jeu, self._absent_depuis = False, None, None

    async def boucle(self) -> None:
        while True:
            try:
                await self.observer()
            except Exception:
                journal.exception("Détection du mode jeu en échec")
            await asyncio.sleep(INTERVALLE_S)
