"""Faux PC pour les tests du lot J : rien n'est jamais réglé sur la vraie machine.

- `FauxPilote` : volume, luminosité, fenêtres, média, verrouillage, extinction, plan, notifications, thème en
  mémoire ; `ignore` fait « oublier » un réglage (la relecture ne concorde pas → « non vérifiée »).
- `FauxOllama` : faux serveur (transport httpx) démarré par `FauxLanceur`, sans aucun processus.
- `FauxDetecteur` / `FauxMesureur` : premier plan et mesures fixés par le test.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from jarvis2.pc.jeu import Premier
from jarvis2.pc.pilote import ActionFenetre, CommandeMedia, ErreurPilote, Fenetre, Media, Volume
from jarvis2.pc.ressources import Echantillon

PERF = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
EQUILIBRE = "381b4222-f694-41f0-9685-ff5bb260df2e"


@dataclass
class FauxPilote:
    nom: str = "faux"
    volume: int = 50
    muet: bool = False
    luminosite: int | None = 70  # None : écran sans réglage de luminosité
    fenetres_ouvertes: list[Fenetre] = field(
        default_factory=lambda: [
            Fenetre(101, "Bloc-notes", "notepad.exe", active=True),
            Fenetre(202, "Lecteur", "lecteur.exe"),
        ]
    )
    lecture: Media = field(default_factory=lambda: Media("lecteur", "Morceau 1", "Artiste", "lecture"))
    est_verrouille: bool = False
    plan: str = EQUILIBRE
    plans: dict[str, str] = field(default_factory=lambda: {EQUILIBRE: "Utilisation normale", PERF: "Performances"})
    notifications: bool = True
    sombre: bool = False
    extinction: int | None = None
    ignore: set[str] = field(default_factory=set)  # réglages qui « ne prennent pas »
    appels: list[str] = field(default_factory=list)

    def _noter(self, quoi: str) -> bool:
        self.appels.append(quoi)
        return quoi.split(":")[0] not in self.ignore

    def lire_volume(self) -> Volume | None:
        return Volume(self.volume, self.muet)

    def lire_luminosite(self) -> int | None:
        return self.luminosite

    def fenetres(self) -> list[Fenetre]:
        return list(self.fenetres_ouvertes)

    def media(self) -> Media | None:
        return self.lecture

    def verrouille(self) -> bool | None:
        return self.est_verrouille

    def lire_plan_alimentation(self) -> str | None:
        return self.plan

    def plans_alimentation(self) -> dict[str, str]:
        return dict(self.plans)

    def lire_notifications(self) -> bool | None:
        return self.notifications

    def lire_theme_sombre(self) -> bool | None:
        return self.sombre

    def regler_volume(self, niveau: int) -> None:
        if self._noter(f"volume:{niveau}"):
            self.volume = niveau

    def regler_muet(self, muet: bool) -> None:
        if self._noter(f"muet:{muet}"):
            self.muet = muet

    def regler_luminosite(self, niveau: int) -> None:
        if self.luminosite is None:
            raise ErreurPilote("Luminosité non réglable sur cet écran")
        if self._noter(f"luminosite:{niveau}"):
            self.luminosite = niveau

    def agir_fenetre(self, ident: int, action: ActionFenetre) -> None:
        self._noter(f"fenetre:{action}:{ident}")
        if not any(f.id == ident for f in self.fenetres_ouvertes):
            raise ErreurPilote("Cette fenêtre n'existe plus")
        if "fenetre" in self.ignore:
            return
        if action == "fermer":
            self.fenetres_ouvertes = [f for f in self.fenetres_ouvertes if f.id != ident]
            return
        nouvelles = []
        for f in self.fenetres_ouvertes:
            if action == "activer":
                f = Fenetre(f.id, f.titre, f.programme, f.id == ident, False if f.id == ident else f.reduite)
            elif f.id == ident:
                f = Fenetre(f.id, f.titre, f.programme, f.active, action == "minimiser")
            nouvelles.append(f)
        self.fenetres_ouvertes = nouvelles

    def commande_media(self, commande: CommandeMedia) -> None:
        if not self._noter(f"media:{commande}"):
            return
        m = self.lecture
        if commande in ("lecture", "pause"):
            self.lecture = Media(m.application, m.titre, m.artiste, commande)
        elif commande == "bascule":
            self.lecture = Media(m.application, m.titre, m.artiste, "pause" if m.statut == "lecture" else "lecture")
        else:
            self.lecture = Media(m.application, "Morceau 2", m.artiste, m.statut)

    def verrouiller(self) -> None:
        if self._noter("verrouiller"):
            self.est_verrouille = True

    def planifier_extinction(self, delai_s: int, message: str) -> None:
        self._noter(f"extinction:{delai_s}")
        self.extinction = delai_s

    def annuler_extinction(self) -> bool:
        self._noter("annulation")
        prevue, self.extinction = self.extinction is not None, None
        return prevue

    def regler_plan_alimentation(self, ident: str) -> None:
        if self._noter(f"plan:{ident}"):
            self.plan = ident

    def regler_notifications(self, actives: bool) -> None:
        if self._noter(f"notifications:{actives}"):
            self.notifications = actives

    def regler_theme_sombre(self, sombre: bool) -> None:
        if self._noter(f"theme:{sombre}"):
            self.sombre = sombre


@dataclass
class FauxProcessus:
    pid: int = 4242
    code: int | None = None

    def poll(self) -> int | None:
        return self.code


@dataclass
class FauxOllama:
    """Faux serveur Ollama : répond seulement quand `actif` (démarré par le faux lanceur ou « par l'utilisateur »)."""

    actif: bool = False
    charges: list[str] = field(default_factory=list)
    requetes: list[str] = field(default_factory=list)

    def transport(self) -> httpx.MockTransport:
        def repondre(requete: httpx.Request) -> httpx.Response:
            self.requetes.append(f"{requete.method} {requete.url.path}")
            if not self.actif:
                raise httpx.ConnectError("refusé", request=requete)
            if requete.url.path == "/api/version":
                return httpx.Response(200, json={"version": "0.0-faux"})
            if requete.url.path == "/api/ps":
                return httpx.Response(
                    200, json={"models": [{"name": n, "size": 2 * 1024**3, "size_vram": 1024**3} for n in self.charges]}
                )
            if requete.url.path == "/api/generate":
                corps = json.loads(requete.content)
                if corps.get("keep_alive") == 0 and corps["model"] in self.charges:
                    self.charges.remove(corps["model"])
                return httpx.Response(200, json={"done": True})
            return httpx.Response(404)

        return httpx.MockTransport(repondre)


@dataclass
class FauxLanceur:
    serveur: FauxOllama
    installe: bool = True
    lances: list[str] = field(default_factory=list)
    arretes: int = 0
    processus: FauxProcessus | None = None

    def trouver(self) -> str | None:
        return "ollama-faux" if self.installe else None

    def lancer(self, executable: str, hote: str, journal_fichier: Path | None) -> FauxProcessus:
        self.lances.append(hote)
        self.serveur.actif = True
        self.processus = FauxProcessus()
        return self.processus

    def arreter(self, processus: Any) -> None:
        self.arretes += 1
        processus.code = 0
        self.serveur.actif, self.serveur.charges = False, []


@dataclass
class FauxDetecteur:
    premier: Premier | None = None

    def premier_plan(self) -> Premier | None:
        return self.premier


@dataclass
class FauxMesureur:
    cpu: float = 12.5
    gpu: float | None = 85.0

    def mesurer(self) -> Echantillon:
        return Echantillon(time.time(), self.cpu, 8.0, 32.0, self.gpu, 20.0, 24.0)
