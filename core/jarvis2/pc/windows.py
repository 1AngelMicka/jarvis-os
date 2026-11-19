"""Pilote Windows : le SEUL endroit où JARVIS lit et règle réellement le PC.

Sans dépendance, sans wmic :
- volume : Core Audio (IAudioEndpointVolume) par COM, appelé avec ctypes ;
- luminosité : écrans externes par DDC/CI (dxva2), écran de portable par WMI (`Get-CimInstance`) ;
- fenêtres : API user32 (EnumWindows, ShowWindow, SetForegroundWindow, WM_CLOSE) ;
- média en cours : contrôles multimédias du système (GlobalSystemMediaTransportControls, WinRT par PowerShell) ;
- verrouillage : LockWorkStation ; extinction : `shutdown /s /t` (annulable par `shutdown /a`) ;
- modes : plan d'alimentation (`powercfg`), bannières de notification et thème sombre (registre de l'utilisateur,
  annoncés aux applications par WM_SETTINGCHANGE).

Garde-fou : aucun réglage n'est appliqué pendant les tests (variable PYTEST_CURRENT_TEST), même si un test se
trompait de pilote. Les tests utilisent un faux pilote.
"""

# ruff: noqa: E501 — scripts PowerShell gardés sur une ligne par instruction
from __future__ import annotations

import base64
import ctypes
import importlib
import json
import ntpath
import os
import re
import subprocess
import sys
import time
from ctypes import wintypes
from typing import Any

from .pilote import ActionFenetre, CommandeMedia, ErreurPilote, Fenetre, Media, Volume

# Attributs propres à Windows, typés Any : le module s'importe (et se vérifie avec mypy) sur tous les systèmes.
_windll: Any = getattr(ctypes, "windll", None)
_WINFUNCTYPE: Any = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
SANS_FENETRE = 0x08000000  # CREATE_NO_WINDOW : aucune console ne s'ouvre
DELAI_POWERSHELL = 20.0
GUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
CLE_NOTIFICATIONS = r"Software\Microsoft\Windows\CurrentVersion\PushNotifications"
CLE_THEME = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def disponible() -> bool:
    return sys.platform == "win32" and _windll is not None


def _garde_ecriture() -> None:
    if "PYTEST_CURRENT_TEST" in os.environ:
        raise ErreurPilote("Réglage du PC refusé pendant les tests (faux pilote attendu)")


def _fn(dll: str, nom: str, restype: Any, *argtypes: Any) -> Any:
    f = getattr(getattr(_windll, dll), nom)
    f.restype = restype
    f.argtypes = list(argtypes)
    return f


def _executer(commande: list[str], delai: float = 10.0) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(commande, capture_output=True, timeout=delai, creationflags=SANS_FENETRE, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ErreurPilote(f"{commande[0]} indisponible : {exc}") from exc


def _texte(octets: bytes) -> str:
    try:
        return octets.decode("oem", errors="replace")  # sortie des outils Windows dans la page de code OEM
    except LookupError:
        return octets.decode("utf-8", errors="replace")


def powershell(script: str, env: dict[str, str] | None = None, delai: float = DELAI_POWERSHELL) -> str:
    """Exécute un script PowerShell (Windows PowerShell 5.1, qui charge WinRT). Les valeurs passent par
    l'environnement, jamais dans le texte du script : aucune injection possible."""
    entete = "$ErrorActionPreference='Stop';[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    code = base64.b64encode((entete + script).encode("utf-16-le")).decode()
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", code],
            capture_output=True,
            timeout=delai,
            creationflags=SANS_FENETRE,
            env={**os.environ, **(env or {})},
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ErreurPilote(f"PowerShell indisponible : {exc}") from exc
    if r.returncode != 0:
        raise ErreurPilote(f"PowerShell a échoué : {r.stderr.decode('utf-8', errors='replace').strip()[:300]}")
    return r.stdout.decode("utf-8", errors="replace").strip()


# Attente d'une opération WinRT depuis PowerShell 5.1 (IAsyncOperation → Task)
ATTENTE_WINRT = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Attendre($op, [Type]$type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
"""

SCRIPT_MEDIA = (
    ATTENTE_WINRT
    + r"""
$G = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager,Windows.Media.Control,ContentType=WindowsRuntime]
$m = Attendre ($G::RequestAsync()) $G
$s = $m.GetCurrentSession()
if (-not $s) { '{}'; exit 0 }
$cmd = $env:JARVIS_MEDIA
if ($cmd) {
  $op = switch ($cmd) { 'lecture' { $s.TryPlayAsync() } 'pause' { $s.TryPauseAsync() }
    'bascule' { $s.TryTogglePlayPauseAsync() } 'suivant' { $s.TrySkipNextAsync() } 'precedent' { $s.TrySkipPreviousAsync() } }
  $ok = Attendre $op ([bool]); @{ ok = $ok } | ConvertTo-Json -Compress; exit 0
}
$P = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties,Windows.Media.Control,ContentType=WindowsRuntime]
$p = Attendre ($s.TryGetMediaPropertiesAsync()) $P
$i = $s.GetPlaybackInfo()
@{ application = $s.SourceAppUserModelId; titre = $p.Title; artiste = $p.Artist; statut = "$($i.PlaybackStatus)" } |
  ConvertTo-Json -Compress
"""
)

STATUTS_MEDIA = {"Playing": "lecture", "Paused": "pause", "Stopped": "arret", "Closed": "arret", "Changing": "lecture"}

SCRIPT_LUMINOSITE_WMI = r"""
$b = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction SilentlyContinue | Select-Object -First 1
if ($env:JARVIS_LUMINOSITE) {
  $m = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | Select-Object -First 1
  Invoke-CimMethod -InputObject $m -MethodName WmiSetBrightness -Arguments @{ Timeout = [uint32]1; Brightness = [byte]$env:JARVIS_LUMINOSITE } | Out-Null
  'ok'; exit 0
}
if ($b) { $b.CurrentBrightness } else { '' }
"""


# --- COM : Core Audio ------------------------------------------------------------------------------------------


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(texte: str) -> _GUID:
    g = _GUID()
    hr = _windll.ole32.CLSIDFromString(ctypes.c_wchar_p(texte), ctypes.byref(g))
    if hr < 0:
        raise ErreurPilote("Identifiant COM invalide")
    return g


def _methode(objet: ctypes.c_void_p, index: int, *argtypes: Any) -> Any:
    """Méthode n° `index` de la table virtuelle d'un objet COM."""
    table = ctypes.cast(objet, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    prototype = _WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
    fonction = prototype(table[index])
    return lambda *a: fonction(objet, *a)


def _verifier_hr(hr: int, quoi: str) -> None:
    if hr < 0:
        raise ErreurPilote(f"{quoi} : refus de Windows (0x{hr & 0xFFFFFFFF:08X})")


class _Volume:
    """Contexte : ouvre IAudioEndpointVolume du haut-parleur par défaut, le libère à la sortie."""

    CLSID_ENUM = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
    IID_ENUM = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
    IID_VOLUME = "{5CDF2C82-841E-4546-9722-0CF74078229A}"

    def __enter__(self) -> _Volume:
        if not disponible():
            raise ErreurPilote("Volume : Windows seulement")
        self._init = _windll.ole32.CoInitializeEx(None, 0)
        self._objets: list[ctypes.c_void_p] = []
        enum, dev, vol = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        clsid, iid = _guid(self.CLSID_ENUM), _guid(self.IID_ENUM)
        co = _fn("ole32", "CoCreateInstance", ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                 ctypes.c_void_p, ctypes.c_void_p)  # fmt: skip
        _verifier_hr(co(ctypes.byref(clsid), None, 23, ctypes.byref(iid), ctypes.byref(enum)), "Audio")
        self._objets.append(enum)
        defaut = _methode(enum, 4, ctypes.c_int, ctypes.c_int, ctypes.c_void_p)
        _verifier_hr(defaut(0, 1, ctypes.byref(dev)), "Haut-parleur par défaut")  # eRender, eMultimedia
        self._objets.append(dev)
        iid_vol = _guid(self.IID_VOLUME)
        activer = _methode(dev, 3, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p)
        _verifier_hr(activer(ctypes.byref(iid_vol), 23, None, ctypes.byref(vol)), "Volume")
        self._objets.append(vol)
        self.objet = vol
        return self

    def __exit__(self, *_: Any) -> None:
        for o in reversed(self._objets):
            if o.value:
                _methode(o, 2)()  # Release
        if self._init in (0, 1):
            _windll.ole32.CoUninitialize()

    def lire(self) -> Volume:
        niveau, muet = ctypes.c_float(), wintypes.BOOL()
        _verifier_hr(_methode(self.objet, 9, ctypes.c_void_p)(ctypes.byref(niveau)), "Lecture du volume")
        _verifier_hr(_methode(self.objet, 15, ctypes.c_void_p)(ctypes.byref(muet)), "Lecture de la sourdine")
        return Volume(round(niveau.value * 100), bool(muet.value))

    def regler(self, niveau: int) -> None:
        valeur = ctypes.c_float(max(0, min(100, niveau)) / 100)
        _verifier_hr(_methode(self.objet, 7, ctypes.c_float, ctypes.c_void_p)(valeur, None), "Réglage du volume")

    def sourdine(self, muet: bool) -> None:
        _verifier_hr(_methode(self.objet, 14, wintypes.BOOL, ctypes.c_void_p)(int(muet), None), "Sourdine")


# --- Écrans (DDC/CI) -------------------------------------------------------------------------------------------


class _EcranPhysique(ctypes.Structure):
    _fields_ = [("handle", wintypes.HANDLE), ("description", ctypes.c_wchar * 128)]


def _ecrans_physiques() -> list[tuple[Any, Any]]:
    """(tableau, nombre) par moniteur ; à libérer par `DestroyPhysicalMonitors`."""
    moniteurs: list[int] = []
    rappel_type = _WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.c_void_p, wintypes.LPARAM)

    def rappel(h: int, *_: Any) -> bool:
        moniteurs.append(h)
        return True

    r = rappel_type(rappel)
    _fn("user32", "EnumDisplayMonitors", wintypes.BOOL, wintypes.HDC, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.LPARAM)(None, None, r, 0)  # fmt: skip
    nombre_de = _fn("dxva2", "GetNumberOfPhysicalMonitorsFromHMONITOR", wintypes.BOOL, wintypes.HMONITOR,
                    ctypes.POINTER(wintypes.DWORD))  # fmt: skip
    lire = _fn("dxva2", "GetPhysicalMonitorsFromHMONITOR", wintypes.BOOL, wintypes.HMONITOR, wintypes.DWORD,
               ctypes.c_void_p)  # fmt: skip
    sortie = []
    for h in moniteurs:
        n = wintypes.DWORD()
        if not nombre_de(h, ctypes.byref(n)) or n.value == 0:
            continue
        tableau = (_EcranPhysique * n.value)()
        if lire(h, n.value, tableau):
            sortie.append((tableau, n.value))
    return sortie


def _ddc(niveau: int | None) -> int | None:
    """Lit (niveau None) ou règle la luminosité des écrans DDC/CI ; renvoie le premier niveau lu (en %)."""
    lire = _fn("dxva2", "GetMonitorBrightness", wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD),
               ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD))  # fmt: skip
    regler = _fn("dxva2", "SetMonitorBrightness", wintypes.BOOL, wintypes.HANDLE, wintypes.DWORD)
    liberer = _fn("dxva2", "DestroyPhysicalMonitors", wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p)
    trouve: int | None = None
    for tableau, n in _ecrans_physiques():
        try:
            for i in range(n):
                mini, cour, maxi = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
                if not lire(tableau[i].handle, ctypes.byref(mini), ctypes.byref(cour), ctypes.byref(maxi)):
                    continue
                etendue = max(1, maxi.value - mini.value)
                if niveau is None:
                    if trouve is None:
                        trouve = round((cour.value - mini.value) * 100 / etendue)
                else:
                    if regler(tableau[i].handle, mini.value + round(etendue * niveau / 100)):
                        trouve = niveau
        finally:
            liberer(n, tableau)
    return trouve


# --- Fenêtres --------------------------------------------------------------------------------------------------

PROGRAMMES_SYSTEME = frozenset({"textinputhost.exe", "applicationframehost.exe", "shellexperiencehost.exe",
                                "searchhost.exe", "startmenuexperiencehost.exe", "lockapp.exe"})  # fmt: skip


def programme_de(hwnd: int) -> str:
    pid = wintypes.DWORD()
    _fn("user32", "GetWindowThreadProcessId", wintypes.DWORD, wintypes.HWND, ctypes.POINTER(wintypes.DWORD))(
        hwnd, ctypes.byref(pid)
    )
    h = _fn("kernel32", "OpenProcess", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)(
        0x1000, False, pid.value
    )
    if not h:
        return ""
    try:
        tampon, taille = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
        ok = _fn("kernel32", "QueryFullProcessImageNameW", wintypes.BOOL, wintypes.HANDLE, wintypes.DWORD,
                 wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))(h, 0, tampon, ctypes.byref(taille))  # fmt: skip
        return tampon.value if ok else ""
    finally:
        _fn("kernel32", "CloseHandle", wintypes.BOOL, wintypes.HANDLE)(h)


def _titre(hwnd: int) -> str:
    longueur = _fn("user32", "GetWindowTextLengthW", ctypes.c_int, wintypes.HWND)(hwnd)
    if longueur <= 0:
        return ""
    tampon = ctypes.create_unicode_buffer(longueur + 1)
    _fn("user32", "GetWindowTextW", ctypes.c_int, wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)(
        hwnd, tampon, longueur + 1
    )
    return tampon.value


def _masquee(hwnd: int) -> bool:
    """Fenêtre « cachée » par le système (applications UWP en arrière-plan) ou fenêtre d'outil."""
    cachee = ctypes.c_int()
    _fn("dwmapi", "DwmGetWindowAttribute", ctypes.c_long, wintypes.HWND, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD)(hwnd, 14, ctypes.byref(cachee), 4)  # fmt: skip
    style = _fn("user32", "GetWindowLongW", ctypes.c_long, wintypes.HWND, ctypes.c_int)(hwnd, -20)
    return bool(cachee.value) or bool(style & 0x80)  # DWMWA_CLOAKED, WS_EX_TOOLWINDOW


def premier_plan() -> int | None:
    h = _fn("user32", "GetForegroundWindow", wintypes.HWND)()
    return int(h) if h else None


def plein_ecran(hwnd: int) -> bool:
    """La fenêtre couvre-t-elle tout son écran (jeu, vidéo en plein écran) ?"""

    class Rect(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]

    class InfoMoniteur(ctypes.Structure):
        _fields_ = [("taille", wintypes.DWORD), ("ecran", Rect), ("travail", Rect), ("drapeaux", wintypes.DWORD)]

    rect = Rect()
    if not _fn("user32", "GetWindowRect", wintypes.BOOL, wintypes.HWND, ctypes.c_void_p)(hwnd, ctypes.byref(rect)):
        return False
    moniteur = _fn("user32", "MonitorFromWindow", wintypes.HMONITOR, wintypes.HWND, wintypes.DWORD)(hwnd, 2)
    info = InfoMoniteur()
    info.taille = ctypes.sizeof(InfoMoniteur)
    if not _fn("user32", "GetMonitorInfoW", wintypes.BOOL, wintypes.HMONITOR, ctypes.c_void_p)(
        moniteur, ctypes.byref(info)
    ):
        return False
    e = info.ecran
    return bool(rect.l <= e.l and rect.t <= e.t and rect.r >= e.r and rect.b >= e.b)


# --- Le pilote -------------------------------------------------------------------------------------------------


class PiloteWindows:
    nom = "windows"

    # Lecture

    def lire_volume(self) -> Volume | None:
        with _Volume() as v:
            return v.lire()

    def lire_luminosite(self) -> int | None:
        if not disponible():
            return None
        niveau = _ddc(None)
        if niveau is not None:
            return niveau
        sortie = powershell(SCRIPT_LUMINOSITE_WMI)
        return int(sortie) if sortie.isdigit() else None

    def fenetres(self) -> list[Fenetre]:
        if not disponible():
            raise ErreurPilote("Fenêtres : Windows seulement")
        trouvees: list[int] = []
        rappel_type = _WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        visible = _fn("user32", "IsWindowVisible", wintypes.BOOL, wintypes.HWND)

        def rappel(hwnd: int, _: Any) -> bool:
            if hwnd and visible(hwnd):
                trouvees.append(int(hwnd))
            return True

        _fn("user32", "EnumWindows", wintypes.BOOL, ctypes.c_void_p, wintypes.LPARAM)(rappel_type(rappel), 0)
        active = premier_plan()
        reduite = _fn("user32", "IsIconic", wintypes.BOOL, wintypes.HWND)
        sortie = []
        for h in trouvees:
            titre = _titre(h)
            if not titre or _masquee(h):
                continue
            programme = ntpath.basename(programme_de(h)).lower()
            if programme in PROGRAMMES_SYSTEME or (programme == "explorer.exe" and titre == "Program Manager"):
                continue
            sortie.append(Fenetre(h, titre[:200], programme or "?", h == active, bool(reduite(h))))
        return sortie

    def media(self) -> Media | None:
        if not disponible():
            return None
        brut = json.loads(powershell(SCRIPT_MEDIA, {"JARVIS_MEDIA": ""}) or "{}")
        if not brut:
            return Media()
        return Media(
            brut.get("application") or None,
            brut.get("titre") or None,
            brut.get("artiste") or None,
            STATUTS_MEDIA.get(str(brut.get("statut"))),
        )

    def verrouille(self) -> bool | None:
        """Heuristique classique : le bureau d'entrée n'est pas accessible quand la session est verrouillée."""
        if not disponible():
            return None
        h = _fn("user32", "OpenInputDesktop", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)(
            0, False, 0x0100
        )
        if not h:
            return True
        try:
            return not _fn("user32", "SwitchDesktop", wintypes.BOOL, wintypes.HANDLE)(h)
        finally:
            _fn("user32", "CloseDesktop", wintypes.BOOL, wintypes.HANDLE)(h)

    def lire_plan_alimentation(self) -> str | None:
        r = _executer(["powercfg", "/getactivescheme"])
        trouve = GUID_RE.search(_texte(r.stdout))
        return trouve.group(0).lower() if trouve else None

    def plans_alimentation(self) -> dict[str, str]:
        r = _executer(["powercfg", "/list"])
        plans = {}
        for ligne in _texte(r.stdout).splitlines():
            guid = GUID_RE.search(ligne)
            nom = re.search(r"\(([^)]*)\)", ligne)
            if guid:
                plans[guid.group(0).lower()] = nom.group(1).strip() if nom else guid.group(0)
        return plans

    def _registre(self, cle: str, valeur: str) -> int | None:
        winreg: Any = importlib.import_module("winreg")
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, cle) as k:
                return int(winreg.QueryValueEx(k, valeur)[0])
        except OSError:
            return None

    def _ecrire_registre(self, cle: str, valeur: str, donnee: int) -> None:
        winreg: Any = importlib.import_module("winreg")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cle) as k:
            winreg.SetValueEx(k, valeur, 0, winreg.REG_DWORD, donnee)

    def lire_notifications(self) -> bool | None:
        if not disponible():
            return None
        valeur = self._registre(CLE_NOTIFICATIONS, "ToastEnabled")
        return True if valeur is None else bool(valeur)  # valeur absente : bannières autorisées

    def lire_theme_sombre(self) -> bool | None:
        if not disponible():
            return None
        valeur = self._registre(CLE_THEME, "AppsUseLightTheme")
        return None if valeur is None else valeur == 0

    # Réglages

    def regler_volume(self, niveau: int) -> None:
        _garde_ecriture()
        with _Volume() as v:
            v.regler(niveau)

    def regler_muet(self, muet: bool) -> None:
        _garde_ecriture()
        with _Volume() as v:
            v.sourdine(muet)

    def regler_luminosite(self, niveau: int) -> None:
        _garde_ecriture()
        niveau = max(0, min(100, niveau))
        if _ddc(niveau) is None:
            powershell(SCRIPT_LUMINOSITE_WMI, {"JARVIS_LUMINOSITE": str(niveau)})

    def agir_fenetre(self, ident: int, action: ActionFenetre) -> None:
        _garde_ecriture()
        if not _fn("user32", "IsWindow", wintypes.BOOL, wintypes.HWND)(ident):
            raise ErreurPilote("Cette fenêtre n'existe plus")
        montrer = _fn("user32", "ShowWindow", wintypes.BOOL, wintypes.HWND, ctypes.c_int)
        if action == "minimiser":
            montrer(ident, 6)
        elif action == "restaurer":
            montrer(ident, 9)
        elif action == "activer":
            if _fn("user32", "IsIconic", wintypes.BOOL, wintypes.HWND)(ident):
                montrer(ident, 9)
            touche = _fn("user32", "keybd_event", None, wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p)
            touche(0x12, 0, 0, None)  # Alt pressée puis relâchée : Windows autorise alors le passage au premier plan
            touche(0x12, 0, 2, None)
            _fn("user32", "SetForegroundWindow", wintypes.BOOL, wintypes.HWND)(ident)
        elif action == "fermer":  # demande polie : l'application peut proposer d'enregistrer
            _fn("user32", "PostMessageW", wintypes.BOOL, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                wintypes.LPARAM)(ident, 0x0010, 0, 0)  # fmt: skip
        else:
            raise ErreurPilote(f"Action de fenêtre inconnue : {action}")

    def fenetre_existe(self, ident: int) -> bool:
        return bool(_fn("user32", "IsWindow", wintypes.BOOL, wintypes.HWND)(ident))

    def commande_media(self, commande: CommandeMedia) -> None:
        _garde_ecriture()
        brut = json.loads(powershell(SCRIPT_MEDIA, {"JARVIS_MEDIA": commande}) or "{}")
        if not brut:
            raise ErreurPilote("Aucun média en cours")
        if not brut.get("ok"):
            raise ErreurPilote("L'application du média a refusé la commande")

    def verrouiller(self) -> None:
        _garde_ecriture()
        if not _fn("user32", "LockWorkStation", wintypes.BOOL)():
            raise ErreurPilote("Windows a refusé le verrouillage")

    def planifier_extinction(self, delai_s: int, message: str) -> None:
        _garde_ecriture()
        r = _executer(["shutdown", "/s", "/t", str(delai_s), "/c", message[:500]])
        if r.returncode != 0:
            raise ErreurPilote(f"Extinction refusée par Windows : {_texte(r.stderr or r.stdout).strip()[:200]}")

    def annuler_extinction(self) -> bool:
        # Annuler protège : permis même pendant les tests ? Non : le faux pilote suffit, on ne touche à rien.
        _garde_ecriture()
        r = _executer(["shutdown", "/a"])
        return r.returncode == 0  # 1116 : aucune extinction en cours

    def regler_plan_alimentation(self, ident: str) -> None:
        _garde_ecriture()
        if not GUID_RE.fullmatch(ident):
            raise ErreurPilote("Plan d'alimentation invalide")
        r = _executer(["powercfg", "/setactive", ident])
        if r.returncode != 0:
            raise ErreurPilote("Windows a refusé le plan d'alimentation")

    def regler_notifications(self, actives: bool) -> None:
        _garde_ecriture()
        self._ecrire_registre(CLE_NOTIFICATIONS, "ToastEnabled", int(actives))

    def regler_theme_sombre(self, sombre: bool) -> None:
        _garde_ecriture()
        self._ecrire_registre(CLE_THEME, "AppsUseLightTheme", 0 if sombre else 1)
        self._ecrire_registre(CLE_THEME, "SystemUsesLightTheme", 0 if sombre else 1)
        resultat = wintypes.DWORD()  # les applications ouvertes changent de thème tout de suite
        _fn("user32", "SendMessageTimeoutW", wintypes.LPARAM, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
            wintypes.LPCWSTR, wintypes.UINT, wintypes.UINT, ctypes.c_void_p)(
            0xFFFF, 0x001A, 0, "ImmersiveColorSet", 2, 1000, ctypes.byref(resultat))  # fmt: skip
        time.sleep(0.1)
