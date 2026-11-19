"""Matériel du PC (RAM, carte graphique) et UNE table déclarative matériel → modèle conseillé par usage.

Lecture seule, sans dépendance, sans rien installer ni démarrer (Ollama compris) :
- RAM : Windows par l'API système (`GlobalMemoryStatusEx`, sans wmic), Linux par `/proc/meminfo`, macOS par
  `sysctl hw.memsize`.
- Carte graphique : NVIDIA par `nvidia-smi` s'il existe ; AMD par `rocm-smi` s'il existe, sinon le registre Windows
  ou `/sys/class/drm` sous Linux ; Apple Silicon (mémoire unifiée) ; sinon repli sur le processeur.

Le conseil prend, pour chaque usage, le plus gros palier qui tient dans la mémoire utile, puis descend d'un palier
pour garder de la marge (contexte long, autres programmes, jeux). Le maximum est donné aussi, à titre indicatif.
Les noms de modèles sont des exemples à vérifier dans le catalogue d'Ollama : rien n'est téléchargé par JARVIS.
"""

from __future__ import annotations

import contextlib
import ctypes
import functools
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

GO = 1024**3
MEMINFO = Path("/proc/meminfo")
DRM = Path("/sys/class/drm")
DELAI_COMMANDE = 5.0

TypeCarte = Literal["nvidia", "amd", "apple", "intel", "autre", "aucune"]
Acceleration = Literal["cuda", "rocm", "vulkan", "metal", "processeur"]
Ressource = Literal["vram", "ram"]

LIBELLES_ACCELERATION: dict[str, str] = {
    "cuda": "CUDA",
    "rocm": "ROCm",
    "vulkan": "Vulkan, expérimental",
    "metal": "Metal",
    "processeur": "non utilisée",
}
VRAM_MINIMUM = 4.0  # en dessous (cartes intégrées), la carte n'aide pas : repli sur le processeur
PART_UNIFIEE = 0.7  # Apple Silicon : part de la mémoire unifiée que le GPU peut raisonnablement prendre
PART_PROCESSEUR = 0.5  # sans carte : part de la RAM laissée aux modèles

# Cartes AMD prises en charge par ROCm (et par Ollama sous Windows) : Radeon RX 6800 et plus, RX 7000, RX 9000,
# Radeon Pro W6800/W7000, Instinct. Les autres cartes AMD passent par Vulkan (expérimental dans Ollama).
_AMD_ROCM = re.compile(r"RX\s*(6[89]\d\d|[79]\d\d\d)|PRO\s*W(6[89]|7\d)\d\d|INSTINCT|MI\d{2,3}", re.IGNORECASE)


@dataclass(frozen=True)
class Materiel:
    ram_go: float | None
    vram_go: float | None
    carte: str | None
    type_carte: TypeCarte = "aucune"
    acceleration: Acceleration = "processeur"
    memoire_unifiee: bool = False
    sources: tuple[str, ...] = ()  # d'où viennent les chiffres (diagnostic)

    def budget(self, ressource: Ressource) -> float:
        """Mémoire utile (Go) pour un modèle selon la ressource qu'il occupe."""
        ram = self.ram_go or 0.0
        if ressource == "ram":
            return ram
        if self.memoire_unifiee:
            return round(ram * PART_UNIFIEE, 1)
        if self.acceleration != "processeur" and (self.vram_go or 0) >= VRAM_MINIMUM:
            return self.vram_go or 0.0
        return round(ram * PART_PROCESSEUR, 1)

    @property
    def sur_carte(self) -> bool:
        return self.memoire_unifiee or (self.acceleration != "processeur" and (self.vram_go or 0) >= VRAM_MINIMUM)


# ---------------------------------------------------------------- la table


@dataclass(frozen=True)
class Palier:
    besoin_go: float  # mémoire nécessaire, contexte compris (quantification 4 bits pour les LLM)
    taille: str
    modele: str  # modèle conseillé (nom Ollama, Whisper ou fastembed selon l'usage)
    exemples: tuple[str, ...] = ()


@dataclass(frozen=True)
class Usage:
    id: str
    titre: str
    ressource: Ressource  # « vram » : carte graphique, ou mémoire unifiée, ou à défaut une part de la RAM
    paliers: tuple[Palier, ...]  # du plus léger au plus lourd
    marge: bool = True  # descendre d'un palier sous le maximum
    plafond_processeur: str | None = None  # sans carte : palier le plus gros encore utilisable (lenteur)
    note: str = ""


TABLE: tuple[Usage, ...] = (
    Usage(
        "conversation",
        "Conversation (Ollama)",
        "vram",
        (
            Palier(3, "1 à 2 milliards", "qwen3.5:2b", ("gemma 2B",)),
            Palier(5, "3 à 4 milliards", "qwen3.5:4b", ("gemma 4B", "phi 4 mini")),
            Palier(8, "7 à 9 milliards", "qwen3.5:9b", ("llama 8B", "mistral 7B")),
            Palier(11, "12 à 14 milliards", "gemma4:12b", ("qwen 14B",)),
            Palier(21, "24 à 32 milliards", "qwen3.5:27b", ("gemma 27B", "mistral small 24B")),
            Palier(44, "70 milliards", "llama3.3:70b", ("qwen 72B",)),
        ),
        plafond_processeur="7 à 9 milliards",
        note="Quantification 4 bits ; le maximum laisse peu de place au contexte long.",
    ),
    Usage(
        "vision",
        "Vision (Ollama)",
        "vram",
        (
            Palier(3, "2 milliards", "qwen3.5:2b"),
            Palier(8, "7 milliards", "qwen2.5vl:7b", ("llava 7B",)),
            Palier(22, "32 milliards", "qwen2.5vl:32b"),
        ),
        plafond_processeur="2 milliards",
        note="Utilisé pour le bouton « Écran » et les images jointes ([connecteurs.ollama] modele_vision).",
    ),
    Usage(
        "embeddings",
        "Mémoire (embeddings)",
        "ram",
        (
            Palier(2, "MiniLM, 384 dimensions", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
            Palier(8, "multilingue, 1024 dimensions", "BAAI/bge-m3"),
        ),
        marge=False,  # taille fixe, chargé une fois sur le processeur
        note="Changer de modèle demande un ré-encodage de la mémoire (JARVIS2_MODELE_EMBEDDINGS).",
    ),
    Usage(
        "transcription",
        "Transcription (Whisper)",
        "ram",
        (
            Palier(2, "tiny", "tiny"),
            Palier(4, "base", "base"),
            Palier(8, "small", "small"),
            Palier(16, "medium", "medium"),
            Palier(32, "large-v3", "large-v3"),
        ),
        note="Sur le processeur (int8) ; JARVIS2_MODELE_VOIX.",
    ),
)


def _choisir(usage: Usage, m: Materiel) -> tuple[int | None, int | None]:
    """Indices (conseillé, maximum) dans `usage.paliers` ; None si rien ne tient."""
    budget = m.budget(usage.ressource)
    paliers = usage.paliers
    if usage.ressource == "vram" and not m.sur_carte and usage.plafond_processeur:
        tailles = [p.taille for p in paliers]
        if usage.plafond_processeur in tailles:
            paliers = paliers[: tailles.index(usage.plafond_processeur) + 1]
    tiennent = [i for i, p in enumerate(paliers) if p.besoin_go <= budget]
    if not tiennent:
        return (None, None)
    maximum = tiennent[-1]
    conseille = max(0, maximum - 1) if usage.marge else maximum
    return (conseille, maximum)


def _ou(usage: Usage, m: Materiel) -> str:
    if usage.ressource == "ram":
        return "processeur"
    if m.memoire_unifiee:
        return "puce Apple (mémoire unifiée)"
    if m.sur_carte:
        return f"carte graphique ({LIBELLES_ACCELERATION[m.acceleration]})"
    return "processeur (lent)"


def conseiller(m: Materiel, table: Sequence[Usage] = TABLE) -> list[dict[str, Any]]:
    """Un conseil par usage : modèle conseillé (un palier sous le maximum) et maximum indicatif."""
    sorties: list[dict[str, Any]] = []
    for usage in table:
        i_conseil, i_max = _choisir(usage, m)
        budget = m.budget(usage.ressource)
        entree: dict[str, Any] = {
            "usage": usage.id,
            "titre": usage.titre,
            "ou": _ou(usage, m),
            "budget_go": budget,
            "note": usage.note,
            "conseille": None,
            "maximum": None,
        }
        if i_conseil is not None and i_max is not None:
            p, pm = usage.paliers[i_conseil], usage.paliers[i_max]
            entree["conseille"] = {
                "taille": p.taille,
                "modele": p.modele,
                "besoin_go": p.besoin_go,
                "exemples": list(p.exemples),
            }
            entree["maximum"] = {"taille": pm.taille, "modele": pm.modele, "besoin_go": pm.besoin_go}
            entree["raison"] = f"{budget:g} Go utiles : jusqu'à « {pm.taille} »" + (
                ", un palier en dessous pour garder de la marge" if i_conseil != i_max else ""
            )
        else:
            entree["raison"] = f"{budget:g} Go utiles : trop peu pour un modèle local de cet usage"
        sorties.append(entree)
    return sorties


# ---------------------------------------------------------------- détection

Executer = Callable[[Sequence[str]], str | None]


def _executer(commande: Sequence[str]) -> str | None:
    """Sortie d'un outil s'il est installé ; None sinon (jamais d'installation, jamais de démarrage de service)."""
    if not shutil.which(commande[0]):
        return None
    try:
        r = subprocess.run(list(commande), capture_output=True, text=True, timeout=DELAI_COMMANDE, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def type_depuis_nom(nom: str | None) -> TypeCarte:
    n = (nom or "").lower()
    if any(x in n for x in ("nvidia", "geforce", "quadro", "tesla", "rtx")):
        return "nvidia"
    if any(x in n for x in ("amd", "radeon", "advanced micro devices", "instinct")):
        return "amd"
    if "apple" in n:
        return "apple"
    if "intel" in n or "arc" in n.split():
        return "intel"
    return "autre" if n else "aucune"


def acceleration_amd(nom: str | None, rocm_installe: bool = False) -> Acceleration:
    """ROCm pour les cartes qu'il prend en charge (Ollama embarque ses bibliothèques), Vulkan sinon."""
    return "rocm" if (rocm_installe or _AMD_ROCM.search(nom or "")) else "vulkan"


def lire_nvidia_smi(sortie: str | None) -> tuple[float, str] | None:
    """`nvidia-smi --query-gpu=memory.total,name --format=csv,noheader,nounits` → (Go, nom) de la plus grosse carte."""
    meilleure: tuple[float, str] | None = None
    for ligne in (sortie or "").strip().splitlines():
        morceaux = [x.strip() for x in ligne.split(",", 1)]
        try:
            go = round(int(morceaux[0]) / 1024, 1)
        except (ValueError, IndexError):
            continue
        nom = morceaux[1] if len(morceaux) > 1 else "NVIDIA"
        if meilleure is None or go > meilleure[0]:
            meilleure = (go, nom)
    return meilleure


def lire_rocm_smi(memoire: str | None, noms: str | None = None) -> tuple[float, str] | None:
    """`rocm-smi --showmeminfo vram --json` (+ `--showproductname --json`) → (Go, nom) de la plus grosse carte."""
    try:
        mem = json.loads(memoire or "")
    except ValueError:
        return None
    try:
        prod = json.loads(noms or "{}")
    except ValueError:
        prod = {}
    meilleure: tuple[float, str] | None = None
    if not isinstance(mem, dict):
        return None
    for carte, valeurs in mem.items():
        if not isinstance(valeurs, dict):
            continue
        total = next((v for k, v in valeurs.items() if "total memory" in k.lower() and "used" not in k.lower()), None)
        try:
            go = round(int(str(total)) / GO, 1)
        except (TypeError, ValueError):
            continue
        infos = prod.get(carte, {}) if isinstance(prod, dict) else {}
        nom = next(
            (str(v) for k, v in infos.items() if k.lower() in ("card series", "card model", "card sku")), "Carte AMD"
        )
        if meilleure is None or go > meilleure[0]:
            meilleure = (go, nom)
    return meilleure


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


def _cartes_registre_windows() -> list[tuple[float, str]]:
    """Cartes du registre (valeur 64 bits `qwMemorySize`, fiable au-delà de 4 Go, toutes marques)."""
    if sys.platform != "win32":  # registre Windows ; mypy ne vérifie la suite que pour Windows
        return []
    import winreg

    cle = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    cartes: list[tuple[float, str]] = []
    try:
        racine = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, cle)
    except OSError:
        return cartes
    with racine:
        for i in range(32):
            try:
                nom = winreg.EnumKey(racine, i)
            except OSError:
                break
            try:
                with winreg.OpenKey(racine, nom) as carte:
                    taille, _ = winreg.QueryValueEx(carte, "HardwareInformation.qwMemorySize")
                    libelle = ""
                    for valeur in ("DriverDesc", "ProviderName"):
                        with contextlib.suppress(OSError):
                            libelle = f"{libelle} {winreg.QueryValueEx(carte, valeur)[0]}".strip()
            except OSError:
                continue
            if isinstance(taille, int) and taille > 0:
                cartes.append((round(taille / GO, 1), libelle))
    return cartes


def _nom_registre(libelle: str) -> str:
    """« Radeon RX 7900 XTX Advanced Micro Devices, Inc. » → « Radeon RX 7900 XTX » (le fournisseur sert au type)."""
    for fournisseur in ("Advanced Micro Devices, Inc.", "NVIDIA", "Intel Corporation"):
        if libelle.endswith(fournisseur) and libelle != fournisseur:
            return libelle[: -len(fournisseur)].strip()
    return libelle


def _rocm_windows() -> bool:
    return (
        bool(os.environ.get("HIP_PATH"))
        or Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"), "AMD", "ROCm").is_dir()
    )


def _ram_linux(meminfo: Path | None = None) -> float | None:
    try:
        with (meminfo or MEMINFO).open(encoding="utf-8") as f:
            for ligne in f:
                if ligne.startswith("MemTotal:"):
                    return round(int(ligne.split()[1]) * 1024 / GO, 1)
    except (OSError, ValueError, IndexError):
        pass
    return None


def _amd_sysfs(drm: Path | None = None) -> tuple[float, str] | None:
    """Pilote amdgpu : `card*/device/mem_info_vram_total` (octets), fabricant 0x1002."""
    meilleure: tuple[float, str] | None = None
    drm = drm or DRM
    if not drm.is_dir():
        return None
    for vram in drm.glob("card*/device/mem_info_vram_total"):
        try:
            if (vram.parent / "vendor").read_text(encoding="utf-8").strip().lower() != "0x1002":
                continue
            go = round(int(vram.read_text(encoding="utf-8").strip()) / GO, 1)
        except (OSError, ValueError):
            continue
        if meilleure is None or go > meilleure[0]:
            meilleure = (go, "Carte AMD")
    return meilleure


def _carte_commune(executer: Executer) -> tuple[Materiel | None, list[str]]:
    """NVIDIA puis AMD par leurs outils, s'ils sont installés."""
    nv = lire_nvidia_smi(executer(["nvidia-smi", "--query-gpu=memory.total,name", "--format=csv,noheader,nounits"]))
    if nv:
        return Materiel(None, nv[0], nv[1], "nvidia", "cuda"), ["nvidia-smi"]
    memoire = executer(["rocm-smi", "--showmeminfo", "vram", "--json"])
    if memoire:
        amd = lire_rocm_smi(memoire, executer(["rocm-smi", "--showproductname", "--json"]))
        if amd:
            return Materiel(None, amd[0], amd[1], "amd", "rocm"), ["rocm-smi"]
    return None, []


def _windows(executer: Executer) -> Materiel:
    ram = _ram_windows()
    commune, sources = _carte_commune(executer)
    sources = ["GlobalMemoryStatusEx", *sources]
    if commune:
        return Materiel(
            ram, commune.vram_go, commune.carte, commune.type_carte, commune.acceleration, False, tuple(sources)
        )
    cartes = sorted(_cartes_registre_windows(), reverse=True)
    if not cartes:
        return Materiel(ram, None, None, sources=tuple(sources))
    go, libelle = cartes[0]
    type_carte = type_depuis_nom(libelle)
    nom = _nom_registre(libelle) or None
    acc: Acceleration = "processeur"
    if type_carte == "nvidia":
        acc = "cuda"
    elif type_carte == "amd":
        acc = acceleration_amd(nom, _rocm_windows())
    elif type_carte == "intel":
        acc = "vulkan"
    return Materiel(ram, go, nom, type_carte, acc, False, (*sources, "registre"))


def _linux(executer: Executer) -> Materiel:
    ram = _ram_linux()
    commune, sources = _carte_commune(executer)
    sources = ["/proc/meminfo", *sources]
    if commune:
        return Materiel(
            ram, commune.vram_go, commune.carte, commune.type_carte, commune.acceleration, False, tuple(sources)
        )
    amd = _amd_sysfs()
    if amd:
        return Materiel(
            ram, amd[0], amd[1], "amd", acceleration_amd(amd[1], Path("/opt/rocm").is_dir()), False, (*sources, "sysfs")
        )
    return Materiel(ram, None, None, sources=tuple(sources))


def _macos(executer: Executer, machine: str) -> Materiel:
    ram = None
    sortie = executer(["sysctl", "-n", "hw.memsize"])
    with contextlib.suppress(ValueError):
        ram = round(int((sortie or "").strip()) / GO, 1)
    if machine == "arm64":
        puce = (executer(["sysctl", "-n", "machdep.cpu.brand_string"]) or "Apple Silicon").strip()
        return Materiel(ram, None, puce, "apple", "metal", True, ("sysctl",))
    return Materiel(ram, None, None, sources=("sysctl",))


def detecter_sans_cache(
    executer: Executer = _executer, plateforme: str = sys.platform, machine: str | None = None
) -> Materiel:
    if plateforme == "win32":
        return _windows(executer)
    if plateforme == "darwin":
        return _macos(executer, machine or platform.machine())
    return _linux(executer)


@functools.cache
def detecter() -> Materiel:
    """Le matériel ne change pas pendant que le Core tourne : une seule détection."""
    return detecter_sans_cache()


def resume(m: Materiel) -> str:
    ram = f"{m.ram_go:g} Go de RAM" if m.ram_go else "RAM inconnue"
    if m.memoire_unifiee:
        return f"{ram} · {m.carte} (mémoire unifiée, Metal)"
    if m.carte and m.vram_go:
        return f"{ram} · {m.carte} ({m.vram_go:g} Go, {LIBELLES_ACCELERATION[m.acceleration]})"
    return f"{ram} · pas de carte graphique adaptée : processeur"


@dataclass
class Description:
    materiel: Materiel
    conseils: list[dict[str, Any]] = field(default_factory=list)

    def en_dict(self) -> dict[str, Any]:
        return {**asdict(self.materiel), "resume": resume(self.materiel), "conseils": self.conseils}


def decrire(m: Materiel | None = None) -> dict[str, Any]:
    m = m or detecter()
    return Description(m, conseiller(m)).en_dict()
