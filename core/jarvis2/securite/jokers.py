"""Motifs à jokers des commandes rapides et des règles de protection.

Un motif est une phrase en clair, comparée sans accents, sans majuscules ni ponctuation :
- `*` : n'importe quel texte (même vide) ;
- `{nom}` : un morceau de texte capturé (au moins un caractère), réutilisable dans les paramètres de l'action.
Jamais d'expression régulière fournie par l'utilisateur : le motif est traduit ici, chaque partie littérale échappée.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

NB_MAX_CAPTURES = 5
NB_MIN_LITTERAUX = 2  # un motif doit contenir au moins deux lettres ou chiffres : « * » seul capterait tout
PONCTUATION_BORD = " \t.,;:!?«»\"'"
_CAPTURE = re.compile(r"\{([^{}]*)\}")
_NOM_CAPTURE = re.compile(r"^[a-z_][a-z0-9_]{0,30}$")


class ErreurMotif(ValueError):
    """Message en français, affichable tel quel."""


def _avec_positions(texte: str) -> tuple[str, list[int]]:
    """Texte normalisé et, pour chacun de ses caractères, sa position dans le texte d'origine."""
    sortie: list[str] = []
    positions: list[int] = []
    for i, c in enumerate(texte):
        base = "".join(x for x in unicodedata.normalize("NFKD", c.lower()) if not unicodedata.combining(x))
        base = base.replace("œ", "oe").replace("æ", "ae")
        for x in base or " ":
            garde = x if ("0" <= x <= "9" or "a" <= x <= "z") else " "
            if garde == " " and (not sortie or sortie[-1] == " "):
                continue
            sortie.append(garde)
            positions.append(i)
    if sortie and sortie[-1] == " ":
        sortie.pop()
        positions.pop()
    return "".join(sortie), positions


def normaliser(texte: str) -> str:
    """Sans majuscules, accents ni ponctuation : « Ouvre les Missions ! » → « ouvre les missions »."""
    return _avec_positions(texte)[0]


def _normaliser_motif(motif: str) -> str:
    """Comme `normaliser`, mais garde `*` et `{nom}` (le nom de capture n'est pas modifié)."""
    morceaux: list[str] = []
    position = 0
    for m in _CAPTURE.finditer(motif):
        morceaux.append(_litteral(motif[position : m.start()]))
        morceaux.append("{" + m.group(1).strip() + "}")
        position = m.end()
    morceaux.append(_litteral(motif[position:]))
    return " ".join(" ".join(morceaux).split())


def _litteral(texte: str) -> str:
    return " * ".join(normaliser(p) for p in texte.split("*")).strip() if "*" in texte else normaliser(texte)


@dataclass(frozen=True)
class Motif:
    source: str
    normalise: str
    regex: re.Pattern[str]
    captures: tuple[str, ...]
    specificite: int  # nombre de caractères littéraux : à priorité égale, le motif le plus précis l'emporte

    def correspond(self, texte: str, contient: bool = False) -> dict[str, str] | None:
        """Captures si le texte (entier, ou seulement une partie si `contient`) correspond ; sinon None."""
        cible, positions = _avec_positions(texte)
        m = self.regex.search(cible) if contient else self.regex.fullmatch(cible)
        if m is None:
            return None
        # Les captures reprennent le texte d'origine (accents, majuscules) : « Recherche sur l'Été » → « l'Été »
        return {
            nom: texte[positions[m.start(nom)] : positions[m.end(nom) - 1] + 1].strip(PONCTUATION_BORD)
            for nom in self.captures
        }


def compiler(motif: str) -> Motif:
    source = motif.strip()
    if not source:
        raise ErreurMotif("Motif vide")
    if len(source) > 200:
        raise ErreurMotif("Motif trop long (200 caractères au plus)")
    if source.count("{") != source.count("}"):
        raise ErreurMotif("Accolades non fermées : une capture s'écrit {nom}")
    normalise = _normaliser_motif(source)
    parties: list[str] = []
    captures: list[str] = []
    litteraux = 0
    for jeton in re.split(r"(\*|\{[^{}]*\})", normalise):
        if not jeton:
            continue
        if jeton == "*":
            parties.append(".*?")
        elif jeton.startswith("{"):
            nom = jeton[1:-1]
            if not _NOM_CAPTURE.match(nom):
                raise ErreurMotif(f"Nom de capture invalide : « {nom} » (lettres minuscules, chiffres, _)")
            if nom in captures:
                raise ErreurMotif(f"Capture en double : « {nom} »")
            captures.append(nom)
            parties.append(f"(?P<{nom}>.+?)")
        else:
            litteraux += sum(c.isalnum() for c in jeton)
            parties.append(re.escape(jeton))
    if len(captures) > NB_MAX_CAPTURES:
        raise ErreurMotif(f"{NB_MAX_CAPTURES} captures au plus")
    if litteraux < NB_MIN_LITTERAUX:
        raise ErreurMotif("Motif trop large : il doit contenir au moins quelques lettres")
    # Les espaces autour d'un joker sont facultatifs (« ouvre * missions » accepte « ouvre missions »)
    expression = "".join(parties).replace(r"\ ", " ")
    expression = re.sub(r" ?(\.\*\?) ?", r" ?\1 ?", expression)
    return Motif(source, normalise, re.compile(expression), tuple(captures), litteraux)


def remplacer(valeur: object, captures: dict[str, str]) -> object:
    """Remplace `{nom}` dans les chaînes (récursivement) ; une capture inconnue est une erreur."""
    if isinstance(valeur, str):

        def un(m: re.Match[str]) -> str:
            nom = m.group(1).strip()
            if nom not in captures:
                raise ErreurMotif(f"Paramètre « {{{nom}}} » : aucune capture de ce nom dans le motif")
            return captures[nom]

        return _CAPTURE.sub(un, valeur)
    if isinstance(valeur, dict):
        return {k: remplacer(v, captures) for k, v in valeur.items()}
    if isinstance(valeur, list):
        return [remplacer(v, captures) for v in valeur]
    return valeur
