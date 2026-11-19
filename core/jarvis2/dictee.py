"""Dictée globale (lot K3) : maintenir le raccourci de l'application de bureau, parler, relâcher : le texte transcrit
sur le PC est collé dans l'application au premier plan.

- Désactivée par défaut (Réglages › Voix & écoute › Dictée).
- Dictionnaire de corrections de l'utilisateur (« jarvice » → « JARVIS »), appliqué mot entier, sans tenir compte
  de la casse ni des accents.
- Ponctuation dite à voix haute (« virgule », « point d'interrogation », « à la ligne »…).
- Mise en forme selon l'application au premier plan : « phrase » (traitement de texte, courriel : majuscule et
  point), « message » (messageries : majuscule, sans point final), « code » (éditeurs, terminaux : texte tel quel,
  sans majuscule ni point ajoutés), « brut ». Choix par programme réglable.
- Collage : seulement depuis le PC lui-même (jamais à distance), jamais en mode sans écran. Presse-papiers
  remplacé le temps du collage, puis remis (texte seulement).
"""

from __future__ import annotations

import ctypes
import json
import logging
import re
import sys
import time
import unicodedata
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from .voix import sans_accents

if TYPE_CHECKING:
    from .db import Base

journal = logging.getLogger("jarvis2.dictee")

CLE = "dictee"
Style = Literal["phrase", "message", "code", "brut"]
STYLES: tuple[Style, ...] = ("phrase", "message", "code", "brut")
CORRECTIONS_MAX = 200
REGLAGES_DEFAUT: dict[str, Any] = {"actif": False, "corrections": [], "styles": {}}

PROGRAMMES: dict[str, Style] = {
    # éditeurs de code et terminaux
    **{
        p: "code"
        for p in (
            "code.exe",
            "code - insiders.exe",
            "cursor.exe",
            "devenv.exe",
            "idea64.exe",
            "pycharm64.exe",
            "webstorm64.exe",
            "rider64.exe",
            "sublime_text.exe",
            "notepad++.exe",
            "windowsterminal.exe",
            "wt.exe",
            "cmd.exe",
            "powershell.exe",
            "pwsh.exe",
            "conhost.exe",
            "alacritty.exe",
            "wezterm-gui.exe",
        )
    },
    # messageries
    **{
        p: "message"
        for p in (
            "discord.exe",
            "slack.exe",
            "teams.exe",
            "ms-teams.exe",
            "whatsapp.exe",
            "signal.exe",
            "telegram.exe",
            "element.exe",
        )
    },
    # traitement de texte et courriel
    **{p: "phrase" for p in ("winword.exe", "outlook.exe", "olk.exe", "thunderbird.exe", "soffice.bin", "notepad.exe")},
}

PONCTUATION_DITE: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\s*\b(?:point a la ligne|point,? a la ligne)\b[.,]?\s*", re.IGNORECASE), ".\n"),
    (re.compile(r"\s*\b(?:a la ligne|nouvelle ligne|retour a la ligne)\b[.,]?\s*", re.IGNORECASE), "\n"),
    (re.compile(r"\s*\bpoint d'interrogation\b[.,]?", re.IGNORECASE), " ?"),
    (re.compile(r"\s*\bpoint d'exclamation\b[.,]?", re.IGNORECASE), " !"),
    (re.compile(r"\s*\bpoints de suspension\b[.,]?", re.IGNORECASE), "…"),
    (re.compile(r"\s*\bdeux[- ]points\b[.,]?", re.IGNORECASE), " :"),
    (re.compile(r"\s*\bpoint[- ]virgule\b[.,]?", re.IGNORECASE), " ;"),
    (re.compile(r"\s*\bvirgule\b[.,]?", re.IGNORECASE), ","),
    (re.compile(r"\s*\bouvrez? les guillemets\b[.,]?\s*", re.IGNORECASE), " « "),
    (re.compile(r"\s*\bfermez? les guillemets\b[.,]?", re.IGNORECASE), " »"),
]


def _plier(texte: str) -> str:
    return sans_accents(texte).lower()


def _remplacer_plie(texte: str, motif: re.Pattern[str], par: str) -> str:
    """Remplacement cherché sur le texte sans accents, appliqué au texte d'origine (mêmes positions)."""
    plie = _plier(texte)
    if len(plie) != len(texte):  # caractères composés rares : recherche directe
        return motif.sub(par, texte)
    morceaux, fin = [], 0
    for m in motif.finditer(plie):
        morceaux.append(texte[fin : m.start()])
        morceaux.append(m.expand(par))
        fin = m.end()
    morceaux.append(texte[fin:])
    return "".join(morceaux)


def ponctuation_dite(texte: str) -> str:
    for motif, par in PONCTUATION_DITE:
        texte = _remplacer_plie(texte, motif, par)
    return re.sub(r"[ \t]+\n", "\n", re.sub(r"[ \t]{2,}", " ", texte)).strip(" ")


def valider_corrections(corrections: Any) -> list[dict[str, str]]:
    sortie: list[dict[str, str]] = []
    vus: set[str] = set()
    for c in corrections or []:
        if not isinstance(c, dict):
            continue
        de = " ".join(str(c.get("de", "")).split())[:80]
        vers = str(c.get("vers", ""))[:200].strip()
        if not de or _plier(de) in vus:
            continue
        vus.add(_plier(de))
        sortie.append({"de": de, "vers": vers})
    return sortie[:CORRECTIONS_MAX]


def corriger(texte: str, corrections: list[dict[str, str]]) -> str:
    """Mots entiers, sans casse ni accents ; les expressions les plus longues d'abord."""
    for c in sorted(corrections, key=lambda c: -len(c["de"])):
        motif = re.compile(r"(?<!\w)" + re.escape(_plier(c["de"])) + r"(?!\w)", re.IGNORECASE)
        texte = _remplacer_plie(texte, motif, c["vers"].replace("\\", "\\\\"))
    return texte


def mettre_en_forme(texte: str, style: Style) -> str:
    texte = texte.strip()
    if not texte or style == "brut":
        return texte
    if style == "code":
        if len(texte) > 1 and texte[0].isupper() and not texte[:2].isupper():
            texte = texte[0].lower() + texte[1:]
        return texte.rstrip(".")
    texte = texte[0].upper() + texte[1:]
    if style == "message":
        return texte[:-1] if texte.endswith(".") and not texte.endswith("..") else texte
    if not texte.endswith((".", "!", "?", "…", ":", ";", "»", "\n")):
        texte += "."
    return texte


def style_pour(programme: str | None, styles: dict[str, str]) -> Style:
    nom = (programme or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    voulu = styles.get(nom) or PROGRAMMES.get(nom) or "phrase"
    return voulu if voulu in STYLES else "phrase"


def preparer(texte: str, reglages: dict[str, Any], programme: str | None) -> tuple[str, Style]:
    style = style_pour(programme, reglages.get("styles") or {})
    sortie = corriger(ponctuation_dite(texte), reglages.get("corrections") or [])
    sortie = unicodedata.normalize("NFC", mettre_en_forme(sortie, style))
    return sortie, style


# --- Windows : programme au premier plan, collage --------------------------------------------------------------


def programme_au_premier_plan() -> str | None:
    if sys.platform != "win32":
        return None
    from .pc import windows

    if not windows.disponible():
        return None
    h = windows.premier_plan()
    return windows.programme_de(h) if h is not None else None


CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
VK_CONTROL, VK_V = 0x11, 0x56
MODIFICATEURS = (0x10, 0x11, 0x12, 0x5B, 0x5C)  # Maj, Ctrl, Alt, Windows gauche et droite
KEYEVENTF_KEYUP = 0x0002
ATTENTE_TOUCHES = 1.5  # secondes au plus pour que les touches du raccourci soient relâchées


def coller(texte: str) -> None:
    """Met le texte au presse-papiers, envoie Ctrl+V à l'application au premier plan, remet l'ancien texte."""
    from ctypes import wintypes

    from .pc import windows

    windows._garde_ecriture()  # jamais pendant les tests
    if not windows.disponible():
        raise RuntimeError("Collage possible seulement sous Windows")
    windll: Any = getattr(ctypes, "windll", None)
    user32, kernel32 = windll.user32, windll.kernel32
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]

    def ouvrir() -> None:
        for _ in range(10):
            if user32.OpenClipboard(None):
                return
            time.sleep(0.03)
        raise RuntimeError("Presse-papiers occupé par une autre application")

    def lire() -> str | None:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p) if p else None
        finally:
            kernel32.GlobalUnlock(h)

    def ecrire(valeur: str) -> None:
        donnees = ctypes.create_unicode_buffer(valeur)
        taille = ctypes.sizeof(donnees)
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, taille)
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, donnees, taille)
        kernel32.GlobalUnlock(h)
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, h):
            raise RuntimeError("Presse-papiers non modifiable")

    ouvrir()
    try:
        ancien = lire()
        ecrire(texte)
    finally:
        user32.CloseClipboard()
    # Alt ou Maj encore tenus feraient de Ctrl+V un « collage spécial » : on attend qu'ils soient relâchés
    fin = time.monotonic() + ATTENTE_TOUCHES
    while time.monotonic() < fin and any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in MODIFICATEURS):
        time.sleep(0.02)
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_V, 0, 0, 0)
    user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
    if ancien is not None:
        time.sleep(0.4)  # l'application lit le presse-papiers après avoir reçu Ctrl+V
        ouvrir()
        try:
            ecrire(ancien)
        finally:
            user32.CloseClipboard()


# --- Service ------------------------------------------------------------------------------------------------


class ServiceDictee:
    def __init__(self, pool: Base) -> None:
        self.pool = pool
        self.reglages: dict[str, Any] | None = None
        self.colleur: Callable[[str], None] = coller
        self.premier_plan: Callable[[], str | None] = programme_au_premier_plan

    async def charger(self) -> dict[str, Any]:
        if self.reglages is None:
            brut = await self.pool.fetchval("SELECT valeur FROM etat_systeme WHERE cle = $1", CLE)
            valeur = json.loads(brut) if isinstance(brut, str) else (brut or {})
            valeur = dict(valeur) if isinstance(valeur, dict) else {}
            self.reglages = {
                "actif": bool(valeur.get("actif", False)),
                "corrections": valider_corrections(valeur.get("corrections")),
                "styles": self._styles(valeur.get("styles")),
            }
        return self.reglages

    @staticmethod
    def _styles(brut: Any) -> dict[str, str]:
        if not isinstance(brut, dict):
            return {}
        sortie = {}
        for programme, style in list(brut.items())[:100]:
            nom = str(programme).strip().lower()[:100]
            if nom and style in STYLES:
                sortie[nom] = str(style)
        return sortie

    async def regler(self, actif: bool | None = None, corrections: Any = None, styles: Any = None) -> dict[str, Any]:
        reglages = dict(await self.charger())
        if actif is not None:
            reglages["actif"] = bool(actif)
        if corrections is not None:
            reglages["corrections"] = valider_corrections(corrections)
        if styles is not None:
            reglages["styles"] = self._styles(styles)
        await self.pool.execute(
            "UPDATE etat_systeme SET valeur = $2::text::jsonb, maj_le = now() WHERE cle = $1",
            CLE,
            json.dumps(reglages, ensure_ascii=False),
        )
        self.reglages = reglages
        return reglages
