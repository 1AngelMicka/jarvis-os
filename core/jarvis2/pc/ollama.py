"""Ollama À LA DEMANDE : démarré seulement quand l'utilisateur le demande, arrêté après inactivité.

Règles :
- JARVIS ne démarre JAMAIS Ollama de lui-même (ni au lancement, ni au réveil, ni pour une tâche automatique) :
  seule l'action `ollama.demarrer`, approuvée par l'utilisateur (🟡, jamais « toujours autorisée »), le lance.
- JARVIS n'arrête que l'Ollama qu'IL a démarré : un Ollama lancé par l'utilisateur (ou par un autre programme)
  n'est jamais tué ; on peut seulement en décharger les modèles.
- Arrêt après `inactivite` minutes sans modèle chargé, à l'entrée en mode jeu, et à l'arrêt du Core.
- « Décharger » libère la VRAM d'un modèle (`keep_alive: 0`), sans arrêter Ollama.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

journal = logging.getLogger("jarvis2.pc.ollama")

INACTIVITE_DEFAUT = 20  # minutes sans modèle chargé
ATTENTE_DEMARRAGE = 25.0  # secondes pour qu'Ollama réponde après le lancement
SANS_FENETRE = 0x08000000


class ErreurOllama(RuntimeError):
    pass


class Processus(Protocol):
    pid: int

    def poll(self) -> int | None: ...


class Lanceur(Protocol):
    """Lance et arrête le serveur Ollama (abstrait : les tests n'en lancent aucun)."""

    def trouver(self) -> str | None: ...
    def lancer(self, executable: str, hote: str, journal_fichier: Path | None) -> Processus: ...
    def arreter(self, processus: Processus) -> None: ...


def executable_ollama() -> str | None:
    trouve = shutil.which("ollama")
    if trouve:
        return trouve
    if sys.platform == "win32":
        candidat = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        if candidat.is_file():
            return str(candidat)
    return None


class LanceurSysteme:
    def trouver(self) -> str | None:
        return executable_ollama()

    def lancer(self, executable: str, hote: str, journal_fichier: Path | None) -> Processus:
        sortie: Any = subprocess.DEVNULL
        if journal_fichier is not None:
            journal_fichier.parent.mkdir(parents=True, exist_ok=True)
            sortie = journal_fichier.open("ab")
        try:
            return subprocess.Popen(
                [executable, "serve"],
                stdout=sortie,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env={**os.environ, "OLLAMA_HOST": hote},
                creationflags=SANS_FENETRE if sys.platform == "win32" else 0,
                start_new_session=sys.platform != "win32",
            )
        finally:
            if journal_fichier is not None:
                sortie.close()

    def arreter(self, processus: Processus) -> None:
        if processus.poll() is not None:
            return
        if sys.platform == "win32":  # l'arbre entier : `ollama serve` lance ses propres moteurs
            subprocess.run(
                ["taskkill", "/PID", str(processus.pid), "/T", "/F"],
                capture_output=True,
                creationflags=SANS_FENETRE,
                check=False,
                timeout=15,
            )
        else:
            os.killpg(processus.pid, 15)


@dataclass
class GestionnaireOllama:
    url: str = "http://127.0.0.1:11434"
    lanceur: Lanceur = field(default_factory=LanceurSysteme)
    inactivite: int = INACTIVITE_DEFAUT  # minutes
    journal_fichier: Path | None = None
    transport: httpx.AsyncBaseTransport | None = None
    attente_demarrage: float = ATTENTE_DEMARRAGE
    bloque: Callable[[], str | None] = lambda: None  # raison de refuser un démarrage (arrêt d'urgence…)
    processus: Processus | None = None  # l'Ollama que JARVIS a lancé (le seul qu'il arrête)
    depuis_inactif: float | None = None
    demarre_le: float | None = None

    def _client(self, delai: float = 3.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.url.rstrip("/"), timeout=delai, transport=self.transport)

    @property
    def lance_par_jarvis(self) -> bool:
        return self.processus is not None and self.processus.poll() is None

    async def joignable(self) -> bool:
        try:
            async with self._client(2.0) as c:
                return (await c.get("/api/version")).status_code == 200
        except httpx.HTTPError:
            return False

    async def charges(self) -> list[dict[str, Any]]:
        """Modèles chargés en mémoire (`/api/ps`), avec leur part en VRAM. Ne démarre rien."""
        try:
            async with self._client() as c:
                r = await c.get("/api/ps")
                r.raise_for_status()
                modeles = r.json().get("models") or []
        except (httpx.HTTPError, ValueError):
            return []
        return [
            {
                "nom": str(m.get("name") or m.get("model") or "?"),
                "taille_go": round(float(m.get("size") or 0) / 1024**3, 2),
                "vram_go": round(float(m.get("size_vram") or 0) / 1024**3, 2),
                "expire_le": m.get("expires_at"),
            }
            for m in modeles
        ]

    async def etat(self) -> dict[str, Any]:
        joignable = await self.joignable()
        return {
            "installe": self.lanceur.trouver() is not None,
            "joignable": joignable,
            "lance_par_jarvis": self.lance_par_jarvis,
            "modeles_charges": await self.charges() if joignable else [],
            "inactivite_min": self.inactivite,
            "arret_dans_s": self._arret_dans(),
        }

    def _arret_dans(self) -> int | None:
        if not self.lance_par_jarvis or self.depuis_inactif is None:
            return None
        return max(0, round(self.inactivite * 60 - (time.monotonic() - self.depuis_inactif)))

    async def demarrer(self) -> dict[str, Any]:
        """Uniquement depuis l'action approuvée `ollama.demarrer` (demande explicite de l'utilisateur)."""
        raison = self.bloque()
        if raison:
            raise ErreurOllama(raison)
        if await self.joignable():
            return {"deja_demarre": True, "lance_par_jarvis": self.lance_par_jarvis, "verifiee": True}
        executable = self.lanceur.trouver()
        if executable is None:
            raise ErreurOllama("Ollama n'est pas installé sur ce PC (https://ollama.com/download)")
        adresse = urlparse(self.url)
        hote = f"{adresse.hostname or '127.0.0.1'}:{adresse.port or 11434}"
        self.processus = await asyncio.to_thread(self.lanceur.lancer, executable, hote, self.journal_fichier)
        self.demarre_le, self.depuis_inactif = time.monotonic(), time.monotonic()
        journal.info("Ollama démarré à la demande de l'utilisateur (pid %s)", self.processus.pid)
        fin = time.monotonic() + self.attente_demarrage
        while time.monotonic() < fin:  # vérifié en relisant : Ollama répond-il ?
            if await self.joignable():
                return {"deja_demarre": False, "lance_par_jarvis": True, "verifiee": True}
            if self.processus.poll() is not None:
                self.processus = None
                raise ErreurOllama("Ollama s'est arrêté aussitôt après son lancement (voir son journal)")
            await asyncio.sleep(0.5)
        return {"deja_demarre": False, "lance_par_jarvis": True, "verifiee": False,
                "detail": "Ollama ne répond pas encore"}  # fmt: skip

    async def arreter(self, motif: str = "demande") -> dict[str, Any]:
        """Arrête l'Ollama lancé par JARVIS ; un Ollama démarré par l'utilisateur n'est jamais tué."""
        if not self.lance_par_jarvis or self.processus is None:
            if await self.joignable():
                raise ErreurOllama(
                    "Cet Ollama n'a pas été démarré par JARVIS : il n'est pas arrêté (déchargez ses modèles)"
                )
            self.processus = None
            return {"arrete": False, "verifiee": True, "detail": "Ollama n'était pas démarré"}
        await asyncio.to_thread(self.lanceur.arreter, self.processus)
        self.processus, self.depuis_inactif = None, None
        journal.info("Ollama arrêté (%s)", motif)
        for _ in range(10):  # relu : ne répond plus ?
            if not await self.joignable():
                return {"arrete": True, "verifiee": True, "motif": motif}
            await asyncio.sleep(0.3)
        return {"arrete": True, "verifiee": False, "motif": motif, "detail": "Ollama répond encore"}

    async def decharger(self, modele: str | None = None) -> dict[str, Any]:
        """Décharge un modèle (ou tous) de la mémoire. Ne démarre jamais Ollama."""
        if not await self.joignable():
            return {"decharges": [], "verifiee": True, "detail": "Ollama n'est pas démarré : rien à décharger"}
        cibles = [modele] if modele else [m["nom"] for m in await self.charges()]
        decharges = []
        async with self._client(30.0) as c:
            for nom in cibles:
                try:
                    r = await c.post("/api/generate", json={"model": nom, "keep_alive": 0})
                except httpx.HTTPError as exc:
                    raise ErreurOllama(f"Ollama injoignable : {exc}") from exc
                if r.status_code == 200:
                    decharges.append(nom)
        restants = {m["nom"] for m in await self.charges()}
        return {
            "decharges": decharges,
            "verifiee": not (set(cibles) & restants),
            **({"detail": f"encore chargé : {', '.join(sorted(set(cibles) & restants))}"} if set(cibles) & restants
               else {}),
        }  # fmt: skip

    async def surveiller(self) -> None:
        """Un passage de la boucle : arrêt après `inactivite` minutes sans modèle chargé (Ollama lancé par JARVIS)."""
        if self.processus is not None and self.processus.poll() is not None:
            self.processus, self.depuis_inactif = None, None  # arrêté par quelqu'un d'autre
        if not self.lance_par_jarvis:
            return
        if await self.charges():
            self.depuis_inactif = None
            return
        if self.depuis_inactif is None:
            self.depuis_inactif = time.monotonic()
        elif time.monotonic() - self.depuis_inactif >= self.inactivite * 60:
            await self.arreter(f"inactif depuis {self.inactivite} min")

    async def boucle(self, intervalle: float = 30.0) -> None:
        while True:
            try:
                await self.surveiller()
            except Exception:
                journal.exception("Surveillance d'Ollama en échec")
            await asyncio.sleep(intervalle)

    async def fermer(self) -> None:
        """Arrêt du Core : l'Ollama lancé par JARVIS s'arrête avec lui."""
        if self.lance_par_jarvis:
            await self.arreter("arrêt de JARVIS")
