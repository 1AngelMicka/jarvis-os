"""Mémoire du PC (RAM, VRAM) et recommandation de modèles locaux adaptés au matériel.

Lecture seule, sans dépendance : Windows (API système et registre des cartes graphiques), Linux (`/proc/meminfo`,
`nvidia-smi` s'il existe). La recommandation est une indication de taille, pas une liste figée de modèles.
"""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Any

GO = 1024**3


@dataclass(frozen=True)
class Materiel:
    ram_go: float | None
    vram_go: float | None
    carte: str | None


def _ram_windows() -> float | None:
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
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(etat)):  # type: ignore[attr-defined, unused-ignore]
        return None
    return round(float(etat.ullTotalPhys) / GO, 1)


def _vram_windows() -> tuple[float | None, str | None]:
    """Plus grande mémoire vidéo déclarée dans le registre (valeur 64 bits, fiable au-delà de 4 Go)."""
    import winreg  # type: ignore[import-not-found, unused-ignore]

    cle = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    meilleure: tuple[float | None, str | None] = (None, None)
    try:
        racine = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, cle)
    except OSError:
        return meilleure
    with racine:
        for i in range(32):
            try:
                nom = winreg.EnumKey(racine, i)
            except OSError:
                break
            try:
                with winreg.OpenKey(racine, nom) as carte:
                    taille, _ = winreg.QueryValueEx(carte, "HardwareInformation.qwMemorySize")
                    try:
                        libelle, _ = winreg.QueryValueEx(carte, "DriverDesc")
                    except OSError:
                        libelle = None
            except OSError:
                continue
            go = int(taille) / GO if isinstance(taille, int) else None
            if go and (meilleure[0] is None or go > meilleure[0]):
                meilleure = (round(go, 1), str(libelle) if libelle else None)
    return meilleure


def _linux() -> Materiel:
    ram = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for ligne in f:
                if ligne.startswith("MemTotal:"):
                    ram = round(int(ligne.split()[1]) * 1024 / GO, 1)
    except OSError:
        pass
    vram, carte = None, None
    if shutil.which("nvidia-smi"):
        try:
            sortie = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total,name", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            ).stdout
            premiere = sortie.strip().splitlines()[0].split(",")
            vram, carte = round(int(premiere[0]) / 1024, 1), premiere[1].strip()
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            pass
    return Materiel(ram, vram, carte)


def detecter() -> Materiel:
    if sys.platform == "win32":
        vram, carte = _vram_windows()
        return Materiel(_ram_windows(), vram, carte)
    return _linux()


def recommander(m: Materiel) -> list[dict[str, Any]]:
    """Tailles de modèles conseillées (quantification 4 bits), de la plus ambitieuse à la plus légère."""
    vram = m.vram_go or 0
    ram = m.ram_go or 0
    conseils: list[dict[str, Any]] = []
    if vram >= 20:
        conseils.append(
            {
                "taille": "24 à 32 milliards de paramètres",
                "ou": "carte graphique",
                "exemples": ["gemma 27B", "qwen 27–32B"],
                "raison": f"{vram:.0f} Go de mémoire vidéo",
            }
        )
    if vram >= 10:
        conseils.append(
            {
                "taille": "12 à 14 milliards",
                "ou": "carte graphique",
                "exemples": ["gemma 12B", "qwen 14B"],
                "raison": "rapide et de bonne qualité",
            }
        )
    if vram >= 6:
        conseils.append(
            {
                "taille": "7 à 9 milliards",
                "ou": "carte graphique",
                "exemples": ["llama 8B", "qwen 7B"],
                "raison": "réponses quasi instantanées",
            }
        )
    if not conseils:
        ou = "processeur (lent)" if ram >= 16 else "processeur, petits modèles seulement"
        conseils.append(
            {
                "taille": "1 à 4 milliards",
                "ou": ou,
                "exemples": ["qwen 2–4B", "gemma 2–4B"],
                "raison": "pas de carte graphique adaptée détectée",
            }
        )
    return conseils


def decrire() -> dict[str, Any]:
    m = detecter()
    return {**asdict(m), "recommandations": recommander(m)}
