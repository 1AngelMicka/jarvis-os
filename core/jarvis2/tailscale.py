"""Tailscale (accès du téléphone hors du PC) : lecture seule de l'état, jamais de modification.

JARVIS n'écoute que sur 127.0.0.1 ; `tailscale serve` (lancé par l'utilisateur) publie le Core en HTTPS sur son
réseau privé Tailscale, sans ouvrir de port : https://<nom-du-pc>.<réseau>.ts.net. JARVIS détecte cette adresse pour
le QR de jumelage et l'ajoute aux origines autorisées.
"""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .moteurs.sousprocessus import environnement, executer_court

INSTALLATION_URL = "https://tailscale.com/download"


@dataclass(frozen=True)
class EtatTailscale:
    installe: bool = False
    connecte: bool = False
    nom: str | None = None  # nom DNS complet du PC sur le réseau Tailscale (sans point final)
    serve_actif: bool = False  # `tailscale serve` publie déjà le Core

    @property
    def adresse(self) -> str | None:
        return f"https://{self.nom}" if self.nom else None

    def commande_serve(self, port: int) -> str:
        return f"tailscale serve --bg {port}"

    def en_dict(self, port: int) -> dict[str, Any]:
        return {
            **asdict(self),
            "adresse": self.adresse,
            "commande": self.commande_serve(port),
            "aide": INSTALLATION_URL,
        }


def binaire() -> str | None:
    trouve = shutil.which("tailscale")
    if trouve:
        return trouve
    if sys.platform == "win32":
        defaut = Path(r"C:\Program Files\Tailscale\tailscale.exe")
        return str(defaut) if defaut.is_file() else None
    if sys.platform == "darwin":
        app = Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")
        return str(app) if app.is_file() else None
    return None


def _json(sortie: str) -> Any:
    debut = sortie.find("{")
    try:
        return json.loads(sortie[debut:]) if debut >= 0 else None
    except json.JSONDecodeError:
        return None


async def lire_etat(port: int) -> EtatTailscale:
    commande = binaire()
    if commande is None:
        return EtatTailscale()
    env = environnement()
    try:
        code, sortie = await executer_court([commande, "status", "--json"], env, delai=6)
    except (OSError, TimeoutError):
        return EtatTailscale(installe=True)
    etat = _json(sortie) if code == 0 else None
    if not isinstance(etat, dict) or etat.get("BackendState") != "Running":
        return EtatTailscale(installe=True)
    nom = str((etat.get("Self") or {}).get("DNSName") or "").rstrip(".") or None
    serve = False
    try:
        code, sortie = await executer_court([commande, "serve", "status", "--json"], env, delai=6)
        serve = code == 0 and any(f"{h}:{port}" in sortie for h in ("127.0.0.1", "localhost"))
    except (OSError, TimeoutError):
        pass
    return EtatTailscale(installe=True, connecte=True, nom=nom, serve_actif=serve)
