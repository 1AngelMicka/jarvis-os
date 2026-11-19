"""Mise à jour du Core : dernière version publiée, indicateur des Réglages et commande `jarvis2 mettre-a-jour`.

- La dernière version vient de l'API PUBLIQUE de GitHub (`releases/latest`), sans jeton ni compte : seuls partent
  l'adresse IP et la demande elle-même (comme pour tout téléchargement). Aucune donnée personnelle.
- L'indicateur des Réglages vérifie **au plus une fois par jour** (date de la dernière vérification gardée en base,
  `etat_systeme`, clé `mises_a_jour`), seulement quand la vue le demande, et se désactive d'un clic.
- Rien n'est jamais installé sans accord : la commande montre la version et ses notes, puis demande « o/N ».
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import httpx

from . import __version__

if TYPE_CHECKING:
    from .db import Executant

journal = logging.getLogger(__name__)

DEPOT = "1AngelMicka/jarvis-os"
URL_API = f"https://api.github.com/repos/{DEPOT}/releases/latest"
URL_VERSIONS = f"https://github.com/{DEPOT}/releases"
# Seules adresses acceptées venant de la réponse : la page d'une version et ses fichiers joints, sur ce dépôt
_PREFIXE_PAGE = f"{URL_VERSIONS}/"
_PREFIXE_FICHIER = f"{URL_VERSIONS}/download/"
_URL_SURE = re.compile(r"^[A-Za-z0-9._~:/%+-]+$")  # ni espace, ni guillemet, ni caractère de commande
DELAI = httpx.Timeout(6.0, connect=4.0)
ENTETES = {"User-Agent": "jarvis2", "Accept": "application/vnd.github+json"}
INTERVALLE = timedelta(days=1)
NOTES_MAX = 4000  # notes renvoyées à l'interface (texte brut)
NOTES_CONSOLE = 1500  # notes affichées par la commande
COMMANDE = "jarvis2 mettre-a-jour"
CLE_ETAT = "mises_a_jour"

Methode = Literal["uv", "pipx", "developpement", "inconnue"]


class ErreurVersions(Exception):
    """Dernière version illisible : hors ligne, limite de débit de GitHub, réponse inattendue."""


# --- Numéros de version --------------------------------------------------------------------------------------------

_VERSION = re.compile(r"^\s*[vV]?(\d+(?:\.\d+)*)(?:[-.]?([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]*)?\s*$")


def analyser_version(texte: str | None) -> tuple[tuple[int, ...], tuple[int, str]] | None:
    """`v0.9.0` → ((0, 9, 0), (1, "")) ; `1.0.0-rc.1` → ((1, 0, 0), (0, "rc.1")). Une préversion passe avant la
    version finale ; les zéros de fin ne comptent pas (`1.0` == `1.0.0`). None si ce n'est pas un numéro."""
    if not texte:
        return None
    m = _VERSION.match(texte)
    if not m:
        return None
    nombres = [int(n) for n in m.group(1).split(".")]
    while len(nombres) > 1 and nombres[-1] == 0:
        nombres.pop()
    suffixe = (m.group(2) or "").strip(".-")  # métadonnées de construction (+…) ignorées par l'expression
    return tuple(nombres), (0, suffixe.lower()) if suffixe else (1, "")


def normaliser_version(texte: str | None) -> str | None:
    """Numéro affiché : `v0.9.0` → `0.9.0` (None si illisible)."""
    if analyser_version(texte) is None or texte is None:
        return None
    return texte.strip().lstrip("vV")


def plus_recente(candidate: str | None, installee: str = __version__) -> bool:
    """La version `candidate` est-elle strictement plus récente que celle installée ? Faux si l'une est illisible."""
    a, b = analyser_version(candidate), analyser_version(installee)
    return a is not None and b is not None and a > b


def tronquer(texte: str, limite: int) -> str:
    """Coupe proprement : à la dernière fin de ligne (ou d'espace) avant la limite, suivie de « … »."""
    texte = texte.replace("\r\n", "\n").strip()
    if len(texte) <= limite:
        return texte
    coupe = texte[:limite]
    fin = max(coupe.rfind("\n"), coupe.rfind(" "))
    return (coupe[:fin] if fin > limite // 2 else coupe).rstrip() + " …"


# --- Dernière version publiée ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Publication:
    version: str
    notes: str
    url: str
    publiee_le: str | None
    roue: str | None  # roue (.whl) jointe à la version : ce que les installeurs installent

    def en_dict(self) -> dict[str, Any]:
        return {"version": self.version, "notes": self.notes, "url": self.url, "publiee_le": self.publiee_le}

    @classmethod
    def depuis_dict(cls, d: Any) -> Publication | None:
        if not isinstance(d, dict) or not isinstance(d.get("version"), str):
            return None
        notes, url = str(d.get("notes") or ""), str(d.get("url") or URL_VERSIONS)
        return cls(d["version"], notes, url, d.get("publiee_le"), None)


def _url_sure(url: Any, prefixe: str) -> str | None:
    if isinstance(url, str) and url.startswith(prefixe) and _URL_SURE.match(url):
        return url
    return None


def lire_publication(corps: Any) -> Publication:
    """Réponse de `releases/latest` → Publication (adresses vérifiées : rien d'autre que ce dépôt)."""
    if not isinstance(corps, dict):
        raise ErreurVersions("réponse inattendue de GitHub")
    version = normaliser_version(corps.get("tag_name")) or normaliser_version(corps.get("name"))
    if version is None:
        raise ErreurVersions("la dernière version publiée n'a pas de numéro lisible")
    roues = [
        u
        for a in corps.get("assets") or []
        if isinstance(a, dict) and str(a.get("name", "")).endswith(".whl")
        for u in [_url_sure(a.get("browser_download_url"), _PREFIXE_FICHIER)]
        if u
    ]
    publiee = corps.get("published_at")
    return Publication(
        version=version,
        notes=str(corps.get("body") or ""),
        url=_url_sure(corps.get("html_url"), _PREFIXE_PAGE) or URL_VERSIONS,
        publiee_le=publiee if isinstance(publiee, str) else None,
        roue=roues[0] if roues else None,
    )


async def derniere_publication(transport: httpx.AsyncBaseTransport | None = None) -> Publication:
    """Interroge l'API publique de GitHub (sans jeton). Lève ErreurVersions avec une raison lisible."""
    try:
        async with httpx.AsyncClient(timeout=DELAI, headers=ENTETES, transport=transport) as client:
            rep = await client.get(URL_API)
    except httpx.TimeoutException as exc:
        raise ErreurVersions("GitHub ne répond pas (délai dépassé) : réessayez plus tard") from exc
    except httpx.HTTPError as exc:
        raise ErreurVersions("GitHub injoignable : pas de connexion à Internet ?") from exc
    if rep.status_code == 429 or (rep.status_code == 403 and rep.headers.get("x-ratelimit-remaining") == "0"):
        raise ErreurVersions("limite de débit de l'API GitHub atteinte : réessayez dans une heure")
    if rep.status_code == 404:
        raise ErreurVersions("aucune version publiée pour l'instant")
    if rep.status_code != 200:
        raise ErreurVersions(f"réponse inattendue de GitHub (code {rep.status_code})")
    try:
        corps = rep.json()
    except ValueError as exc:
        raise ErreurVersions("réponse illisible de GitHub") from exc
    return lire_publication(corps)


# --- Indicateur des Réglages : au plus une vérification par jour, désactivable -------------------------------------


def _date(texte: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(texte) if isinstance(texte, str) else None
    except ValueError:
        return None


class ServiceMisesAJour:
    """Dernière version connue, gardée en base avec la date de vérification : un redémarrage ne relance pas l'appel."""

    def __init__(
        self,
        base: Executant,
        transport: httpx.AsyncBaseTransport | None = None,
        horloge: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.base = base
        self.transport = transport
        self.horloge = horloge
        self._verrou = asyncio.Lock()

    async def _lire(self) -> dict[str, Any]:
        valeur = await self.base.fetchval("SELECT valeur FROM etat_systeme WHERE cle = $1", CLE_ETAT)
        etat = valeur if isinstance(valeur, dict) else json.loads(valeur or "{}")
        etat.setdefault("verifier", True)
        return etat

    async def _ecrire(self, etat: dict[str, Any]) -> None:
        # Ligne créée par la migration 033 (le rôle applicatif ne peut que la mettre à jour)
        await self.base.execute(
            "UPDATE etat_systeme SET valeur = $1::text::jsonb, maj_le = now() WHERE cle = $2",
            json.dumps(etat, ensure_ascii=False),
            CLE_ETAT,
        )

    async def actif(self) -> bool:
        return bool((await self._lire())["verifier"])

    async def regler(self, verifier: bool) -> dict[str, Any]:
        etat = await self._lire()
        etat["verifier"] = verifier
        await self._ecrire(etat)
        return await self.decrire(verifier_si_besoin=verifier)  # réactivée : vérifie tout de suite si besoin

    def _perime(self, etat: dict[str, Any]) -> bool:
        derniere = _date(etat.get("verifie_le"))
        return derniere is None or self.horloge() - derniere >= INTERVALLE

    async def decrire(self, verifier_si_besoin: bool = True) -> dict[str, Any]:
        """État pour les Réglages. Interroge GitHub seulement si la vérification est active et date d'un jour ou plus
        (succès comme échec : un échec n'est pas réessayé avant le lendemain)."""
        etat = await self._lire()
        if verifier_si_besoin and etat["verifier"] and self._perime(etat):
            async with self._verrou:
                etat = await self._lire()  # une autre demande a peut-être vérifié pendant l'attente
                if etat["verifier"] and self._perime(etat):
                    etat["verifie_le"] = self.horloge().isoformat(timespec="seconds")
                    try:
                        trouvee = await derniere_publication(self.transport)
                        etat["derniere"], etat["erreur"] = trouvee.en_dict(), None
                    except ErreurVersions as exc:
                        journal.info("Vérification des nouvelles versions impossible : %s", exc)
                        etat["erreur"] = str(exc)
                    await self._ecrire(etat)
        actif = bool(etat["verifier"])
        pub = Publication.depuis_dict(etat.get("derniere")) if actif else None
        return {
            "active": actif,
            "installee": __version__,
            "derniere": pub.version if pub else None,
            "nouvelle": bool(pub and plus_recente(pub.version)),
            "notes": tronquer(pub.notes, NOTES_MAX) if pub else None,
            "url": pub.url if pub else None,
            "publiee_le": pub.publiee_le if pub else None,
            "verifie_le": etat.get("verifie_le") if actif else None,
            "erreur": etat.get("erreur") if actif else None,
            "commande": COMMANDE,
        }


# --- Commande `jarvis2 mettre-a-jour` -------------------------------------------------------------------------------


def detecter_methode(prefixe: str | Path | None = None, paquet: Path | None = None) -> Methode:
    """Comment ce Core a été installé, d'après l'environnement Python qui l'exécute (prudemment : en cas de doute,
    « inconnue », et la commande explique au lieu d'agir).

    - uv tool : l'environnement contient `uv-receipt.toml` (ou se trouve sous `…/uv/tools/`) ;
    - pipx    : `pipx_metadata.json` (ou `…/pipx/venvs/`) ;
    - dépôt   : le paquet est lu directement depuis `core/` (installation de développement, `uv sync`)."""
    env = Path(prefixe if prefixe is not None else sys.prefix)
    chemin = str(env).replace("\\", "/").lower().rstrip("/") + "/"
    paquet = paquet if paquet is not None else Path(__file__).resolve().parent
    if (paquet.parent / "pyproject.toml").is_file():
        return "developpement"
    if (env / "uv-receipt.toml").is_file() or "/uv/tools/" in chemin:
        return "uv"
    if (env / "pipx_metadata.json").is_file() or "/pipx/venvs/" in chemin:
        return "pipx"
    return "inconnue"


def commande_maj(methode: Methode, roue: str) -> list[str] | None:
    """Commande qui installe la roue de la nouvelle version, selon la méthode d'installation.

    Pourquoi pas `uv tool upgrade jarvis2` / `pipx upgrade jarvis2` : les installeurs (install.ps1, install.sh) et le
    README installent la roue jointe à une version GitHub, par son adresse. Cette adresse désigne UNE version : une
    « mise à niveau » relirait la même roue et ne changerait rien. On réinstalle donc, à la place, la roue de la
    nouvelle version (`--force` : remplace l'installation existante ; données et configuration ne sont pas touchées)."""
    if methode == "uv":
        return ["uv", "tool", "install", "--force", "--python", "3.13", roue]
    if methode == "pipx":
        return ["pipx", "install", "--force", "--python", "3.13", roue]
    return None


def _executer(commande: list[str]) -> int:
    """Lance la commande de mise à jour (sans shell, arguments en liste).

    Sous Windows, le programme `jarvis2` en cours d'exécution et son Python sont verrouillés : les remplacer
    maintenant échouerait. La commande est donc lancée dans une nouvelle fenêtre qui attend la fin de celle-ci."""
    if os.name != "nt":
        return subprocess.run(commande, check=False).returncode
    arguments = " ".join("'" + a.replace("'", "''") + "'" for a in commande[1:])
    script = (
        f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2; "
        f"& '{commande[0]}' {arguments}; "
        "Write-Host ''; Read-Host 'Mise à jour terminée. Entrée pour fermer cette fenêtre'"
    )
    # Pas de shell : PowerShell reçoit le script en argument ; l'adresse de la roue a été vérifiée (lire_publication)
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )
    print("La mise à jour se poursuit dans une nouvelle fenêtre, dès que cette commande est terminée.")
    return 0


def mettre_a_jour(
    oui: bool = False,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    demander: Callable[[str], str] = input,
    executer: Callable[[list[str]], int] = _executer,
    methode: Methode | None = None,
    trouver: Callable[[str], str | None] = shutil.which,
) -> int:
    """`jarvis2 mettre-a-jour` : 0 à jour, refusé ou mis à jour ; 1 vérification impossible ; 3 échec de la mise à
    jour. Rien n'est lancé sans « o » (ou `--oui`)."""
    print(f"Version installée : {__version__}")
    try:
        pub = asyncio.run(derniere_publication(transport))
    except ErreurVersions as exc:
        print(f"Impossible de vérifier la dernière version : {exc}.")
        print(f"Versions publiées : {URL_VERSIONS}")
        return 1
    if not plus_recente(pub.version):
        print(f"JARVIS 2 est à jour (dernière version publiée : {pub.version}).")
        return 0
    publiee = f" (publiée le {pub.publiee_le[:10]})" if pub.publiee_le else ""
    print(f"Nouvelle version disponible : {pub.version}{publiee}")
    if pub.notes.strip():
        print("\nNotes de version :")
        for ligne in tronquer(pub.notes, NOTES_CONSOLE).splitlines():
            print(f"  {ligne}")
    print(f"\nPage de la version : {pub.url}\n")

    methode = methode or detecter_methode()
    if methode == "developpement":
        print("Installation de développement (dépôt git) : rien n'est lancé. Pour mettre à jour :")
        print("  git pull ; cd core ; uv sync ; cd ../interface ; npm ci ; npm run build")
        return 0
    if pub.roue is None:
        print("Aucune roue (.whl) n'est jointe à cette version : téléchargez-la depuis la page ci-dessus.")
        return 0
    commande = commande_maj(methode, pub.roue)
    if commande is None:
        print("Méthode d'installation non reconnue : rien n'est lancé. Selon votre installation :")
        print(f"  uv tool install --force --python 3.13 {pub.roue}")
        print(f"  pipx install --force --python 3.13 {pub.roue}")
        return 0
    if trouver(commande[0]) is None:
        print(f"« {commande[0]} » est introuvable dans le PATH : lancez vous-même, une fois {commande[0]} installé :")
        print("  " + " ".join(commande))
        return 0
    print("Méthode d'installation : " + ("uv tool" if methode == "uv" else "pipx"))
    print("Commande : " + " ".join(commande))
    print("Arrêtez d'abord le Core s'il tourne (jarvis2 serveur, application de bureau) ; vos données restent.")
    if not oui:
        try:
            reponse = demander("Mettre à jour maintenant ? [o/N] ")
        except EOFError:  # pas de terminal interactif : jamais d'accord implicite
            reponse = ""
        if reponse.strip().lower() not in ("o", "oui", "y", "yes"):
            print("Rien n'a été modifié.")
            return 0
    code = executer(commande)
    if code != 0:
        print(f"La mise à jour a échoué (code {code}). Rien d'autre n'a été modifié.")
        return 3
    return 0
