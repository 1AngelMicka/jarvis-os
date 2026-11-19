"""Protocole `jarvis://` : liens ouverts depuis le bureau (raccourci, gadget, autre application, navigateur).

Liste blanche STRICTE, vérifiée deux fois : par l'application de bureau (Tauri) avant de montrer la fenêtre, puis
ici, par le Core, avant que l'interface ne fasse quoi que ce soit. Un lien ne fait JAMAIS plus qu'une action
d'interface 🟢 (ouvrir une vue, écouter, proposer une capture d'écran, préremplir un texte) :

- rien n'est exécuté, envoyé à l'IA ni approuvé par un lien ; aucun paramètre inconnu n'est toléré ;
- `dire` ne fait que PRÉREMPLIR la zone de saisie : le texte vient de l'extérieur, il reste une donnée non fiable
  que l'utilisateur relit et envoie lui-même ;
- jamais de déverrouillage (session du PC, arrêt d'urgence) : aucune action de ce genre n'existe ici.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit
from uuid import UUID

from .pilotage import VUES

SCHEMA = "jarvis"
LONGUEUR_MAX = 2048
TEXTE_MAX = 2000

# action → paramètres permis (et rien d'autre)
ACTIONS: dict[str, frozenset[str]] = {
    "ouvrir": frozenset({"vue"}),  # jarvis://ouvrir/memoire  ou  jarvis://ouvrir?vue=memoire
    "conversation": frozenset({"id"}),  # jarvis://conversation/<uuid>
    "nouvelle": frozenset(),  # nouvelle conversation
    "ecouter": frozenset(),  # ouvre le micro (raccourci global « voix »)
    "ecran": frozenset(),  # propose « regarde mon écran » (la capture reste soumise à ses propres règles)
    "dire": frozenset({"texte"}),  # préremplit la zone de saisie, sans l'envoyer
    "decision": frozenset({"id"}),  # ouvre l'appel de décision d'une demande en attente
    "gadget": frozenset(),  # vue compacte du gadget de bureau
}
LIBELLES = {
    "ouvrir": "Ouvrir une vue",
    "conversation": "Ouvrir une conversation",
    "nouvelle": "Nouvelle conversation",
    "ecouter": "Écouter (micro)",
    "ecran": "Regarder l'écran",
    "dire": "Préremplir un message",
    "decision": "Décider d'une demande",
    "gadget": "Gadget de bureau",
}
_ACTION = re.compile(r"^[a-z]{2,20}$")


class ErreurLien(ValueError):
    """Lien refusé : message en français, affichable tel quel."""


@dataclass(frozen=True, slots=True)
class LienJarvis:
    action: str
    parametres: dict[str, str] = field(default_factory=dict)

    @property
    def non_fiable(self) -> bool:
        """Le lien porte un texte venu de l'extérieur (à relire, jamais à suivre comme une consigne)."""
        return self.action == "dire"

    def en_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "parametres": self.parametres,
            "libelle": LIBELLES[self.action],
            "non_fiable": self.non_fiable,
        }


def _propre(texte: str) -> str:
    """Retire les caractères de contrôle (sauf saut de ligne) et les caractères invisibles de mise en forme."""
    return "".join(c for c in texte if c == "\n" or unicodedata.category(c) not in ("Cc", "Cf", "Co", "Cs")).strip()


def analyser(lien: str) -> LienJarvis:
    """`jarvis://<action>[/<valeur>][?clé=valeur]` → action de la liste blanche, ou ErreurLien."""
    if not isinstance(lien, str) or not lien or len(lien) > LONGUEUR_MAX:
        raise ErreurLien("Lien vide ou trop long")
    if any(unicodedata.category(c) == "Cc" for c in lien):
        raise ErreurLien("Lien refusé : caractères de contrôle")
    try:
        morceaux = urlsplit(lien)
    except ValueError as exc:
        raise ErreurLien("Lien illisible") from exc
    if morceaux.scheme.lower() != SCHEMA:
        raise ErreurLien("Seuls les liens jarvis:// sont acceptés")
    if "@" in morceaux.netloc or ":" in morceaux.netloc or morceaux.fragment:
        raise ErreurLien("Lien refusé : identifiant, port ou fragment interdits")
    action = morceaux.netloc.lower()
    if not _ACTION.match(action) or action not in ACTIONS:
        raise ErreurLien(f"Action inconnue : « {action[:30]} »")
    permis = ACTIONS[action]
    parametres: dict[str, str] = {}
    try:
        paires = parse_qsl(morceaux.query, keep_blank_values=True, strict_parsing=bool(morceaux.query))
    except ValueError as exc:
        raise ErreurLien("Paramètres illisibles") from exc
    for cle, valeur in paires:
        if cle not in permis:
            raise ErreurLien(f"Paramètre non permis pour « {action} » : « {cle[:30]} »")
        if cle in parametres:
            raise ErreurLien(f"Paramètre répété : « {cle} »")
        parametres[cle] = valeur
    chemin = unquote(morceaux.path).strip("/")
    if chemin:
        if "/" in chemin or len(permis) != 1:
            raise ErreurLien("Chemin non permis")
        (cle,) = permis
        if cle in parametres:
            raise ErreurLien(f"Paramètre donné deux fois : « {cle} »")
        parametres[cle] = chemin
    return _verifier(action, parametres)


def _verifier(action: str, p: dict[str, str]) -> LienJarvis:
    if action == "ouvrir":
        vue = p.get("vue", "").lower()
        if vue not in VUES:
            raise ErreurLien(f"Vue inconnue : « {vue[:30]} »")
        return LienJarvis(action, {"vue": vue})
    if action in ("conversation", "decision"):
        try:
            ident = str(UUID(p.get("id", "")))
        except ValueError as exc:
            raise ErreurLien("Identifiant invalide") from exc
        return LienJarvis(action, {"id": ident})
    if action == "dire":
        texte = _propre(p.get("texte", ""))
        if not texte:
            raise ErreurLien("Texte vide")
        return LienJarvis(action, {"texte": texte[:TEXTE_MAX]})
    return LienJarvis(action, {})
