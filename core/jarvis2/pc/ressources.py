"""Ressources du PC en direct : CPU, RAM, GPU, VRAM (lecture seule, sans dépendance, sans wmic).

- CPU : Windows `GetSystemTimes`, Linux `/proc/stat` (écart entre deux mesures).
- RAM : Windows `GlobalMemoryStatusEx`, Linux `/proc/meminfo`.
- GPU et VRAM : NVIDIA par `nvidia-smi` ; sous Windows, toutes marques (AMD compris) par les compteurs de
  performance du système (PDH : « GPU Engine » et « GPU Adapter Memory », ceux du Gestionnaire des tâches) ;
  sous Linux, AMD par `/sys/class/drm` (`gpu_busy_percent`, `mem_info_vram_used`).
- La VRAM totale vient de la détection du matériel (`materiel.py`).

Un historique de 10 minutes est gardé en mémoire (jamais en base) ; au-delà de 80 %, une alerte est signalée.
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import shutil
import subprocess
import sys
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from .. import materiel

_windll: Any = getattr(ctypes, "windll", None)
GO = 1024**3
SEUIL_ALERTE = 80.0
DUREE_HISTORIQUE = 600.0  # secondes
INTERVALLE = 5.0
SANS_FENETRE = 0x08000000


@dataclass(frozen=True)
class Echantillon:
    horodatage: float
    cpu: float | None  # %
    ram_utilisee_go: float | None
    ram_totale_go: float | None
    gpu: float | None  # % d'utilisation
    vram_utilisee_go: float | None
    vram_totale_go: float | None

    @property
    def ram(self) -> float | None:
        return _part(self.ram_utilisee_go, self.ram_totale_go)

    @property
    def vram(self) -> float | None:
        return _part(self.vram_utilisee_go, self.vram_totale_go)

    def alertes(self) -> list[str]:
        sortie = []
        for nom, valeur in (("CPU", self.cpu), ("RAM", self.ram), ("GPU", self.gpu), ("VRAM", self.vram)):
            if valeur is not None and valeur >= SEUIL_ALERTE:
                sortie.append(f"{nom} à {round(valeur)} %")
        return sortie

    def en_dict(self) -> dict[str, Any]:
        return {**asdict(self), "ram": self.ram, "vram": self.vram}


def _part(utilise: float | None, total: float | None) -> float | None:
    if utilise is None or not total:
        return None
    return round(min(100.0, utilise * 100 / total), 1)


class Mesureur(Protocol):
    def mesurer(self) -> Echantillon: ...


# --- Windows ---------------------------------------------------------------------------------------------------


class _Temps(ctypes.Structure):
    _fields_ = [("bas", ctypes.c_ulong), ("haut", ctypes.c_ulong)]

    @property
    def valeur(self) -> int:
        return int((self.haut << 32) | self.bas)


def _temps_windows() -> tuple[int, int] | None:
    """(inactif, total) du processeur depuis le démarrage."""
    inactif, noyau, utilisateur = _Temps(), _Temps(), _Temps()
    if not _windll.kernel32.GetSystemTimes(ctypes.byref(inactif), ctypes.byref(noyau), ctypes.byref(utilisateur)):
        return None
    return inactif.valeur, noyau.valeur + utilisateur.valeur  # le temps noyau inclut le temps inactif


def _ram_windows() -> tuple[float, float] | None:
    class Etat(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    etat = Etat()
    etat.dwLength = ctypes.sizeof(Etat)
    if not _windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(etat)):
        return None
    total = etat.ullTotalPhys / GO
    return round(total - etat.ullAvailPhys / GO, 2), round(total, 1)


class _ValeurPDH(ctypes.Structure):
    _fields_ = [("statut", ctypes.c_ulong), ("valeur", ctypes.c_double)]


class _ElementPDH(ctypes.Structure):
    _fields_ = [("nom", ctypes.c_wchar_p), ("valeur", _ValeurPDH)]


class CompteursGPU:
    """Compteurs de performance du GPU (Windows 10 1709 et plus, toutes marques). Une requête PDH gardée ouverte :
    l'utilisation est un taux, calculé entre deux collectes."""

    PLUS_DE_DONNEES = 0x800007D2
    FORMAT_DOUBLE = 0x00000200

    def __init__(self) -> None:
        self.pdh: Any = _windll.pdh if _windll is not None else None
        self.requete = ctypes.c_void_p()
        self.moteur = ctypes.c_void_p()
        self.memoire = ctypes.c_void_p()
        self.pret = False
        if self.pdh is None:
            return
        try:
            if self.pdh.PdhOpenQueryW(None, None, ctypes.byref(self.requete)) != 0:
                return
            ajouter = self.pdh.PdhAddEnglishCounterW
            ajouter.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p]
            ok = ajouter(self.requete, r"\GPU Engine(*engtype_3D)\Utilization Percentage", None,
                         ctypes.byref(self.moteur)) == 0  # fmt: skip
            ok = ajouter(self.requete, r"\GPU Adapter Memory(*)\Dedicated Usage", None,
                         ctypes.byref(self.memoire)) == 0 and ok  # fmt: skip
            self.pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
            self.pret = ok and self.pdh.PdhCollectQueryData(self.requete) == 0
        except (AttributeError, OSError):
            self.pret = False

    def _valeurs(self, compteur: ctypes.c_void_p) -> list[tuple[str, float]]:
        lire = self.pdh.PdhGetFormattedCounterArrayW
        lire.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        taille, nombre = ctypes.c_ulong(0), ctypes.c_ulong(0)
        statut = lire(compteur, self.FORMAT_DOUBLE, ctypes.byref(taille), ctypes.byref(nombre), None)
        if statut & 0xFFFFFFFF != self.PLUS_DE_DONNEES or taille.value == 0:
            return []
        tampon = ctypes.create_string_buffer(taille.value)
        if lire(compteur, self.FORMAT_DOUBLE, ctypes.byref(taille), ctypes.byref(nombre), tampon) != 0:
            return []
        elements = ctypes.cast(tampon, ctypes.POINTER(_ElementPDH))
        return [
            (elements[i].nom or "", elements[i].valeur.valeur)
            for i in range(nombre.value)
            if elements[i].valeur.statut in (0, 1)  # PDH_CSTATUS_VALID_DATA / NEW_DATA
        ]

    def lire(self) -> tuple[float | None, float | None]:
        """(utilisation %, VRAM dédiée utilisée en Go) de la carte la plus occupée."""
        if not self.pret or self.pdh.PdhCollectQueryData(self.requete) != 0:
            return None, None
        par_carte: dict[str, float] = {}
        for nom, valeur in self._valeurs(self.moteur):
            carte = nom.split("_phys_")[0].split("luid_")[-1] if "luid_" in nom else nom
            par_carte[carte] = par_carte.get(carte, 0.0) + valeur
        gpu = round(min(100.0, max(par_carte.values())), 1) if par_carte else None
        memoires = [v for _, v in self._valeurs(self.memoire)]
        vram = round(max(memoires) / GO, 2) if memoires else None
        return gpu, vram


# --- Linux -----------------------------------------------------------------------------------------------------


def _temps_linux(stat: Path = Path("/proc/stat")) -> tuple[int, int] | None:
    try:
        champs = [int(x) for x in stat.read_text().splitlines()[0].split()[1:]]
    except (OSError, ValueError, IndexError):
        return None
    inactif = champs[3] + (champs[4] if len(champs) > 4 else 0)
    return inactif, sum(champs[:8])


def _ram_linux(meminfo: Path = Path("/proc/meminfo")) -> tuple[float, float] | None:
    valeurs: dict[str, int] = {}
    try:
        for ligne in meminfo.read_text().splitlines():
            cle, _, reste = ligne.partition(":")
            valeurs[cle] = int(reste.split()[0])
    except (OSError, ValueError, IndexError):
        return None
    if "MemTotal" not in valeurs:
        return None
    total = valeurs["MemTotal"] / 1024**2
    dispo = valeurs.get("MemAvailable", valeurs.get("MemFree", 0)) / 1024**2
    return round(total - dispo, 2), round(total, 1)


def gpu_sysfs(drm: Path = Path("/sys/class/drm")) -> tuple[float | None, float | None]:
    """Carte AMD sous Linux : (utilisation %, VRAM utilisée en Go)."""
    for carte in sorted(drm.glob("card[0-9]")):
        dossier = carte / "device"
        with contextlib.suppress(OSError, ValueError):
            utilisee = int((dossier / "mem_info_vram_used").read_text().strip())
            occupation = None
            with contextlib.suppress(OSError, ValueError):
                occupation = float((dossier / "gpu_busy_percent").read_text().strip())
            return occupation, round(utilisee / GO, 2)
    return None, None


def lire_nvidia(sortie: str | None) -> tuple[float, float, float] | None:
    """Sortie de `nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits`."""
    if not sortie:
        return None
    meilleure: tuple[float, float, float] | None = None
    for ligne in sortie.strip().splitlines():
        try:
            gpu, utilisee, totale = (float(x) for x in ligne.split(",")[:3])
        except ValueError:
            continue
        if meilleure is None or totale > meilleure[2]:
            meilleure = (gpu, round(utilisee / 1024, 2), round(totale / 1024, 1))
    return meilleure


def _nvidia() -> tuple[float, float, float] | None:
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=SANS_FENETRE if sys.platform == "win32" else 0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return lire_nvidia(r.stdout) if r.returncode == 0 else None


class MesureurSysteme:
    """Mesure réelle, en lecture seule. Appelé dans un fil à part (quelques millisecondes)."""

    def __init__(self, detecter: Callable[[], materiel.Materiel] = materiel.detecter) -> None:
        self._detecter = detecter
        self._materiel: materiel.Materiel | None = None
        self._precedent: tuple[int, int] | None = None
        self._gpu: CompteursGPU | None = None
        self._nvidia = shutil.which("nvidia-smi") is not None

    def _vram_totale(self) -> float | None:
        if self._materiel is None:
            try:
                self._materiel = self._detecter()
            except Exception:  # détection impossible : la VRAM totale reste inconnue
                self._materiel = materiel.Materiel(None, None, None)
        return None if self._materiel.memoire_unifiee else self._materiel.vram_go

    def _cpu(self) -> float | None:
        temps = _temps_windows() if sys.platform == "win32" and _windll is not None else _temps_linux()
        if temps is None:
            return None
        precedent, self._precedent = self._precedent, temps
        if precedent is None:
            time.sleep(0.2)  # première mesure : un court écart pour avoir une valeur tout de suite
            return self._cpu()
        inactif, total = temps[0] - precedent[0], temps[1] - precedent[1]
        return round(max(0.0, min(100.0, 100 * (1 - inactif / total))), 1) if total > 0 else None

    def mesurer(self) -> Echantillon:
        windows = sys.platform == "win32" and _windll is not None
        ram = _ram_windows() if windows else _ram_linux()
        gpu = vram = None
        vram_totale = self._vram_totale()
        nvidia = _nvidia() if self._nvidia else None
        if nvidia is not None:
            gpu, vram, vram_totale = nvidia
        elif windows:
            if self._gpu is None:
                self._gpu = CompteursGPU()
            gpu, vram = self._gpu.lire()
        elif sys.platform.startswith("linux"):
            gpu, vram = gpu_sysfs()
        return Echantillon(
            time.time(),
            self._cpu(),
            ram[0] if ram else None,
            ram[1] if ram else None,
            gpu,
            vram,
            vram_totale,
        )


class Historique:
    """Dernières 10 minutes, en mémoire. La boucle ne mesure que si quelqu'un regarde (vue ouverte ces 2 dernières
    minutes) : rien ne tourne pour rien, surtout en mode jeu."""

    def __init__(self, mesureur: Mesureur, intervalle: float = INTERVALLE) -> None:
        self.mesureur = mesureur
        self.intervalle = intervalle
        self.points: deque[Echantillon] = deque(maxlen=int(DUREE_HISTORIQUE / intervalle) + 1)
        self.vu_le = 0.0
        self._verrou = asyncio.Lock()

    async def mesurer(self) -> Echantillon:
        async with self._verrou:
            e = await asyncio.to_thread(self.mesureur.mesurer)
            self.points.append(e)
            return e

    async def actuel(self) -> Echantillon:
        """Dernière mesure si elle a moins d'un intervalle, sinon une nouvelle."""
        self.vu_le = time.monotonic()
        if self.points and time.time() - self.points[-1].horodatage < self.intervalle:
            return self.points[-1]
        return await self.mesurer()

    def courbe(self) -> list[dict[str, Any]]:
        limite = time.time() - DUREE_HISTORIQUE
        return [
            {"t": round(p.horodatage), "cpu": p.cpu, "ram": p.ram, "gpu": p.gpu, "vram": p.vram}
            for p in self.points
            if p.horodatage >= limite
        ]

    async def boucle(self) -> None:
        while True:
            if time.monotonic() - self.vu_le < 120:
                with contextlib.suppress(Exception):  # une mesure ratée n'arrête pas la boucle
                    await self.mesurer()
            await asyncio.sleep(self.intervalle)
