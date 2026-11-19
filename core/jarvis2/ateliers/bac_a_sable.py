"""Bac à sable des ateliers Claude Code : ce qui AGIT tourne isolé, réseau coupé, seul le worktree monté.

Principe : Claude Code (le « cerveau », qui a besoin de l'abonnement de l'utilisateur) reste sur le PC, dans le
worktree de l'atelier. Ce qui agit passe par le bac à sable : chaque commande `Bash` accordée est RÉÉCRITE (dans
`updatedInput.command` de la réponse de l'outil d'autorisation) pour s'exécuter dans le bac à sable choisi, réseau
coupé, seul le worktree monté. En mode bac à sable, `WebFetch` et `WebSearch` sont refusés (réseau coupé). Les
écritures de Claude Code lui-même (Edit, Write…) sont déjà confinées au worktree par `autorisation.decider`.
Si au moment d'une commande le bac à sable n'est plus disponible, la commande est refusée avec la raison : elle
n'est JAMAIS exécutée hors du bac à sable.

Bacs reconnus : Docker et Podman (toutes plateformes, moteur DÉJÀ en marche et image déjà présente : JARVIS ne
démarre aucun service et ne télécharge rien, `--pull never`), Windows Sandbox (Windows, fonctionnalité déjà
activée), Bubblewrap (Linux), sandbox-exec (macOS). Choix d'un atelier : « auto » (premier disponible), un type
précis (jamais de repli sur un autre), ou « aucun » (sans bac à sable, choix explicite de l'utilisateur).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import shlex
import shutil
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePath
from typing import Protocol
from xml.sax.saxutils import escape

TYPES: tuple[str, ...] = ("docker", "podman", "windows_sandbox", "bubblewrap", "sandbox_exec")
CHOIX: tuple[str, ...] = ("auto", *TYPES, "aucun")
NOMS = {
    "docker": "Docker",
    "podman": "Podman",
    "windows_sandbox": "Windows Sandbox",
    "bubblewrap": "Bubblewrap",
    "sandbox_exec": "sandbox-exec (macOS)",
}
PLATEFORMES = {
    "windows_sandbox": ("win32", "Windows"),
    "bubblewrap": ("linux", "Linux"),
    "sandbox_exec": ("darwin", "macOS"),
}
IMAGE_DEFAUT = "python:3.13-slim"
DUREE_CACHE = 30.0  # secondes
DELAI_SONDE = 5.0  # chaque sonde (docker info, image inspect) : 5 s au plus
DELAI_WSB = 600.0  # une commande dans Windows Sandbox : 10 minutes au plus
COMMANDE_MAX = 8000  # caractères (ligne de commande de Windows Sandbox)
DOSSIER_SORTIE_WSB = ".jarvis-bac"  # dans le worktree : sortie et code de retour d'une commande Windows Sandbox


class RefusBacASable(RuntimeError):
    """Aucun bac à sable utilisable pour ce choix : l'atelier ne se lance pas (aucun repli silencieux)."""


@dataclass(frozen=True)
class Bac:
    id: str
    nom: str
    disponible: bool
    raison: str

    def en_dict(self) -> dict[str, object]:
        return asdict(self)


class Lanceur(Protocol):
    """Accès au système, injectable (les tests passent un faux lanceur : aucune exécution réelle)."""

    def which(self, nom: str) -> str | None: ...

    def existe(self, chemin: Path) -> bool: ...

    async def executer(self, args: Sequence[str], delai: float) -> tuple[int, str]: ...


class LanceurReel:
    """`shutil.which` et sous-processus courts ; ne démarre jamais un service (sondes en lecture seule)."""

    def which(self, nom: str) -> str | None:
        return shutil.which(nom)

    def existe(self, chemin: Path) -> bool:
        return chemin.exists()

    async def executer(self, args: Sequence[str], delai: float = DELAI_SONDE) -> tuple[int, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            return 127, str(exc)
        try:
            sortie, _ = await asyncio.wait_for(proc.communicate(), timeout=delai)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return 124, f"délai dépassé ({delai:g} s)"
        return proc.returncode or 0, sortie.decode("utf-8", "replace").strip()


class Detecteur:
    """Quels bacs à sable sont utilisables sur ce PC, maintenant (résultat gardé 30 s)."""

    def __init__(
        self,
        lanceur: Lanceur | None = None,
        plateforme: str = sys.platform,
        image: str = IMAGE_DEFAUT,
        racine_systeme: str | None = None,
    ) -> None:
        self.lanceur: Lanceur = lanceur or LanceurReel()
        self.plateforme = plateforme
        self.image = image
        self.racine_systeme = racine_systeme or os.environ.get("SYSTEMROOT") or r"C:\Windows"
        self._cache: tuple[float, list[Bac]] | None = None
        self._verrou = asyncio.Lock()

    async def detecter(self, rafraichir: bool = False) -> list[Bac]:
        async with self._verrou:
            if not rafraichir and self._cache is not None and time.monotonic() - self._cache[0] < DUREE_CACHE:
                return list(self._cache[1])
            bacs = [await self._un(t) for t in TYPES]
            self._cache = (time.monotonic(), bacs)
            return list(bacs)

    async def _un(self, ident: str) -> Bac:
        nom = NOMS[ident]
        if ident in PLATEFORMES:
            plateforme, libelle = PLATEFORMES[ident]
            if self.plateforme != plateforme:
                return Bac(ident, nom, False, f"réservé à {libelle}")
        if ident in ("docker", "podman"):
            return await self._moteur(ident, nom)
        if ident == "windows_sandbox":
            exe = self.exe_windows_sandbox()
            if not self.lanceur.existe(exe):
                return Bac(ident, nom, False, "fonctionnalité Windows Sandbox non activée (JARVIS ne l'active pas)")
            return Bac(ident, nom, True, "Windows Sandbox activé")
        cli = "bwrap" if ident == "bubblewrap" else "sandbox-exec"
        if self.lanceur.which(cli) is None:
            return Bac(ident, nom, False, f"`{cli}` introuvable (JARVIS n'installe rien)")
        return Bac(ident, nom, True, f"`{cli}` présent")

    async def _moteur(self, cli: str, nom: str) -> Bac:
        if self.lanceur.which(cli) is None:
            return Bac(cli, nom, False, f"{nom} non installé (`{cli}` introuvable)")
        code, _ = await self.lanceur.executer([cli, "info", "--format", "{{.ServerVersion}}"], DELAI_SONDE)
        if code != 0:
            return Bac(cli, nom, False, f"{nom} est arrêté : JARVIS ne le démarre jamais")
        code, _ = await self.lanceur.executer([cli, "image", "inspect", self.image], DELAI_SONDE)
        if code != 0:
            return Bac(cli, nom, False, f"image {self.image} absente : `{cli} pull {self.image}` à faire vous-même")
        return Bac(cli, nom, True, f"{nom} en marche, image {self.image} présente")

    def exe_windows_sandbox(self) -> Path:
        return Path(self.racine_systeme) / "System32" / "WindowsSandbox.exe"

    async def bac(self, ident: str) -> Bac | None:
        """État actuel (cache) d'un type de bac."""
        return next((b for b in await self.detecter() if b.id == ident), None)


def valider_choix(choix: str) -> str:
    if choix not in CHOIX:
        raise ValueError(f"Bac à sable inconnu : « {str(choix)[:40]} » (attendu : {', '.join(CHOIX)})")
    return choix


def choisir(choix: str, bacs: Sequence[Bac]) -> Bac | None:
    """Bac à utiliser pour ce choix ; None = sans bac à sable (choix « aucun », explicite). Jamais de repli."""
    valider_choix(choix)
    if choix == "aucun":
        return None
    par_id = {b.id: b for b in bacs}
    if choix == "auto":
        for t in TYPES:
            if t in par_id and par_id[t].disponible:
                return par_id[t]
        details = " ; ".join(f"{b.nom} : {b.raison}" for b in bacs) or "aucun bac détecté"
        raise RefusBacASable(
            f"Aucun bac à sable disponible ({details}). Aucun repli silencieux ; choisissez “sans bac à sable”"
            " explicitement si vous l'acceptez."
        )
    bac = par_id.get(choix)
    if bac is None or not bac.disponible:
        raison = bac.raison if bac is not None else "non détecté"
        raise RefusBacASable(
            f"{NOMS[choix]} indisponible : {raison}. Aucun repli silencieux sur un autre bac ; choisissez-en un"
            " autre, ou “sans bac à sable” explicitement si vous l'acceptez."
        )
    return bac


# --- Enveloppes ---------------------------------------------------------------------------------------------------


def _chaine_sbpl(texte: str) -> str:
    return '"' + texte.replace("\\", "\\\\").replace('"', '\\"') + '"'


def profil_sandbox_exec(worktree: PurePath) -> str:
    """Profil sandbox-exec : réseau coupé, écriture seulement dans le worktree (et /dev/null)."""
    wt = _chaine_sbpl(str(worktree))
    return (
        "(version 1)(allow default)(deny network*)"
        f'(deny file-write* (require-all (require-not (subpath {wt})) (require-not (literal "/dev/null"))))'
    )


def script_wsb(commande: str, ident: str) -> str:
    """Script PowerShell lancé au démarrage de Windows Sandbox. La commande n'y figure qu'en base64 : aucune
    injection possible (ni XML, ni PowerShell) ; elle est écrite dans un .cmd PRIVÉ au bac (hors dossier partagé)."""
    code64 = base64.b64encode(commande.encode("utf-8")).decode("ascii")
    sortie = rf"C:\atelier\{DOSSIER_SORTIE_WSB}\{ident}"
    return "\n".join(
        [
            "$ErrorActionPreference = 'Continue'",
            rf"New-Item -ItemType Directory -Force 'C:\atelier\{DOSSIER_SORTIE_WSB}' | Out-Null",
            f"$c = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{code64}'))",
            "$f = Join-Path $env:TEMP 'jarvis-commande.cmd'",
            'Set-Content -LiteralPath $f -Encoding OEM -Value ("@echo off`r`n" + $c)',
            "$code = 1",
            "try {",
            "  $p = Start-Process -FilePath cmd.exe -ArgumentList '/d', '/c', $f -WorkingDirectory 'C:\\atelier'"
            f" -RedirectStandardOutput '{sortie}.sortie' -RedirectStandardError '{sortie}.erreurs'"
            " -NoNewWindow -Wait -PassThru",
            "  $code = $p.ExitCode",
            f"}} catch {{ $_ | Out-File -Append -LiteralPath '{sortie}.erreurs' }}",
            f"Set-Content -LiteralPath '{sortie}.code' -Value $code",
            "shutdown /s /t 0",
        ]
    )


def fichier_wsb(worktree: Path, commande: str, ident: str) -> str:
    """Configuration Windows Sandbox : réseau, presse-papiers, imprimantes, micro, caméra et GPU coupés, client
    protégé, UN seul dossier partagé (le worktree, en C:\\atelier)."""
    if not ident.isalnum():
        raise ValueError("identifiant de commande invalide")
    encode = base64.b64encode(script_wsb(commande, ident).encode("utf-16-le")).decode("ascii")
    lancement = f"powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encode}"
    return "\n".join(
        [
            "<Configuration>",
            "  <Networking>Disable</Networking>",
            "  <ClipboardRedirection>Disable</ClipboardRedirection>",
            "  <PrinterRedirection>Disable</PrinterRedirection>",
            "  <AudioInput>Disable</AudioInput>",
            "  <VideoInput>Disable</VideoInput>",
            "  <vGPU>Disable</vGPU>",
            "  <ProtectedClient>Enable</ProtectedClient>",
            "  <MappedFolders>",
            "    <MappedFolder>",
            f"      <HostFolder>{escape(str(worktree))}</HostFolder>",
            r"      <SandboxFolder>C:\atelier</SandboxFolder>",
            "      <ReadOnly>false</ReadOnly>",
            "    </MappedFolder>",
            "  </MappedFolders>",
            "  <LogonCommand>",
            f"    <Command>{escape(lancement)}</Command>",
            "  </LogonCommand>",
            "</Configuration>",
            "",
        ]
    )


def envelopper(
    bac_id: str,
    commande: str,
    worktree: Path,
    image: str = IMAGE_DEFAUT,
    dossier_wsb: Path | None = None,
    ident: str | None = None,
) -> list[str]:
    """Arguments qui exécutent `commande` dans le bac `bac_id`, réseau coupé, seul le worktree monté."""
    if not commande.strip():
        raise ValueError("commande vide")
    if bac_id in ("docker", "podman"):
        return [
            bac_id,
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "-v",
            f"{worktree}:/atelier",
            "-w",
            "/atelier",
            image,
            "sh",
            "-c",
            commande,
        ]
    if bac_id == "bubblewrap":
        wt = str(worktree)
        lectures = [a for d in ("/bin", "/lib", "/lib64", "/etc") for a in ("--ro-bind-try", d, d)]
        return [
            "bwrap",
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--ro-bind",
            "/usr",
            "/usr",
            *lectures,
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",  # noqa: S108  (tmpfs propre au bac, vide)
            "--bind",
            wt,
            wt,
            "--chdir",
            wt,
            "sh",
            "-c",
            commande,
        ]
    if bac_id == "sandbox_exec":
        return ["sandbox-exec", "-p", profil_sandbox_exec(worktree), "sh", "-c", commande]
    if bac_id == "windows_sandbox":
        if dossier_wsb is None:
            raise ValueError("Windows Sandbox : dossier des fichiers .wsb manquant")
        if len(commande) > COMMANDE_MAX:
            raise ValueError(f"commande trop longue pour Windows Sandbox ({len(commande)} > {COMMANDE_MAX} caractères)")
        ident = ident or os.urandom(8).hex()
        dossier_wsb.mkdir(parents=True, exist_ok=True)
        wsb = dossier_wsb / f"{ident}.wsb"
        wsb.write_text(fichier_wsb(worktree, commande, ident), encoding="utf-8")
        # -I : ni le dossier courant (le worktree, modifiable par l'atelier) ni PYTHON* dans le chemin d'import
        return [sys.executable, "-I", "-m", "jarvis2", "bac-a-sable-wsb", str(wsb), str(worktree), ident]
    raise ValueError(f"Bac à sable inconnu : {bac_id}")


def commande_reecrite(args: Sequence[str], plateforme: str = sys.platform) -> str:
    """Commande Bash renvoyée à Claude Code (Git Bash sous Windows : pas de conversion des chemins /atelier)."""
    commande = shlex.join(args)
    if plateforme == "win32" and args and args[0] in ("docker", "podman"):
        return f"MSYS_NO_PATHCONV=1 {commande}"
    return commande


# --- Exécution d'une commande dans Windows Sandbox (sous-commande `jarvis2 bac-a-sable-wsb`) ------------------------


async def executer_wsb(
    wsb: Path,
    worktree: Path,
    ident: str,
    lanceur: Lanceur | None = None,
    exe: Path | None = None,
    delai: float = DELAI_WSB,
    sondage: float = 1.0,
    dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ecrire: Callable[[str], object] = print,
) -> int:
    """Lance Windows Sandbox avec ce .wsb, attend le code de retour écrit par le bac, affiche la sortie, nettoie."""
    lanceur = lanceur or LanceurReel()
    exe = exe or Detecteur(lanceur).exe_windows_sandbox()
    sorties = worktree / DOSSIER_SORTIE_WSB
    fichier_code = sorties / f"{ident}.code"
    fichiers_sortie = [sorties / f"{ident}.sortie", sorties / f"{ident}.erreurs"]
    lancement = asyncio.ensure_future(lanceur.executer([str(exe), str(wsb)], delai))
    code: int | None = None
    try:
        attendu = 0.0
        while attendu < delai:
            if lanceur.existe(fichier_code):
                brut = fichier_code.read_text(encoding="utf-8-sig", errors="replace").strip()
                try:
                    code = int(brut or "1")
                except ValueError:
                    code = 1
                break
            if lancement.done() and lancement.result()[0] != 0:
                retour, message = lancement.result()
                ecrire(f"Windows Sandbox n'a pas démarré (code {retour}) : {message}")
                return retour or 1
            await dormir(sondage)
            attendu += sondage
        if code is None:
            ecrire(f"Délai dépassé : aucune fin de commande dans Windows Sandbox après {delai:g} s")
            return 124
        for fichier in fichiers_sortie:
            if lanceur.existe(fichier):
                texte = fichier.read_text(encoding="utf-8", errors="replace").rstrip()
                if texte:
                    ecrire(texte)
        return code
    finally:
        if not lancement.done():
            lancement.cancel()
        for f in (fichier_code, *fichiers_sortie, wsb):
            with contextlib.suppress(OSError):
                f.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            sorties.rmdir()  # seulement s'il est vide
