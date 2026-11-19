"""Table matériel → modèle et détection, avec du matériel simulé (aucun outil réel appelé)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from jarvis2 import diagnostic, materiel
from jarvis2.materiel import Materiel, conseiller, decrire, detecter_sans_cache


def _conseil(m: Materiel, usage: str) -> dict:  # type: ignore[type-arg]
    return next(c for c in conseiller(m) if c["usage"] == usage)


RX_7900_XTX = Materiel(64, 24, "Radeon RX 7900 XTX", "amd", "rocm")


def test_un_palier_sous_le_maximum_avec_une_carte_amd() -> None:
    c = _conseil(RX_7900_XTX, "conversation")
    assert c["maximum"]["taille"] == "24 à 32 milliards"
    assert c["conseille"]["taille"] == "12 à 14 milliards"
    assert c["ou"] == "carte graphique (ROCm)"
    assert "marge" in c["raison"]


def test_un_conseil_par_usage() -> None:
    usages = [c["usage"] for c in conseiller(RX_7900_XTX)]
    assert usages == ["conversation", "vision", "embeddings", "transcription"]
    emb = _conseil(RX_7900_XTX, "embeddings")
    assert emb["conseille"]["modele"] == "BAAI/bge-m3"  # sans marge : taille fixe
    voix = _conseil(RX_7900_XTX, "transcription")
    assert (voix["maximum"]["modele"], voix["conseille"]["modele"]) == ("large-v3", "medium")


def test_repli_processeur_plafonne_et_lent() -> None:
    m = Materiel(32, None, None)
    c = _conseil(m, "conversation")
    assert c["budget_go"] == 16
    assert c["maximum"]["taille"] == "7 à 9 milliards"  # plafond processeur malgré 16 Go
    assert c["conseille"]["taille"] == "3 à 4 milliards"
    assert c["ou"] == "processeur (lent)"


def test_carte_integree_ignoree() -> None:
    m = Materiel(16, 0.5, "AMD Radeon(TM) Graphics", "amd", "vulkan")
    assert not m.sur_carte
    assert _conseil(m, "conversation")["ou"] == "processeur (lent)"


def test_apple_silicon_memoire_unifiee() -> None:
    m = Materiel(32, None, "Apple M2 Pro", "apple", "metal", True)
    c = _conseil(m, "conversation")
    assert c["budget_go"] == 22.4
    assert c["maximum"]["taille"] == "24 à 32 milliards"
    assert c["conseille"]["taille"] == "12 à 14 milliards"


def test_trop_peu_de_memoire() -> None:
    c = _conseil(Materiel(2, None, None), "conversation")
    assert c["conseille"] is None and "trop peu" in c["raison"]
    assert _conseil(Materiel(None, None, None), "transcription")["conseille"] is None


def test_petit_budget_garde_le_plus_petit_palier() -> None:
    c = _conseil(Materiel(16, 4, "GeForce GTX 1650", "nvidia", "cuda"), "conversation")
    assert c["maximum"]["taille"] == c["conseille"]["taille"] == "1 à 2 milliards"


@pytest.mark.parametrize(
    ("nom", "attendu"),
    [
        ("Radeon RX 7900 XTX", "rocm"),
        ("AMD Radeon RX 6800 XT", "rocm"),
        ("AMD Radeon RX 9070 XT", "rocm"),
        ("AMD Radeon RX 580", "vulkan"),
        ("AMD Radeon(TM) Graphics", "vulkan"),
    ],
)
def test_acceleration_amd(nom: str, attendu: str) -> None:
    assert materiel.acceleration_amd(nom) == attendu


def test_types_de_carte() -> None:
    assert materiel.type_depuis_nom("NVIDIA GeForce RTX 4090") == "nvidia"
    assert materiel.type_depuis_nom("Radeon RX 7900 XTX Advanced Micro Devices, Inc.") == "amd"
    assert materiel.type_depuis_nom("Intel(R) Arc(TM) A770 Graphics") == "intel"
    assert materiel.type_depuis_nom(None) == "aucune"


def test_lecture_nvidia_smi() -> None:
    assert materiel.lire_nvidia_smi("8192, RTX 3070\n24576, NVIDIA GeForce RTX 4090\n") == (
        24.0,
        "NVIDIA GeForce RTX 4090",
    )
    assert materiel.lire_nvidia_smi("") is None
    assert materiel.lire_nvidia_smi("[N/A], X") is None


def test_lecture_rocm_smi() -> None:
    mem = json.dumps(
        {
            "card0": {"VRAM Total Memory (B)": str(24 * 1024**3), "VRAM Total Used Memory (B)": "123"},
            "card1": {"VRAM Total Memory (B)": str(512 * 1024**2)},
        }
    )
    noms = json.dumps({"card0": {"Card Series": "Radeon RX 7900 XTX"}})
    assert materiel.lire_rocm_smi(mem, noms) == (24.0, "Radeon RX 7900 XTX")
    assert materiel.lire_rocm_smi("pas du json") is None


def _faux(sorties: dict[str, str]):  # type: ignore[no-untyped-def]
    appels: list[str] = []

    def executer(commande: Sequence[str]) -> str | None:
        cle = " ".join(commande)
        appels.append(cle)
        return next((v for k, v in sorties.items() if cle.startswith(k)), None)

    return executer, appels


def test_detection_windows_amd_par_le_registre(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(materiel, "_ram_windows", lambda: 63.9)
    monkeypatch.setattr(
        materiel,
        "_cartes_registre_windows",
        lambda: [
            (0.5, "AMD Radeon(TM) Graphics Advanced Micro Devices, Inc."),
            (24.0, "Radeon RX 7900 XTX Advanced Micro Devices, Inc."),
        ],
    )
    monkeypatch.setattr(materiel, "_rocm_windows", lambda: False)
    executer, appels = _faux({})
    m = detecter_sans_cache(executer, "win32")
    assert (m.ram_go, m.vram_go, m.carte, m.type_carte, m.acceleration) == (
        63.9,
        24.0,
        "Radeon RX 7900 XTX",
        "amd",
        "rocm",
    )
    assert "registre" in m.sources and not any("wmic" in a for a in appels)
    assert "ROCm" in materiel.resume(m)


def test_detection_windows_nvidia_smi_prioritaire(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(materiel, "_ram_windows", lambda: 32.0)
    monkeypatch.setattr(materiel, "_cartes_registre_windows", lambda: [(4.0, "NVIDIA GeForce RTX 4080")])
    executer, _ = _faux({"nvidia-smi": "16376, NVIDIA GeForce RTX 4080\n"})
    m = detecter_sans_cache(executer, "win32")
    assert (m.vram_go, m.type_carte, m.acceleration) == (16.0, "nvidia", "cuda")


def test_detection_linux_amd_sysfs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    carte = tmp_path / "card0" / "device"
    carte.mkdir(parents=True)
    (carte / "vendor").write_text("0x1002\n")
    (carte / "mem_info_vram_total").write_text(str(24 * 1024**3))
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       65536000 kB\n")
    monkeypatch.setattr(materiel, "MEMINFO", meminfo)
    monkeypatch.setattr(materiel, "DRM", tmp_path)
    executer, _ = _faux({})
    m = detecter_sans_cache(executer, "linux")
    assert (m.ram_go, m.vram_go, m.type_carte) == (62.5, 24.0, "amd")


def test_lecture_ram_linux(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       65536000 kB\nMemFree: 1 kB\n")
    assert materiel._ram_linux(meminfo) == 62.5
    assert materiel._ram_linux(tmp_path / "absent") is None


def test_detection_linux_rocm_smi() -> None:
    mem = json.dumps({"card0": {"VRAM Total Memory (B)": str(16 * 1024**3)}})
    executer, _ = _faux({"rocm-smi --showmeminfo": mem, "rocm-smi --showproductname": "{}"})
    m = detecter_sans_cache(executer, "linux")
    assert (m.vram_go, m.type_carte, m.acceleration) == (16.0, "amd", "rocm")


def test_detection_macos_apple_silicon() -> None:
    executer, _ = _faux({"sysctl -n hw.memsize": str(32 * 1024**3), "sysctl -n machdep": "Apple M3 Max\n"})
    m = detecter_sans_cache(executer, "darwin", "arm64")
    assert (m.ram_go, m.carte, m.memoire_unifiee, m.acceleration) == (32.0, "Apple M3 Max", True, "metal")
    assert "mémoire unifiée" in materiel.resume(m)


def test_detection_macos_intel_repli_processeur() -> None:
    executer, _ = _faux({"sysctl -n hw.memsize": str(16 * 1024**3)})
    m = detecter_sans_cache(executer, "darwin", "x86_64")
    assert (m.ram_go, m.acceleration, m.memoire_unifiee) == (16.0, "processeur", False)


def test_decrire_et_docteur(monkeypatch: pytest.MonkeyPatch) -> None:
    d = decrire(RX_7900_XTX)
    assert d["type_carte"] == "amd" and len(d["conseils"]) == 4 and d["resume"]
    monkeypatch.setattr(materiel, "detecter", lambda: RX_7900_XTX)
    v = diagnostic.verifier_materiel()
    assert v.id == "materiel" and v.statut == "info"
    assert "Radeon RX 7900 XTX" in v.detail and "gemma4:12b" in v.detail
    assert "ollama pull" in (v.aide or "")


def test_commande_materiel_pour_les_installeurs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from jarvis2.__main__ import main

    monkeypatch.setattr(materiel, "detecter", lambda: RX_7900_XTX)
    assert main(["materiel", "--modele", "conversation"]) == 0
    assert capsys.readouterr().out == "gemma4:12b\t11\t12 à 14 milliards\n"
    assert main(["materiel", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["type_carte"] == "amd"
    assert main(["materiel"]) == 0
    assert "Conversation (Ollama) : gemma4:12b" in capsys.readouterr().out


def test_commande_materiel_rien_ne_tient(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from jarvis2.__main__ import main

    monkeypatch.setattr(materiel, "detecter", lambda: Materiel(2, None, None))
    assert main(["materiel", "--modele", "conversation"]) == 1
    assert capsys.readouterr().out == ""
