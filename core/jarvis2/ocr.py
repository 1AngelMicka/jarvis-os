"""Lecture du texte d'une image (OCR), avant tout modèle de vision.

Ordre (lot J) : d'abord l'OCR, rapide et sans carte graphique ; le modèle de vision local (Ollama) seulement si
l'image contient peu de texte. Rien ne sort du PC, l'image n'est jamais gardée (fichier temporaire effacé).

Moteurs, en lecture seule, sans dépendance Python :
- Windows : l'OCR intégré au système (Windows.Media.Ocr, langues de l'utilisateur), appelé par PowerShell ;
- sinon `tesseract` s'il est installé (langues fra + eng).
"""

# ruff: noqa: E501 — scripts PowerShell gardés sur une ligne par instruction
from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Protocol

MIN_CARACTERES = 40  # en dessous (lettres et chiffres), on considère qu'il y a « peu de texte »
MIN_MOTS = 6
SANS_FENETRE = 0x08000000


class LecteurOCR(Protocol):
    nom: str

    def lire(self, image: bytes) -> str: ...


def assez_de_texte(texte: str | None) -> bool:
    if not texte:
        return False
    return len(re.findall(r"\w", texte)) >= MIN_CARACTERES and len(re.findall(r"\w{2,}", texte)) >= MIN_MOTS


def _extension(image: bytes) -> str:
    if image.startswith(b"\x89PNG"):
        return ".png"
    if image.startswith(b"\xff\xd8"):
        return ".jpg"
    return ".webp" if image[8:12] == b"WEBP" else ".img"


SCRIPT_OCR = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Attendre($op, [Type]$type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
$F = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$S = [Windows.Storage.Streams.IRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime]
$D = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$B = [Windows.Graphics.Imaging.SoftwareBitmap,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$O = [Windows.Media.Ocr.OcrEngine,Windows.Media.Ocr,ContentType=WindowsRuntime]
$R = [Windows.Media.Ocr.OcrResult,Windows.Media.Ocr,ContentType=WindowsRuntime]
$f = Attendre ($F::GetFileFromPathAsync($env:JARVIS_IMAGE)) $F
$s = Attendre ($f.OpenAsync([Windows.Storage.FileAccessMode]::Read)) $S
$d = Attendre ($D::CreateAsync($s)) $D
$b = Attendre ($d.GetSoftwareBitmapAsync()) $B
$e = $O::TryCreateFromUserProfileLanguages()
if (-not $e) { exit 3 }
$r = Attendre ($e.RecognizeAsync($b)) $R
($r.Lines | ForEach-Object { $_.Text }) -join "`n"
$s.Dispose()
"""


class OcrWindows:
    nom = "windows"

    def lire(self, image: bytes) -> str:
        from .pc.windows import powershell

        fd, chemin = tempfile.mkstemp(prefix="jarvis-ocr-", suffix=_extension(image))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(image)
            return powershell(SCRIPT_OCR, {"JARVIS_IMAGE": chemin}, delai=30.0)
        finally:
            with contextlib.suppress(OSError):
                Path(chemin).unlink()


class OcrTesseract:
    nom = "tesseract"

    def __init__(self, executable: str) -> None:
        self.executable = executable

    def lire(self, image: bytes) -> str:
        try:
            r = subprocess.run(
                [self.executable, "stdin", "stdout", "-l", "fra+eng"],
                input=image,
                capture_output=True,
                timeout=60,
                creationflags=SANS_FENETRE if sys.platform == "win32" else 0,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"tesseract indisponible : {exc}") from exc
        if r.returncode != 0:
            raise RuntimeError("tesseract a échoué")
        return r.stdout.decode("utf-8", errors="replace").strip()


def choisir() -> LecteurOCR | None:
    if sys.platform == "win32":
        return OcrWindows()
    executable = shutil.which("tesseract")
    return OcrTesseract(executable) if executable else None
