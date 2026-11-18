"""Coffre local des clés d'API : hors du dépôt, jamais dans la base, jamais dans les journaux.

Fichier `coffre.json` à côté de la configuration locale (`%APPDATA%\\JARVIS2\\` ou `~/.config/jarvis2/`).
- Windows : chaque valeur est chiffrée par DPAPI (CryptProtectData) — lisible seulement par cette session Windows ;
- ailleurs : fichier en droits 0600 (lecture par l'utilisateur seul) ; un trousseau du système viendra plus tard.
L'interface ne reçoit jamais une clé : seulement « enregistrée » ou non, et ses 4 derniers caractères.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(donnees: bytes, chiffrer: bool) -> bytes:
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined, unused-ignore]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined, unused-ignore]
    tampon = ctypes.create_string_buffer(donnees, len(donnees))
    entree = _Blob(len(donnees), ctypes.cast(tampon, ctypes.POINTER(ctypes.c_char)))
    sortie = _Blob()
    fonction = crypt32.CryptProtectData if chiffrer else crypt32.CryptUnprotectData
    ok = fonction(ctypes.byref(entree), None, None, None, None, 0x1, ctypes.byref(sortie))  # 0x1 : pas d'IHM
    if not ok:
        raise OSError("DPAPI : opération refusée")
    try:
        return ctypes.string_at(sortie.pbData, sortie.cbData)
    finally:
        kernel32.LocalFree(sortie.pbData)


class Coffre:
    def __init__(self, chemin: Path, chiffrement: bool | None = None) -> None:
        self.chemin = chemin
        self.chiffrement = (sys.platform == "win32") if chiffrement is None else chiffrement
        self._verrou = threading.Lock()

    def _lire(self) -> dict[str, str]:
        try:
            donnees: Any = json.loads(self.chemin.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        return {str(k): str(v) for k, v in donnees.items()} if isinstance(donnees, dict) else {}

    def _ecrire(self, donnees: dict[str, str]) -> None:
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        temporaire = self.chemin.with_suffix(".tmp")
        temporaire.write_text(json.dumps(donnees, indent=1), encoding="utf-8")
        if sys.platform != "win32":
            os.chmod(temporaire, 0o600)
        temporaire.replace(self.chemin)

    def _emballer(self, valeur: str) -> str:
        brut = valeur.encode("utf-8")
        if self.chiffrement:
            return "dpapi:" + base64.b64encode(_dpapi(brut, True)).decode()
        return "clair:" + base64.b64encode(brut).decode()

    def _deballer(self, emballe: str) -> str:
        sorte, _, charge = emballe.partition(":")
        brut = base64.b64decode(charge)
        return (_dpapi(brut, False) if sorte == "dpapi" else brut).decode("utf-8")

    def definir(self, nom: str, valeur: str) -> None:
        valeur = valeur.strip()
        if not valeur:
            raise ValueError("Clé vide")
        with self._verrou:
            donnees = self._lire()
            donnees[nom] = self._emballer(valeur)
            self._ecrire(donnees)

    def lire(self, nom: str) -> str | None:
        with self._verrou:
            emballe = self._lire().get(nom)
        if emballe is None:
            return None
        try:
            return self._deballer(emballe)
        except (OSError, ValueError):
            return None  # coffre créé par une autre session Windows : clé à ressaisir

    def supprimer(self, nom: str) -> bool:
        with self._verrou:
            donnees = self._lire()
            present = donnees.pop(nom, None) is not None
            if present:
                self._ecrire(donnees)
        return present

    def apercu(self, nom: str) -> str | None:
        """« ••••abcd » : de quoi reconnaître une clé sans jamais la montrer."""
        valeur = self.lire(nom)
        return f"••••{valeur[-4:]}" if valeur and len(valeur) >= 12 else ("••••" if valeur else None)

    def fournisseur(self, nom: str) -> Any:
        """Fonction sans argument qui lit la clé au moment de l'appel (passée aux connecteurs)."""
        return lambda: self.lire(nom)
