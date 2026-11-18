"""Filtre des secrets et données personnelles, appliqué à TOUT texte envoyé à un fournisseur externe.

Les éléments repérés sont remplacés par une étiquette (« [SECRET : clé d'API] », « [E-MAIL] »…) : le modèle
externe ne les voit jamais, la conversation stockée et les modèles locaux gardent le texte d'origine.
Les souvenirs `local_uniquement` sont déjà exclus en amont (voir memoire.py) ; ce filtre est la dernière barrière.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field


def _luhn(chiffres: str) -> bool:
    total, double = 0, False
    for c in reversed(chiffres):
        n = int(c) * (2 if double else 1)
        total += n - 9 if n > 9 else n
        double = not double
    return total % 10 == 0


def _carte(m: re.Match[str]) -> bool:
    chiffres = re.sub(r"\D", "", m.group(0))
    return 13 <= len(chiffres) <= 19 and _luhn(chiffres)


def _iban(m: re.Match[str]) -> bool:
    brut = re.sub(r"\s", "", m.group(0)).upper()
    deplace = brut[4:] + brut[:4]
    nombre = "".join(str(int(c, 36)) for c in deplace)
    return int(nombre) % 97 == 1


@dataclass(frozen=True)
class Regle:
    etiquette: str
    motif: re.Pattern[str]
    valider: Callable[[re.Match[str]], bool] | None = None


# Ordre important : les secrets d'abord (une clé peut contenir des suites de chiffres).
REGLES: tuple[Regle, ...] = (
    Regle(
        "SECRET : clé privée", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")
    ),
    Regle("SECRET : clé d'API", re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}")),
    Regle("SECRET : clé d'API", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    Regle("SECRET : jeton GitHub", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})")),
    Regle("SECRET : jeton Slack", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    Regle("SECRET : clé AWS", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    Regle("SECRET : jeton JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    Regle("SECRET : mot de passe", re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s:/@]+:[^\s@/]+@")),
    Regle(
        "SECRET : mot de passe",
        re.compile(r"(?i)\b(?:password|passwd|mot[ _]de[ _]passe|mdp|secret|token|api[_-]?key)\s*[:=]\s*\S{6,}"),
    ),
    Regle("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,7}(?:[ ]?[A-Z0-9]{1,3})?\b"), _iban),
    Regle("CARTE BANCAIRE", re.compile(r"\b(?:\d[ -]?){12,18}\d\b"), _carte),
    Regle(
        "N° SÉCURITÉ SOCIALE",
        re.compile(r"\b[12][ ]?\d{2}[ ]?(?:0[1-9]|1[0-2]|[2-9]\d)[ ]?(?:\d{2}|2[AB])[ ]?\d{3}[ ]?\d{3}[ ]?\d{2}\b"),
    ),
    Regle("E-MAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    Regle("TÉLÉPHONE", re.compile(r"(?<![\w+])(?:\+33[ .-]?[1-9]|0[1-9])(?:[ .-]?\d{2}){4}(?!\d)")),
    Regle("TÉLÉPHONE", re.compile(r"(?<![\w+])\+(?!33)[1-9]\d{0,2}(?:[ .-]?\d{2,4}){3,5}(?!\d)")),
)


@dataclass
class ResultatFiltre:
    texte: str
    masques: Counter[str] = field(default_factory=Counter)


def masquer(texte: str, regles: tuple[Regle, ...] = REGLES) -> ResultatFiltre:
    masques: Counter[str] = Counter()
    for regle in regles:

        def remplacer(m: re.Match[str], regle: Regle = regle) -> str:
            if regle.valider is not None and not regle.valider(m):
                return m.group(0)
            masques[regle.etiquette] += 1
            return f"[{regle.etiquette}]"

        texte = regle.motif.sub(remplacer, texte)
    return ResultatFiltre(texte, masques)
