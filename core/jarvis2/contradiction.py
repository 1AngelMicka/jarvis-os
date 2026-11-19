"""Détection déterministe d'une contradiction (changement d'avis), sans IA.

Un nouveau fait **contredit** un souvenir vivant quand :
1. ils ont le même type, parmi `TYPES_COMPARABLES` ;
2. ils sont proches (cosinus du modèle actif ≥ `SEUIL_PROCHE`) ;
3. ils ne disent pas la même chose (mots significatifs différents : sinon c'est un doublon) ;
4. et le nouveau porte un marqueur de changement absent de l'ancien (« désormais », « finalement », « en fait »,
   « ne … plus », « j'ai changé d'avis », « au lieu de », « plutôt »…), ou les deux donnent une autre valeur à la
   même clé (« je préfère », « j'aime », « mon X est », « j'habite », « je travaille »).

Le souvenir contredit est alors remplacé (`memoire.remplacer`) : rien n'est effacé, l'historique reste.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from . import memoire
from .db import Executant
from .embeddings import Encodeur

TYPES_COMPARABLES = frozenset({"fait", "preference", "decision", "note"})
SEUIL_PROCHE = 0.7  # en dessous, deux phrases parlent d'autre chose
SEUIL_DOUBLON = 0.92  # au-dessus, sans contradiction : déjà connu (ignoré)
CANDIDATS = 5

# Texte normalisé : minuscules, sans accents, apostrophes droites, espaces simples
MARQUEURS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (libelle, re.compile(motif))
    for libelle, motif in (
        ("désormais", r"\bdesormais\b"),
        ("dorénavant", r"\bdorenavant\b"),
        ("à présent", r"\ba present\b"),
        ("finalement", r"\bfinalement\b"),
        ("en fait", r"\ben fait\b"),
        ("j'ai changé d'avis", r"\bj'ai change d'avis\b"),
        ("au lieu de", r"\bau lieu d"),
        ("plutôt", r"\bplutot\b"),
        ("ne … plus", r"\bn(?:e |')(?:[\w']+ ){0,3}plus\b"),
        ("plus jamais", r"\bplus (?:jamais|du tout)\b"),
    )
)
CLES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (cle, re.compile(motif))
    for cle, motif in (
        ("je préfère", r"\bje (?:ne )?(?:prefere|prefererais)\b(?P<v>.*)"),
        ("j'aime", r"\bj'(?:aime|adore)\b(?P<v>.*)"),
        ("mon", r"\b(?:mon|ma|mes) (?P<x>(?:[\w-]+ ){1,3}?)(?:est|sont|s'appelle|c'est)\b(?P<v>.*)"),
        ("j'habite", r"\b(?:j'habite|je vis|je demeure)\b(?P<v>.*)"),
        ("je travaille", r"\bje travaille\b(?P<v>.*)"),
    )
)
_MOTS_NEUTRES = frozenset({"finalement", "desormais", "dorenavant", "plutot", "fait", "present", "maintenant"})


def normaliser(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte.lower().replace("’", "'"))
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w'\s-]", " ", texte).split())


def _significatifs(texte: str) -> frozenset[str]:
    return frozenset(m for m in memoire.mots(texte) if m not in memoire.MOTS_VIDES and m not in _MOTS_NEUTRES)


def marqueur(texte: str) -> str | None:
    """Premier marqueur de changement trouvé dans le texte (normalisé ou non)."""
    n = normaliser(texte)
    return next((libelle for libelle, motif in MARQUEURS if motif.search(n)), None)


def cles(texte: str) -> dict[str, frozenset[str]]:
    """Clés « je préfère », « mon X est »… du texte et leur valeur (mots significatifs)."""
    n = normaliser(texte)
    trouvees: dict[str, frozenset[str]] = {}
    for cle, motif in CLES:
        m = motif.search(n)
        if m is None:
            continue
        nom = f"{cle} {m.group('x').strip()}" if "x" in motif.groupindex else cle
        trouvees[nom] = _significatifs(m.group("v"))
    return trouvees


def contredit(ancien: str, nouveau: str) -> str | None:
    """Raison pour laquelle `nouveau` contredit `ancien` (textes seuls), None sinon (doublon compris)."""
    if _significatifs(ancien) == _significatifs(nouveau):
        return None  # même chose dite autrement : doublon
    m = marqueur(nouveau)
    if m is not None and marqueur(ancien) != m:
        return f"marqueur de changement « {m} »"
    avant = cles(ancien)
    for cle, valeur in cles(nouveau).items():
        if cle in avant and avant[cle] != valeur:
            return f"même clé « {cle} », autre valeur"
    return None


@dataclass(frozen=True)
class Verdict:
    """Ce qu'il faut faire d'un nouveau fait : l'ajouter, remplacer `cible`, ou l'ignorer (doublon de `cible`)."""

    action: Literal["ajouter", "remplacer", "doublon"]
    cible: memoire.Souvenir | None = None
    similarite: float = 0.0
    raison: str = ""


async def examiner(
    conn: Executant,
    encodeur: Encodeur,
    contenu: str,
    type_: str,
    *,
    seuil_proche: float = SEUIL_PROCHE,
    seuil_doublon: float = SEUIL_DOUBLON,
) -> Verdict:
    """Compare un nouveau fait aux souvenirs vivants les plus proches (tous niveaux : tout reste sur le PC)."""
    proches = sorted(await memoire.rechercher(conn, encodeur, contenu, limite=CANDIDATS), key=lambda r: -r.similarite)
    if type_ in TYPES_COMPARABLES:
        for r in proches:
            if r.similarite < seuil_proche:
                break
            if r.souvenir.type != type_:
                continue
            raison = contredit(r.souvenir.contenu, contenu)
            if raison is not None:
                return Verdict("remplacer", r.souvenir, r.similarite, raison)
    if proches and proches[0].similarite >= seuil_doublon:
        return Verdict("doublon", proches[0].souvenir, proches[0].similarite, "déjà connu")
    return Verdict("ajouter")
