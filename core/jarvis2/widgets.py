"""Widgets générés à la demande dans le HUD (phase 14, D 16) : météo, minuteur, liste, petit tableau…

Quand l'utilisateur demande quelque chose qui se lit mieux en carte qu'en phrases, le modèle termine sa réponse par
un ou plusieurs blocs `<widget titre="…">fragment HTML</widget>`. Comme le bloc d'actions (`pilotage.py`), le Core :
1. retire chaque bloc du texte (rien n'est affiché brut ni lu à voix haute) ;
2. valide le fragment contre des listes FERMÉES — balises, attributs (et la forme de leur valeur), classes (tokens de
   `interface/DESIGN.md`, feuille `widgets.css`) et adresses (vues internes `#vue` seulement). Le moindre écart
   (script, style en ligne, gestionnaire d'événement, adresse externe, svg, iframe, commentaire, classe inconnue…)
   écarte le widget ENTIER, avec sa raison : on ne « répare » pas un fragment piégé ;
3. renvoie un fragment RÉÉCRIT depuis l'arbre analysé (texte et valeurs échappés) : l'interface ne reçoit jamais les
   octets du modèle tels quels.
L'interface filtre encore le fragment par DOMPurify avec les mêmes listes (défense en profondeur), puis le construit
avec React, jamais avec `innerHTML`. Un widget n'agit pas : aucun script, aucun formulaire ; le minuteur est animé
par le code de l'interface (`data-minuteur`), pas par le fragment.

Épinglage : un widget peut être gardé dans le HUD (table `widgets_epingles`, migration 029) ; le fragment est validé
de nouveau à l'épinglage, et à la lecture (une liste fermée qui se resserre retire les anciens widgets non conformes).
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from uuid import UUID

from .db import Base
from .pilotage import VUES

NB_MAX_WIDGETS = 3  # par réponse
NB_MAX_EPINGLES = 12
TAILLE_MAX_FRAGMENT = 4000
TAILLE_MAX_TITRE = 60
NB_MAX_ELEMENTS = 200
PROFONDEUR_MAX = 8

# Balises permises (rien qui charge, exécute, dessine ou saisisse : ni script, style, img, svg, math, iframe, form…)
BALISES: frozenset[str] = frozenset(
    {
        "div", "section", "p", "span", "strong", "em", "small", "br",
        "h3", "h4", "ul", "ol", "li",
        "table", "thead", "tbody", "tr", "th", "td",
        "time", "meter", "progress", "a",
    }
)  # fmt: skip
VIDES: frozenset[str] = frozenset({"br"})

# Attribut → (balises où il est permis, ou None pour toutes ; forme exigée de la valeur)
_NOMBRE = re.compile(r"^-?\d{1,9}(?:\.\d{1,3})?$")
_LIBRE = re.compile(r"^[^<>\"`]{0,120}$")
ATTRIBUTS: dict[str, tuple[frozenset[str] | None, re.Pattern[str]]] = {
    "class": (None, re.compile(r"^[a-z0-9 -]{0,200}$")),
    "title": (None, _LIBRE),
    "aria-label": (None, _LIBRE),
    "href": (frozenset({"a"}), re.compile(r"^#[a-z][a-z0-9/-]{0,60}$")),
    "datetime": (frozenset({"time"}), re.compile(r"^[0-9T:+\-Z. ]{4,40}$")),
    "data-minuteur": (frozenset({"time"}), re.compile(r"^[1-9]\d{0,5}$")),  # secondes (≤ 999 999)
    "value": (frozenset({"meter", "progress"}), _NOMBRE),
    "min": (frozenset({"meter"}), _NOMBRE),
    "max": (frozenset({"meter", "progress"}), _NOMBRE),
    "low": (frozenset({"meter"}), _NOMBRE),
    "high": (frozenset({"meter"}), _NOMBRE),
    "colspan": (frozenset({"td", "th"}), re.compile(r"^[1-9]$")),
}

# Classes permises : chacune est définie dans `interface/src/styles/widgets.css` avec les tokens de DESIGN.md
CLASSES: frozenset[str] = frozenset(
    {
        "w-carte", "w-grille", "w-ligne", "w-pile",
        "w-titre", "w-valeur", "w-geant", "w-libelle", "w-unite", "w-icone", "w-mono", "w-discret",
        "w-accent", "w-succes", "w-attention", "w-danger",
        "w-liste", "w-coche", "w-minuteur", "w-jauge",
    }
)  # fmt: skip

_BLOC = re.compile(r"<widget(?=[\s>])([^>]{0,300})>(.*?)(</widget\s*>|$)", re.IGNORECASE | re.DOTALL)
_TITRE = re.compile(r"""titre\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)

CONSIGNES = """Widgets : SEULEMENT quand une carte se lit mieux que des phrases (météo, minuteur, liste de courses, \
petit tableau, chiffres clés), ajoute à la fin de ta réponse un bloc <widget titre="<titre court>">…</widget> \
(3 au plus) contenant un fragment HTML simple. Balises : div section p span strong em small br h3 h4 ul ol li table \
thead tbody tr th td time meter progress a. Attributs : class, title, aria-label ; href="#<vue>" (vues : {vues}) \
sur a ; datetime sur time ; data-minuteur="<secondes>" sur time pour un minuteur ; value min max low high sur \
meter et progress ; colspan sur td/th. Classes : {classes}. Rien d'autre : aucun script, aucun style, aucun \
gestionnaire d'événement, aucune image, aucune adresse externe — un widget non conforme est écarté entier. \
Exemple : <widget titre="Thé"><div class="w-carte"><p class="w-libelle">Infusion</p>\
<time class="w-minuteur w-geant" data-minuteur="240">4:00</time></div></widget>. N'écris jamais de données \
inventées (météo, cours…) : si tu ne les connais pas, dis-le."""


def consignes() -> str:
    return CONSIGNES.format(vues=" ".join(VUES), classes=" ".join(sorted(CLASSES)))


class FragmentRefuse(ValueError):
    """Raison en français (jamais le contenu refusé), affichable telle quelle."""


class _Analyse(HTMLParser):
    """Analyse stricte : lève `FragmentRefuse` au premier écart, sinon réécrit le fragment dans `sortie`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sortie: list[str] = []
        self.pile: list[str] = []
        self.elements = 0

    # --- Balises ------------------------------------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._ouvrir(tag, attrs, fermee=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._ouvrir(tag, attrs, fermee=True)

    def _ouvrir(self, tag: str, attrs: list[tuple[str, str | None]], fermee: bool) -> None:
        if tag not in BALISES:
            raise FragmentRefuse(f"balise non permise : <{tag[:20]}>")
        self.elements += 1
        if self.elements > NB_MAX_ELEMENTS:
            raise FragmentRefuse(f"plus de {NB_MAX_ELEMENTS} éléments")
        morceaux = [tag]
        vus: set[str] = set()
        for nom, valeur in attrs:
            if nom in vus:
                raise FragmentRefuse(f"attribut répété : {nom[:30]}")
            vus.add(nom)
            regle = ATTRIBUTS.get(nom)
            if regle is None:  # on*, style, src, srcset, xlink:href, formaction… : tout ce qui n'est pas listé
                raise FragmentRefuse(f"attribut non permis : {nom[:30]}")
            balises, forme = regle
            if balises is not None and tag not in balises:
                raise FragmentRefuse(f"attribut {nom} non permis sur <{tag}>")
            v = (valeur or "").strip()
            if not forme.match(v):
                raise FragmentRefuse(f"valeur refusée pour {nom}")
            if nom == "class":
                inconnues = [c for c in v.split() if c not in CLASSES]
                if inconnues:
                    raise FragmentRefuse(f"classe inconnue : {inconnues[0][:30]}")
                v = " ".join(v.split())
            elif nom == "href":
                vue = v[1:].split("/", 1)[0]
                if vue not in VUES:  # seules les vues internes : aucune adresse externe, aucun « javascript: »
                    raise FragmentRefuse("adresse non permise (seulement #vue de JARVIS)")
            morceaux.append(f'{nom}="{html.escape(v, quote=True)}"')
        self.sortie.append(f"<{' '.join(morceaux)}>")
        if tag in VIDES:
            return
        if fermee:  # <span/> : fermé tout de suite
            self.sortie.append(f"</{tag}>")
            return
        self.pile.append(tag)
        if len(self.pile) > PROFONDEUR_MAX:
            raise FragmentRefuse(f"imbrication de plus de {PROFONDEUR_MAX} niveaux")

    def handle_endtag(self, tag: str) -> None:
        if tag in VIDES:
            return
        if not self.pile or self.pile[-1] != tag:
            raise FragmentRefuse("balises mal imbriquées")
        self.pile.pop()
        self.sortie.append(f"</{tag}>")

    # --- Contenus -----------------------------------------------------------------------------------------

    def handle_data(self, data: str) -> None:
        self.sortie.append(html.escape(data, quote=False))

    def handle_comment(self, data: str) -> None:
        raise FragmentRefuse("commentaire non permis")

    def handle_decl(self, decl: str) -> None:
        raise FragmentRefuse("déclaration non permise")

    def handle_pi(self, data: str) -> None:
        raise FragmentRefuse("instruction non permise")

    def unknown_decl(self, data: str) -> None:
        raise FragmentRefuse("section CDATA non permise")


def valider_fragment(fragment: str) -> str:
    """Fragment réécrit (sûr, canonique) ou `FragmentRefuse`."""
    if not isinstance(fragment, str):
        raise FragmentRefuse("fragment : texte attendu")
    brut = fragment.strip()
    if not brut:
        raise FragmentRefuse("fragment vide")
    if len(brut) > TAILLE_MAX_FRAGMENT:
        raise FragmentRefuse(f"fragment de plus de {TAILLE_MAX_FRAGMENT} caractères")
    if "\x00" in brut:
        raise FragmentRefuse("caractère nul")
    analyse = _Analyse()
    analyse.feed(brut)
    analyse.close()
    # Une balise tronquée en fin de fragment (« <img src=x onerror=… ») n'est jamais rendue en balise : HTMLParser la
    # rend en texte (échappé ci-dessus) ou l'ignore.
    if analyse.pile:
        raise FragmentRefuse("balise non fermée")
    if analyse.elements == 0:
        raise FragmentRefuse("fragment sans balise")
    propre = "".join(analyse.sortie).strip()
    if len(propre) > 2 * TAILLE_MAX_FRAGMENT:  # échappements compris (colonne `html` de la migration 029)
        raise FragmentRefuse("fragment trop long une fois réécrit")
    return propre


def _titre(valeur: str) -> str:
    t = " ".join(html.unescape(valeur).split())
    t = re.sub(r"[<>]", "", t)
    if not t:
        return "Widget"
    return t if len(t) <= TAILLE_MAX_TITRE else f"{t[: TAILLE_MAX_TITRE - 1]}…"


def empreinte(titre: str, fragment: str) -> str:
    return hashlib.sha256(f"{titre}\n{fragment}".encode()).hexdigest()[:16]


def widget(titre: str, fragment: str) -> dict[str, str]:
    """Widget validé : {id (empreinte), titre, html}. `FragmentRefuse` si le fragment est refusé."""
    propre_titre = _titre(titre)
    propre = valider_fragment(fragment)
    return {"id": empreinte(propre_titre, propre), "titre": propre_titre, "html": propre}


@dataclass
class Extraction:
    texte: str
    widgets: list[dict[str, str]]
    ecartes: list[str]
    bloc: bool

    def meta(self) -> dict[str, Any]:
        if not self.bloc:
            return {}
        return {"widgets": self.widgets, **({"widgets_ecartes": self.ecartes} if self.ecartes else {})}


def retirer_blocs(texte: str) -> tuple[str, list[tuple[str, str, bool]]]:
    """(texte sans bloc `<widget>`, [(titre, fragment, fermé)]). Un bloc non fermé court jusqu'à la fin."""
    blocs: list[tuple[str, str, bool]] = []
    for m in _BLOC.finditer(texte):
        t = _TITRE.search(m.group(1))
        blocs.append(((t.group(1) or t.group(2) or "") if t else "", m.group(2), bool(m.group(3))))
    if not blocs:
        return texte, []
    propre = _BLOC.sub("", texte)
    propre = re.sub(r"```(?:html)?\s*```", "", propre)
    return propre.rstrip(), blocs


def extraire(texte: str) -> Extraction:
    propre, blocs = retirer_blocs(texte)
    if not blocs:
        return Extraction(texte, [], [], False)
    widgets: list[dict[str, str]] = []
    ecartes: list[str] = []
    for titre, fragment, ferme in blocs:
        if len(widgets) >= NB_MAX_WIDGETS:
            ecartes.append(f"plus de {NB_MAX_WIDGETS} widgets")
            break
        if not ferme:
            ecartes.append("bloc <widget> non fermé")
            continue
        corps = re.sub(r"^\s*```(?:html)?|```\s*$", "", fragment.strip()).strip()
        try:
            w = widget(titre, corps)
        except FragmentRefuse as exc:
            ecartes.append(f"« {_titre(titre)} » écarté : {exc}")
            continue
        if all(x["id"] != w["id"] for x in widgets):
            widgets.append(w)
    return Extraction(propre, widgets, ecartes, True)


# --- Widgets épinglés dans le HUD ------------------------------------------------------------------------------


class ErreurWidget(ValueError):
    """Message en français, affichable tel quel."""


def _carte(ligne: Any) -> dict[str, Any]:
    cree: datetime = ligne["cree_le"]
    return {
        "id": str(ligne["id"]),
        "empreinte": ligne["empreinte"],
        "titre": ligne["titre"],
        "html": ligne["html"],
        "cree_le": cree.isoformat(),
    }


async def lister(base: Base) -> list[dict[str, Any]]:
    """Widgets épinglés, du plus ancien au plus récent ; un fragment devenu non conforme n'est plus servi."""
    lignes = await base.fetch("SELECT id, empreinte, titre, html, cree_le FROM widgets_epingles ORDER BY cree_le, id")
    cartes: list[dict[str, Any]] = []
    for ligne in lignes:
        try:
            valider_fragment(ligne["html"])
        except FragmentRefuse:
            continue
        cartes.append(_carte(ligne))
    return cartes


async def epingler(base: Base, titre: str, fragment: str) -> tuple[dict[str, Any], bool]:
    """(widget épinglé, nouveau). Le fragment est validé de nouveau : l'interface ne fait jamais foi."""
    try:
        w = widget(titre, fragment)
    except FragmentRefuse as exc:
        raise ErreurWidget(f"Widget refusé : {exc}") from exc
    existant = await base.fetchrow(
        "SELECT id, empreinte, titre, html, cree_le FROM widgets_epingles WHERE empreinte = $1", w["id"]
    )
    if existant is not None:
        return _carte(existant), False
    if (await base.fetchval("SELECT count(*) FROM widgets_epingles")) >= NB_MAX_EPINGLES:
        raise ErreurWidget(f"{NB_MAX_EPINGLES} widgets épinglés au plus : retirez-en un d'abord")
    ligne = await base.fetchrow(
        "INSERT INTO widgets_epingles (empreinte, titre, html) VALUES ($1, $2, $3)"
        " RETURNING id, empreinte, titre, html, cree_le",
        w["id"],
        w["titre"],
        w["html"],
    )
    return _carte(ligne), True


async def retirer(base: Base, ident: UUID) -> str | None:
    """Titre du widget retiré, ou None s'il n'existait pas."""
    titre = await base.fetchval("SELECT titre FROM widgets_epingles WHERE id = $1", ident)
    if titre is None:
        return None
    await base.execute("DELETE FROM widgets_epingles WHERE id = $1", ident)
    return str(titre)
