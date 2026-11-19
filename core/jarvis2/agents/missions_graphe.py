"""Missions « projet » : plan Markdown à cases → graphe de dépendances, exécuté en parallèle borné.

Format du plan (une étape par case) :

    - [ ] E1 : Titre de l'étape
      Détail facultatif sur les lignes indentées suivantes.
    - [ ] E2 : Autre étape (après E1)
    - [x] E3 : Étape déjà faite (après E1, E2)

`(après E1, E2)` en fin de ligne donne les dépendances (« apres » accepté, casse indifférente). Une case cochée
est une étape faite : elle n'est pas relancée. Erreurs signalées (textes en français) : identifiant en double,
dépendance inconnue, cycle, plus de `MAX_ETAPES` étapes. Ce module ne touche ni la base ni les moteurs.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

PhasePlan = Literal["preparation", "a_valider", "execution", "terminee", "echec"]
StatutEtape = Literal["a_faire", "attente_approbation", "en_cours", "faite", "refusee", "echec", "sautee"]

MAX_ETAPES = 30
MAX_EXTRAIT = 600  # extrait du résultat d'une étape montré dans l'interface
PARALLELE_DEFAUT = 2
PARALLELE_MIN, PARALLELE_MAX = 1, 8

_CASE = re.compile(r"^(?P<retrait>\s*)[-*+]\s+\[(?P<coche>[ xX])\]\s+(?P<reste>.*)$")
_ENTETE = re.compile(r"^(?P<id>E\d+)\s*[:：.\-–—)]\s*(?P<titre>.*)$")
_APRES = re.compile(r"\(\s*apr[eè]s\b\s*:?\s*(?P<liste>[^()]*)\)\s*$", re.IGNORECASE)
_IDENT = re.compile(r"\bE\d+\b")


@dataclass
class Etape:
    id: str
    titre: str
    detail: str = ""
    apres: list[str] = field(default_factory=list)
    fait: bool = False
    ligne: int = 0  # numéro (0 = première) de la ligne de la case dans le plan
    niveau: int = 0


@dataclass
class PlanLu:
    etapes: list[Etape]
    erreurs: list[str]

    @property
    def total(self) -> int:
        return len(self.etapes)

    @property
    def faites(self) -> int:
        return sum(1 for e in self.etapes if e.fait)

    def etape(self, ident: str) -> Etape | None:
        return next((e for e in self.etapes if e.id == ident), None)


def _entete(reste: str) -> tuple[str, str, list[str]] | None:
    """`E2 : Titre (après E1)` → (id, titre, dépendances) ; None si la case n'a pas d'identifiant."""
    trouve = _ENTETE.match(reste.strip())
    if trouve is None:
        return None
    titre = trouve.group("titre").strip()
    apres: list[str] = []
    dep = _APRES.search(titre)
    if dep is not None:
        apres = list(dict.fromkeys(_IDENT.findall(dep.group("liste").upper())))
        titre = titre[: dep.start()].strip()
    return trouve.group("id").upper(), titre.rstrip(" :—–-") or trouve.group("id").upper(), apres


def lire_plan(texte: str) -> PlanLu:
    """Étapes reconnues (dans l'ordre du plan) et erreurs. Les lignes sans case reconnue sont ignorées."""
    etapes: list[Etape] = []
    courante: Etape | None = None
    details: list[str] = []
    retrait_case = 0

    def clore() -> None:
        if courante is not None:
            courante.detail = "\n".join(details).strip()

    for numero, ligne in enumerate(texte.splitlines()):
        case = _CASE.match(ligne)
        entete = _entete(case.group("reste")) if case else None
        if case is not None and entete is not None:
            clore()
            ident, titre, apres = entete
            courante = Etape(ident, titre, apres=apres, fait=case.group("coche") != " ", ligne=numero)
            etapes.append(courante)
            details = []
            retrait_case = len(case.group("retrait").expandtabs(4))
            continue
        if courante is None:
            continue
        if not ligne.strip():
            details.append("")
            continue
        retrait = len(ligne) - len(ligne.lstrip())
        if retrait > retrait_case and case is None:
            details.append(ligne.strip())
        else:  # ligne non indentée (ou autre case) : fin du détail
            clore()
            courante = None
    clore()
    plan = PlanLu(etapes, verifier(etapes))
    calculer_niveaux(plan.etapes)
    return plan


def verifier(etapes: Sequence[Etape]) -> list[str]:
    erreurs: list[str] = []
    vus: set[str] = set()
    for e in etapes:
        if e.id in vus:
            erreurs.append(f"Identifiant en double : {e.id}")
        vus.add(e.id)
    for e in etapes:
        for d in e.apres:
            if d not in vus:
                erreurs.append(f"Dépendance inconnue : {e.id} dépend de {d}, qui n'existe pas")
    cycle = trouver_cycle(etapes)
    if cycle:
        erreurs.append(f"Cycle de dépendances : {' → '.join(cycle)}")
    if len(etapes) > MAX_ETAPES:
        erreurs.append(f"Plus de {MAX_ETAPES} étapes ({len(etapes)}) : regroupez-en")
    return erreurs


def trouver_cycle(etapes: Sequence[Etape]) -> list[str]:
    """Premier cycle trouvé (ex. ["E1", "E2", "E1"]) ; liste vide sans cycle."""
    graphe = {e.id: [d for d in e.apres] for e in etapes}
    couleur: dict[str, int] = {}  # 1 : en cours de visite, 2 : terminé
    pile: list[str] = []

    def visiter(n: str) -> list[str]:
        couleur[n] = 1
        pile.append(n)
        for d in graphe.get(n, []):
            if d not in graphe:
                continue
            if couleur.get(d) == 1:
                return [*pile[pile.index(d) :], d]
            if couleur.get(d) is None:
                trouve = visiter(d)
                if trouve:
                    return trouve
        pile.pop()
        couleur[n] = 2
        return []

    for e in etapes:
        if couleur.get(e.id) is None:
            trouve = visiter(e.id)
            if trouve:
                return trouve
    return []


def calculer_niveaux(etapes: Sequence[Etape]) -> None:
    """Niveau = longueur du plus long chemin depuis une étape sans dépendance (colonnes de l'affichage).
    Dépendances inconnues ignorées ; dans un cycle, la dépendance qui referme le cycle est ignorée."""
    par_id = {e.id: e for e in etapes}
    niveaux: dict[str, int] = {}
    en_cours: set[str] = set()

    def niveau(ident: str) -> int:
        if ident in niveaux:
            return niveaux[ident]
        en_cours.add(ident)
        deps = [d for d in par_id[ident].apres if d in par_id and d not in en_cours]
        valeur = 1 + max((niveau(d) for d in deps), default=-1)
        en_cours.discard(ident)
        niveaux[ident] = valeur
        return valeur

    for e in etapes:
        e.niveau = niveau(e.id)


def cocher(texte: str, ident: str) -> str:
    """Coche la case de l'étape `ident` dans le Markdown du plan (le reste du texte est gardé tel quel)."""
    lignes = texte.splitlines(keepends=True)
    for i, ligne in enumerate(lignes):
        case = _CASE.match(ligne.rstrip("\r\n"))
        if case is None:
            continue
        entete = _entete(case.group("reste"))
        if entete is not None and entete[0] == ident:
            debut = case.start("coche")
            lignes[i] = ligne[:debut] + "x" + ligne[debut + 1 :]
            break
    return "".join(lignes)


def ordre(etapes: Sequence[Etape]) -> list[Etape]:
    """Ordre d'exécution : par niveau, puis dans l'ordre du plan."""
    return sorted(etapes, key=lambda e: (e.niveau, e.ligne))


async def ordonnancer(
    etapes: Sequence[Etape],
    lancer: Callable[[Etape], Awaitable[bool]],
    sauter: Callable[[Etape], Awaitable[None]],
    parallele: int,
) -> dict[str, bool]:
    """Exécute le graphe (sans erreur) : une étape part dès que ses dépendances ont réussi, au plus `parallele`
    à la fois. `lancer` renvoie False pour un échec ou un refus : les descendantes sont alors `sauter`.
    Une étape déjà faite compte comme réussie, sans être relancée. Une exception (ou une annulation) arrête tout."""
    borne = asyncio.Semaphore(max(PARALLELE_MIN, parallele))
    taches: dict[str, asyncio.Task[bool]] = {}

    async def une(e: Etape) -> bool:
        if e.fait:
            return True
        deps = [taches[d] for d in e.apres if d in taches]
        reussies = await asyncio.gather(*deps) if deps else []
        if not all(reussies):
            await sauter(e)
            return False
        async with borne:
            return await lancer(e)

    for e in ordre(etapes):
        taches[e.id] = asyncio.get_running_loop().create_task(une(e))
    try:
        await asyncio.gather(*taches.values())
    except BaseException:
        for t in taches.values():
            t.cancel()
        await asyncio.gather(*taches.values(), return_exceptions=True)
        raise
    return {i: t.result() for i, t in taches.items()}


def extrait(texte: str | None) -> str | None:
    if texte is None:
        return None
    texte = texte.strip()
    return texte if len(texte) <= MAX_EXTRAIT else texte[: MAX_EXTRAIT - 1].rstrip() + "…"


def borne_parallele(valeur: Any) -> int:
    try:
        n = int(valeur)
    except (TypeError, ValueError):
        return PARALLELE_DEFAUT
    return min(PARALLELE_MAX, max(PARALLELE_MIN, n))


def etat_vide(e: Etape) -> dict[str, Any]:
    return {
        "id": e.id,
        "statut": "faite" if e.fait else "a_faire",
        "moteur": None,
        "raison": None,
        "demande_id": None,
        "resultat": None,
        "erreur": None,
        "debut": None,
        "fin": None,
    }


def plan_mission(ligne: Mapping[str, Any], parallele: int) -> dict[str, Any]:
    """`PlanMission` de l'API : le graphe est relu depuis le Markdown du plan, l'état d'exécution vient de
    `graphe` (par identifiant d'étape)."""
    graphe = ligne.get("graphe") or {}
    etats = {str(d.get("id")): d for d in graphe.get("etapes", []) if isinstance(d, dict)}
    lu = lire_plan(ligne.get("plan") or "")
    etapes = []
    for e in lu.etapes:
        etat = {**etat_vide(e), **etats.get(e.id, {})}
        etapes.append(
            {
                "id": e.id,
                "titre": e.titre,
                "detail": e.detail,
                "apres": e.apres,
                "niveau": e.niveau,
                **{k: etat[k] for k in etat_vide(e) if k != "id"},
            }
        )
    return {
        "phase": ligne.get("phase"),
        "brainstorm": ligne.get("brainstorm") or "",
        "spec": ligne.get("spec") or "",
        "plan": ligne.get("plan") or "",
        "etapes": etapes,
        "erreurs": lu.erreurs,
        "faites": lu.faites,
        "total": lu.total,
        "parallele": borne_parallele(graphe.get("parallele", parallele)),
        "repli": bool(graphe.get("repli", False)),
    }


def nettoyer_plan(texte: str) -> str:
    """Réponse du modèle → Markdown du plan (sans clôture de bloc de code)."""
    texte = texte.strip()
    bloc = re.fullmatch(r"```[a-zA-Z]*\n(.*?)\n?```", texte, re.DOTALL)
    return (bloc.group(1) if bloc else texte).strip()
