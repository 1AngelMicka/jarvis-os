"""Filtre des secrets et données personnelles, appliqué à TOUT texte qui sort du coffre local.

Les éléments repérés sont remplacés par une étiquette lisible (« [SECRET : clé OpenAI] », « [E-MAIL] »…) :
- avant le contexte envoyé à un fournisseur externe (`masquer`, toutes les règles) ;
- avant le journal d'audit et le journal applicatif (`masquer_secrets`, secrets seulement : un e-mail ou un numéro
  de téléphone y reste lisible, ce sont des journaux locaux).
La conversation stockée et les modèles locaux gardent le texte d'origine. Les souvenirs `local_uniquement` sont
déjà exclus en amont (voir memoire.py) ; ce filtre est la dernière barrière.

Épargnés volontairement : les empreintes git (40 ou 64 caractères hexadécimaux) et les UUID écrits seuls, sauf
s'ils suivent un mot-clé de secret (« token : … »).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any


def _luhn(chiffres: str) -> bool:
    total, double = 0, False
    for c in reversed(chiffres):
        n = int(c) * (2 if double else 1)
        total += n - 9 if n > 9 else n
        double = not double
    return total % 10 == 0


# Préfixes d'émetteurs (IIN) et longueurs : Visa, Mastercard, American Express, Discover, JCB, Diners, UnionPay,
# Maestro. Un numéro quelconque qui passe Luhn par hasard (1 sur 10) n'a en général pas ces préfixes.
_EMETTEURS = re.compile(
    r"^(?:4\d{12}(?:\d{3}){0,2}"
    r"|(?:5[1-5]\d{2}|2(?:2[2-9]\d|[3-6]\d{2}|7[01]\d|720))\d{12}"
    r"|3[47]\d{13}"
    r"|(?:6011|65\d{2}|64[4-9]\d)\d{12,15}"
    r"|35(?:2[89]|[3-8]\d)\d{12,15}"
    r"|3(?:0[0-5]|[68]\d)\d{10,15}"
    r"|62\d{14,17}"
    r"|(?:50|5[6-9]|6[0-9])\d{10,17})$"
)


def _carte(m: re.Match[str]) -> bool:
    brut = m.group(0)
    if len(set(re.findall(r"\D", brut))) > 1:  # « 1234-5678 9012 » : séparateurs mélangés, pas une carte
        return False
    chiffres = re.sub(r"\D", "", brut)
    return (
        13 <= len(chiffres) <= 19
        and len(set(chiffres)) > 1
        and _EMETTEURS.match(chiffres) is not None
        and _luhn(chiffres)
    )


def _iban(m: re.Match[str]) -> bool:
    brut = re.sub(r"\s", "", m.group(0)).upper()
    deplace = brut[4:] + brut[:4]
    nombre = "".join(str(int(c, 36)) for c in deplace)
    return int(nombre) % 97 == 1


def _secret_aws(m: re.Match[str]) -> bool:
    # Une clé secrète AWS mélange lettres et chiffres en base 64 ; 40 caractères hexadécimaux = une empreinte git.
    return re.fullmatch(r"[0-9a-fA-F]{40}", m.group("v")) is None


@dataclass(frozen=True)
class Regle:
    etiquette: str
    motif: re.Pattern[str]
    valider: Callable[[re.Match[str]], bool] | None = None
    secret: bool = True  # False : donnée personnelle (masquée pour l'extérieur, gardée dans les journaux locaux)


# Ordre important : les formes précises d'abord (une clé Anthropic commence aussi par « sk- »), les secrets avant
# les données personnelles (une clé peut contenir des suites de chiffres).
# Un groupe nommé « v » limite le remplacement à la valeur : « password=[SECRET : mot de passe] » reste lisible.
REGLES: tuple[Regle, ...] = (
    Regle(
        "SECRET : clé privée", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")
    ),
    Regle("SECRET : clé Anthropic", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}")),
    Regle("SECRET : clé OpenAI", re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}")),
    Regle("SECRET : clé Stripe", re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}|\bwhsec_[A-Za-z0-9]{24,}")),
    Regle("SECRET : clé d'API", re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}")),
    Regle("SECRET : clé Google", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    Regle("SECRET : jeton GitHub", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})")),
    Regle("SECRET : jeton Slack", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    Regle("SECRET : clé AWS", re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b")),
    Regle(
        "SECRET : clé AWS",
        re.compile(
            r"(?i)\baws[\w ]{0,20}?(?:secret|key)[\w ]{0,20}?[\"']?\s*[:=]\s*[\"']?"
            r"(?P<v>[A-Za-z0-9/+]{40})(?![A-Za-z0-9/+=])"
        ),
        _secret_aws,
    ),
    Regle("SECRET : jeton JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    Regle("SECRET : jeton", re.compile(r"(?i)\b(?:bearer|basic|token)\s+(?P<v>[A-Za-z0-9._~+/\-]{16,}=*)")),
    Regle("SECRET : identifiants", re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://(?P<v>[^\s:/@]+:(?!\*{3}@)[^\s@/]+)@")),
    Regle(
        "SECRET : mot de passe",
        re.compile(
            r"(?i)\b(?:password|passwd|pwd|mot[ _]de[ _]passe|mdp|secret|token|api[_-]?key|client[_-]?secret)"
            r"[\"']?\s*[:=]\s*[\"']?(?P<v>[^\s\"']{6,})"
        ),
    ),
    Regle(
        "CODE À USAGE UNIQUE",
        re.compile(
            r"(?i)\b(?:code|otp|pin|2fa|mfa)"
            r"(?:\s+(?:de\s+)?(?:v[ée]rification|confirmation|s[ée]curit[ée]|connexion|validation"
            r"|[àa]\s+usage\s+unique|unique|temporaire|verification|sms|otp|2fa))?"
            r"\s*(?:[:=]|est|is)\s*(?P<v>\d{3}[ -]\d{3}|\d{4,8})\b"
        ),
    ),
    Regle(
        "CODE À USAGE UNIQUE",
        re.compile(r"(?i)\b(?P<v>\d{4,8})\s+(?:est\s+votre\s+code|is\s+your\s+(?:verification\s+|security\s+)?code)"),
    ),
    Regle("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,7}(?:[ ]?[A-Z0-9]{1,3})?\b"), _iban),
    Regle("CARTE BANCAIRE", re.compile(r"(?<![\w-])(?:\d[ -]?){12,18}\d(?![\w-])"), _carte),
    Regle(
        "N° SÉCURITÉ SOCIALE",
        re.compile(r"\b[12][ ]?\d{2}[ ]?(?:0[1-9]|1[0-2]|[2-9]\d)[ ]?(?:\d{2}|2[AB])[ ]?\d{3}[ ]?\d{3}[ ]?\d{2}\b"),
        secret=False,
    ),
    Regle("E-MAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), secret=False),
    Regle("TÉLÉPHONE", re.compile(r"(?<![\w+-])(?:\+33[ .-]?[1-9]|0[1-9])(?:[ .-]?\d{2}){4}(?![\w-])"), secret=False),
    Regle("TÉLÉPHONE", re.compile(r"(?<![\w+-])\+(?!33)[1-9]\d{0,2}(?:[ .-]?\d{2,4}){3,5}(?![\w-])"), secret=False),
)
REGLES_SECRETS: tuple[Regle, ...] = tuple(r for r in REGLES if r.secret)

# Jetons épargnés : UUID et empreintes git (SHA-1 / SHA-256) écrits seuls.
_PROTEGES = re.compile(
    r"(?<![\w-])(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|[0-9a-fA-F]{64}|[0-9a-fA-F]{40})(?![\w-])"
)
# Étiquettes déjà posées : une règle suivante ne doit pas les reprendre (« [SECRET : jeton] » ≠ « secret: jeton »).
_ETIQUETTES = re.compile(r"\[(?:SECRET :|CODE À|IBAN|CARTE|N° S|E-MAIL|TÉLÉPHONE)[^\]\n]*\]")


@dataclass
class ResultatFiltre:
    texte: str
    masques: Counter[str] = field(default_factory=Counter)


def _appliquer(regle: Regle, texte: str, masques: Counter[str]) -> str:
    proteges = [m.span() for m in _PROTEGES.finditer(texte)]
    poses = [m.span() for m in _ETIQUETTES.finditer(texte)]

    def remplacer(m: re.Match[str]) -> str:
        debut, fin = m.span()
        if any(a <= debut and fin <= b for a, b in proteges) or any(debut < b and a < fin for a, b in poses):
            return m.group(0)
        if regle.valider is not None and not regle.valider(m):
            return m.group(0)
        masques[regle.etiquette] += 1
        etiquette = f"[{regle.etiquette}]"
        if "v" not in regle.motif.groupindex:
            return etiquette
        a, b = m.span("v")
        return texte[debut:a] + etiquette + texte[b:fin]

    return regle.motif.sub(remplacer, texte)


def masquer(texte: str, regles: tuple[Regle, ...] = REGLES) -> ResultatFiltre:
    masques: Counter[str] = Counter()
    for regle in regles:
        texte = _appliquer(regle, texte, masques)
    return ResultatFiltre(texte, masques)


def masquer_secrets(texte: str) -> str:
    """Secrets seulement (clés, jetons, mots de passe, codes, cartes, IBAN) : pour les journaux locaux."""
    return masquer(texte, REGLES_SECRETS).texte


def masquer_valeurs(valeur: Any) -> Any:
    """Masque les secrets dans toutes les chaînes d'une structure JSON (dictionnaires, listes)."""
    if isinstance(valeur, str):
        return masquer_secrets(valeur)
    if isinstance(valeur, Mapping):
        return {cle: masquer_valeurs(v) for cle, v in valeur.items()}
    if isinstance(valeur, list | tuple):
        return [masquer_valeurs(v) for v in valeur]
    return valeur
