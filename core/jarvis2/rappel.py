"""Porte de rappel : faut-il chercher dans la mémoire pour ce message ? Déterministe, sans IA.

Pas de recherche pour un message vide ou très court, une commande « / », une politesse ou un acquittement seuls
(« merci », « ok », « bonjour JARVIS ! »). Recherche dès que le message évoque la mémoire, pose une question ou
parle de l'utilisateur à la première personne ; et, dans le doute, recherche (mieux vaut un souvenir de trop qu'un
oubli). La porte ne touche ni au noyau ni aux blocs, toujours injectés : seule la recherche des souvenirs (et des
domaines de connaissance) est sautée.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

LONGUEUR_MIN = 4  # lettres et chiffres en dessous desquels un message ne mérite pas de recherche

# Raisons, dans l'ordre où elles sont examinées (source unique : `decider` et « Où partent mes données »)
SANS_RECHERCHE = {
    "vide": "message vide",
    "commande": "commande",
    "politesse": "politesse ou acquittement",
    "court": "message très court",
}
AVEC_RECHERCHE = {
    "memoire": "mention de la mémoire",
    "question": "question",
    "personnel": "première personne",
    "defaut": "par défaut",
}

POLITESSES = frozenset(
    {
        "bonjour",
        "bonsoir",
        "salut",
        "coucou",
        "hello",
        "hey",
        "yo",
        "merci",
        "merci beaucoup",
        "merci bien",
        "mille mercis",
        "ok",
        "okay",
        "oki",
        "d'accord",
        "dac",
        "entendu",
        "compris",
        "bien recu",
        "ca marche",
        "parfait",
        "super",
        "genial",
        "top",
        "cool",
        "nickel",
        "excellent",
        "tres bien",
        "bien",
        "oui",
        "non",
        "ouais",
        "yes",
        "bonne nuit",
        "bonne journee",
        "bonne soiree",
        "au revoir",
        "a plus",
        "a bientot",
        "a demain",
        "bravo",
        "de rien",
        "pas de souci",
        "pas de probleme",
        "c'est bon",
        "ca va",
    }
)
_RELANCES = frozenset({"jarvis", "stp", "svp", "beaucoup", "encore", "alors", "bon", "ah", "oh", "eh", "bah", "et"})

_MEMOIRE = re.compile(
    r"\b(?:souviens|souvenir|souvenirs|rappelles?|rappeler|memoire|memorise|retiens|oublie|"
    r"je t'ai (?:dit|parle|explique)|on (?:avait|a) (?:dit|parle|vu)|la derniere fois|tu sais|"
    r"qu'est-ce que tu sais|que sais-tu|tu connais)\b"
)
_INTERROGATIF = re.compile(
    r"^(?:quel(?:le)?s?|pourquoi|comment|combien|quand|ou|qui|que|quoi|qu'|est-ce|peux-tu|pourrais-tu|"
    r"sais-tu|as-tu|y a-t-il|dois-je|faut-il)\b"
)
_PREMIERE_PERSONNE = re.compile(r"(?:^|[\s,(])(?:(?:je|moi|mon|ma|mes|me|nous|notre|nos)\b|[jm]')")


@dataclass(frozen=True)
class Porte:
    rappeler: bool
    raison: str


def _normaliser(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte.lower().replace("’", "'"))
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return " ".join(texte.split())


def _politesse(n: str) -> bool:
    """Le message n'est fait que de politesses et d'acquittements (« merci jarvis, parfait ! »)."""
    morceaux = [m.strip() for m in re.split(r"[,.;:!?…\n]+", n) if m.strip()]
    if not morceaux:
        return False
    for morceau in morceaux:
        mots = [m for m in re.findall(r"[\w']+", morceau) if m not in _RELANCES]
        if mots and " ".join(mots) not in POLITESSES:
            return False
    return True


def decider(texte: str) -> Porte:
    """Chercher ou non dans les souvenirs pour ce message, et pourquoi."""
    brut = (texte or "").strip()
    if not brut:
        return Porte(False, SANS_RECHERCHE["vide"])
    if brut.startswith("/"):
        return Porte(False, SANS_RECHERCHE["commande"])
    n = _normaliser(brut)
    if _MEMOIRE.search(n):
        return Porte(True, AVEC_RECHERCHE["memoire"])
    if _politesse(n):
        return Porte(False, SANS_RECHERCHE["politesse"])
    if "?" in n or _INTERROGATIF.match(n):
        return Porte(True, AVEC_RECHERCHE["question"])
    if _PREMIERE_PERSONNE.search(n):
        return Porte(True, AVEC_RECHERCHE["personnel"])
    utiles = re.findall(r"\w+", n)
    if len("".join(utiles)) < LONGUEUR_MIN:
        return Porte(False, SANS_RECHERCHE["court"])
    return Porte(True, AVEC_RECHERCHE["defaut"])


def _decrire() -> str:
    exemples = ", ".join(f"« {p} »" for p in ("bonjour", "merci", "ok", "parfait") if p in POLITESSES)
    sans = {**SANS_RECHERCHE, "politesse": f"{SANS_RECHERCHE['politesse']} seuls ({exemples}…)"}
    sans["court"] = f"{SANS_RECHERCHE['court']} (moins de {LONGUEUR_MIN} lettres)"
    avec = {**AVEC_RECHERCHE, "defaut": f"{AVEC_RECHERCHE['defaut']} (dans le doute)"}
    return (
        "Porte de rappel, sans IA. Pas de recherche dans les souvenirs : "
        + " ; ".join(sans.values())
        + ". Recherche : "
        + " ; ".join(avec.values())
        + ". Le noyau et les blocs restent toujours injectés (seuls les « public » vers une IA externe)."
    )


DESCRIPTION = _decrire()
