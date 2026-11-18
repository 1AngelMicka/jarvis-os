"""Mémoire : recherche hybride et noyau, portés de JARVIS v1 (`memoire.py`) à l'identique.

Recherche d'un texte :
1. découpage du message en sous-questions (le message entier d'abord) ;
2. pour chacune, score = 0,75 × cosinus (embeddings) + 0,25 × plein texte français ;
3. fusion : par sous-question, résultats ≥ max(seuil, 80 % de son meilleur score), bonus léger (type, récence,
   orientation « qu'as-tu appris / quoi de neuf ») ; les 2 meilleurs de chaque sous-question passent d'abord ;
4. sélection : au plus N souvenirs, un budget de caractères, un par section de document, 3 par source.

Le **noyau** (souvenirs tagués `noyau`) est toujours injecté, plus récents d'abord, dans son propre budget.
Les souvenirs `local_uniquement` ne partent jamais vers un moteur externe.
Un sujet exclu par l'utilisateur est retiré de tout texte de mémoire injecté au modèle (`expurger`).
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import asyncpg

from .embeddings import Encodeur, vecteur_sql

POIDS_VECTEUR = 0.75
POIDS_TEXTE = 0.25
TAG_NOYAU = "noyau"
TAILLE_MAX_SOUVENIR = 1200
BONUS_TYPE = {"decision": 0.02, "fait": 0.02}
BONUS_RECENCE = 0.03  # bonus maximal d'un souvenir tout juste créé…
DEMI_VIE_RECENCE = 30.0  # … divisé par e tous les 30 jours
RATIO_SOUS_REQUETE = 0.8
PAR_SOUS_REQUETE = 2
MAX_SOUS_REQUETES = 6
MAX_SOURCES_ORIENTEES = 4

COLONNES = "id, contenu, type, tags, source, confidentialite, origine, canal_detail, cree_le, maj_le"

_INTERROGATIFS = (
    r"(?:quel(?:le)?s?|pourquoi|comment|combien|quand|où|qui|que|qu['’]|est-ce|"
    r"faut-il|dois-je|peux-tu|peut-on|as-tu|y a-t-il)"
)
_SEPARATEURS = re.compile(
    r"[?;\n]+|,\s*et\s+|,\s*(?=" + _INTERROGATIFS + r"\b)|\s+et\s+(?=" + _INTERROGATIFS + r"\b)", re.IGNORECASE
)

_FIN_DE_PHRASE = re.compile(r"(?<=[.!?;])\s+")


@dataclass(frozen=True, slots=True)
class Souvenir:
    id: str
    contenu: str
    type: str
    tags: tuple[str, ...]
    source: str | None
    confidentialite: str
    origine: str
    canal_detail: str | None
    cree_le: datetime
    maj_le: datetime

    def en_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "contenu": self.contenu,
            "type": self.type,
            "tags": list(self.tags),
            "source": self.source,
            "confidentialite": self.confidentialite,
            "origine": self.origine,
            "canal_detail": self.canal_detail,
            "cree_le": self.cree_le.isoformat(),
            "maj_le": self.maj_le.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class Resultat:
    souvenir: Souvenir
    score: float


def _souvenir(ligne: asyncpg.Record) -> Souvenir:
    return Souvenir(
        id=str(ligne["id"]),
        contenu=ligne["contenu"],
        type=ligne["type"],
        tags=tuple(ligne["tags"] or ()),
        source=ligne["source"],
        confidentialite=ligne["confidentialite"],
        origine=ligne["origine"],
        canal_detail=ligne["canal_detail"],
        cree_le=ligne["cree_le"],
        maj_le=ligne["maj_le"],
    )


# --- Sujets exclus (configuration locale de l'utilisateur, jamais dans le code) ----------------------------


@dataclass(frozen=True)
class Expurgateur:
    """Retire de la mémoire injectée au modèle toute phrase qui nomme un sujet exclu par l'utilisateur."""

    motifs: tuple[re.Pattern[str], ...] = ()

    def mentionne(self, texte: str | None) -> bool:
        return bool(texte) and any(m.search(texte or "") for m in self.motifs)

    def texte(self, texte: str) -> str:
        """Retire toute phrase (ou ligne de tableau) qui nomme un sujet exclu ; le reste est conservé."""
        if not self.mentionne(texte):
            return texte
        lignes = []
        for ligne in texte.split("\n"):
            if not self.mentionne(ligne):
                lignes.append(ligne)
            elif not ligne.lstrip().startswith("|"):  # ligne de tableau : retirée entière
                gardees = [p for p in _FIN_DE_PHRASE.split(ligne) if not self.mentionne(p)]
                if gardees:
                    lignes.append(" ".join(gardees))
        return "\n".join(lignes)

    def souvenir(self, s: Souvenir) -> Souvenir | None:
        """Souvenir expurgé ; None s'il ne reste rien d'utile."""
        if not self.mentionne(s.contenu):
            return s
        contenu = self.texte(s.contenu).strip()
        premiere = contenu.split("\n", 1)[0]
        if len(contenu) - (len(premiere) if premiere.startswith("[") else 0) < 40:
            return None
        return replace(s, contenu=contenu)


# --- Recherche hybride -----------------------------------------------------------------------------------


async def rechercher(
    conn: asyncpg.Pool | asyncpg.Connection,
    encodeur: Encodeur,
    q: str,
    *,
    limite: int = 10,
    exclure_local: bool = False,
    origines: Sequence[str] | None = None,
) -> list[Resultat]:
    """Score = 0,75 × cosinus + 0,25 × plein texte français.

    Texte : 0,5 + 0,5 × ts_rank_cd si TOUS les mots de la requête sont présents ; sinon 0,45 × proportion des
    mots présents (une longue question ne correspond presque jamais en entier).
    """
    vecteur = vecteur_sql(await encodeur.encoder(q))
    lignes = await conn.fetch(
        f"""
        WITH req AS (
            SELECT $1::text::vector AS v, websearch_to_tsquery('french', $2) AS tsq,
                   ARRAY(SELECT DISTINCT unnest(tsvector_to_array(to_tsvector('french', $2)))) AS mots
        ), scores AS (
            SELECT m.*,
                   CASE WHEN m.embedding_model = $8 THEN COALESCE(1 - (m.embedding <=> req.v), 0)
                        ELSE 0 END AS similarite,
                   CASE WHEN m.tsv @@ req.tsq THEN 0.5 + 0.5 * ts_rank_cd(m.tsv, req.tsq, 32)
                        WHEN cardinality(req.mots) = 0 THEN 0
                        ELSE 0.45 * (SELECT count(*) FROM unnest(req.mots) AS mot
                                     WHERE m.tsv @@ quote_literal(mot)::tsquery)::float / cardinality(req.mots)
                   END AS texte
            FROM memoires m CROSS JOIN req
            WHERE m.valid_to IS NULL AND NOT m.archived
              AND (NOT $3 OR m.confidentialite <> 'local_uniquement')
              AND ($4::text[] IS NULL OR m.origine = ANY($4::text[]))
        )
        SELECT {COLONNES}, $5 * similarite + $6 * texte AS score
        FROM scores
        ORDER BY score DESC, cree_le DESC
        LIMIT $7
        """,  # noqa: S608 — COLONNES est une constante
        vecteur,
        q,
        exclure_local,
        list(origines) if origines else None,
        POIDS_VECTEUR,
        POIDS_TEXTE,
        limite,
        encodeur.nom_modele,
    )
    return [Resultat(_souvenir(r), round(float(r["score"]), 4)) for r in lignes]


def decouper_requetes(texte: str, maximum: int = MAX_SOUS_REQUETES) -> list[str]:
    """Message -> [message entier, sous-question 1, …] ; doublons et fragments trop courts écartés."""
    entier = " ".join(texte.split())
    resultat = [entier] if entier else []
    for morceau in _SEPARATEURS.split(texte):
        morceau = re.sub(
            r"^(?:et|ou|mais)\s+", "", " ".join((morceau or "").split()).strip(" ,.:!-"), flags=re.IGNORECASE
        )
        if len(morceau) < 6 or morceau.lower() in (r.lower() for r in resultat):
            continue
        resultat.append(morceau)
        if len(resultat) >= maximum:
            break
    return resultat


def contexte_de(s: Souvenir) -> str | None:
    """« [SUPERPLAN › 5. Architecture cible] » : section d'origine d'un passage importé, sinon None."""
    premiere = s.contenu.split("\n", 1)[0].strip()
    return premiere if premiere.startswith("[") and premiere.endswith("]") else None


def cle_diversite(s: Souvenir) -> tuple[str, str]:
    contexte = contexte_de(s)
    if contexte is None or not s.source:
        return ("id", s.id)
    return (s.source, contexte)


def taille_dans_prompt(s: Souvenir) -> int:
    return min(len(s.contenu), TAILLE_MAX_SOUVENIR)


@dataclass(frozen=True)
class Orientation:
    """Préférences déduites de la question (« qu'as-tu appris… », « quoi de neuf… »)."""

    origines: tuple[str, ...] = ()
    bonus_origine: float = 0.0
    recence: float = 1.0
    sujet: str = ""


_RE_APPRIS = re.compile(
    r"\b(?:appris|apprendre|d[ée]couvert|retenu|tes\s+missions?|tes\s+recherches?|"
    r"tes\s+rapports?|missions?\s+de\s+recherche)\b",
    re.IGNORECASE,
)
_RE_NOUVEAU = re.compile(
    r"quoi\s+de\s+neuf|du\s+nouveau|nouveaut[ée]s?|r[ée]cemment|derni[èe]rement|"
    r"ces\s+derniers\s+jours|derniers?\s+ajouts?|nouveaux\s+souvenirs",
    re.IGNORECASE,
)
_RE_SAIS = re.compile(
    r"qu['’]\s*est[- ]ce\s+que\s+tu\s+(?:sais|connais)|que\s+sais[- ]tu|"
    r"tu\s+sais\s+quoi|que\s+connais[- ]tu",
    re.IGNORECASE,
)
_RE_FORMULE = re.compile(
    r"^.*?\b(?:appris|d[ée]couvert|retenu|sais|connais|neuf|nouveau)\b(?:[- ]tu)?"
    r"(?:\s+(?:r[ée]cemment|derni[èe]rement|de\s+nouveau|gr[âa]ce\s+(?:à|aux)\s+(?:tes\s+)?(?:missions?|recherches?)|"
    r"dans\s+(?:ta|tes)\s+(?:m[ée]moire|missions?)|avec\s+tes\s+missions?|par\s+tes\s+missions?))*"
    r"\s*(?:sur|à\s+propos\s+d[eu']|au\s+sujet\s+d[eu']|concernant|en)?\s*",
    re.IGNORECASE,
)


def orientation(texte: str) -> Orientation | None:
    texte = " ".join((texte or "").split())
    appris, nouveau, sais = (bool(r.search(texte)) for r in (_RE_APPRIS, _RE_NOUVEAU, _RE_SAIS))
    if not (appris or nouveau or sais):
        return None
    sujet = _RE_FORMULE.sub("", texte, count=1).strip(" ?!.,;:")
    if len(sujet) < 3:
        sujet = ""
    if appris:
        return Orientation(("mission",), 0.06, 3.0 if nouveau or not sujet else 2.0, sujet)
    if sais:
        return Orientation(("mission",), 0.02, 1.5 if nouveau else 1.0, sujet)
    return Orientation((), 0.0, 4.0, sujet)


def bonus(s: Souvenir, maintenant: datetime | None = None, o: Orientation | None = None) -> float:
    b = BONUS_TYPE.get(s.type, 0.0)
    if o is not None and s.origine in o.origines:
        b += o.bonus_origine
    cree = s.cree_le if s.cree_le.tzinfo else s.cree_le.replace(tzinfo=UTC)
    age = max(0.0, ((maintenant or datetime.now(UTC)) - cree).total_seconds() / 86400)
    recence = BONUS_RECENCE * (o.recence if o is not None else 1.0)
    return b + recence * math.exp(-age / DEMI_VIE_RECENCE)


def fusionner(
    par_requete: list[list[Resultat]],
    *,
    seuil: float,
    ratio: float = RATIO_SOUS_REQUETE,
    par_sous_requete: int = PAR_SOUS_REQUETE,
    maintenant: datetime | None = None,
    o: Orientation | None = None,
) -> list[Resultat]:
    retenus: list[list[str]] = []
    meilleurs: dict[str, Resultat] = {}
    for resultats in par_requete:
        if not resultats:
            retenus.append([])
            continue
        plancher = max(seuil, ratio * max(r.score for r in resultats))
        liste = []
        for r in resultats:
            if r.score < plancher:
                continue
            ident = r.souvenir.id
            score = round(r.score + bonus(r.souvenir, maintenant, o), 4)
            if ident not in meilleurs or score > meilleurs[ident].score:
                meilleurs[ident] = Resultat(r.souvenir, score)
            liste.append(ident)
        retenus.append(sorted(dict.fromkeys(liste), key=lambda i: -meilleurs[i].score))
    ordre: list[str] = []
    for rang in range(par_sous_requete):
        for liste in retenus:
            if rang < len(liste) and liste[rang] not in ordre:
                ordre.append(liste[rang])
    ordre += [i for i in sorted(meilleurs, key=lambda i: -meilleurs[i].score) if i not in ordre]
    return [meilleurs[i] for i in ordre]


def selectionner(
    candidats: list[Resultat], *, limite: int, budget: int, max_par_source: int = 3, exclure_ids: Sequence[str] = ()
) -> list[Resultat]:
    exclus = set(exclure_ids)
    cles: set[tuple[str, str]] = set()
    par_source: dict[str, int] = {}
    total = 0
    choisis: list[Resultat] = []
    for c in candidats:
        s = c.souvenir
        if s.id in exclus:
            continue
        cle = cle_diversite(s)
        if cle in cles or (s.source and par_source.get(s.source, 0) >= max_par_source):
            continue
        taille = taille_dans_prompt(s)
        if total + taille > budget:
            continue
        choisis.append(c)
        cles.add(cle)
        if s.source:
            par_source[s.source] = par_source.get(s.source, 0) + 1
        total += taille
        if len(choisis) >= limite:
            break
    return choisis


@dataclass(frozen=True)
class ReglagesRecherche:
    limite: int = 10
    seuil: float = 0.2
    budget: int = 7000
    max_par_source: int = 3
    budget_noyau: int = 4000
    expurgateur: Expurgateur = field(default_factory=Expurgateur)


async def rechercher_multi(
    conn: asyncpg.Pool | asyncpg.Connection,
    encodeur: Encodeur,
    texte: str,
    *,
    exclure_local: bool,
    reglages: ReglagesRecherche = ReglagesRecherche(),
    exclure_ids: Sequence[str] = (),
) -> list[Resultat]:
    """Recherche pour la conversation : sous-questions, orientation, fusion, expurgation, sélection."""
    o = orientation(texte)
    par_requete = [
        await rechercher(conn, encodeur, q, limite=max(reglages.limite * 3, 20), exclure_local=exclure_local)
        for q in decouper_requetes(texte)
    ]
    if o is not None and o.origines:
        dedies = await rechercher(
            conn,
            encodeur,
            o.sujet or texte,
            limite=max(reglages.limite * 3, 30),
            exclure_local=exclure_local,
            origines=o.origines,
        )
        groupes: dict[str, list[Resultat]] = {}
        for r in dedies:
            cle = (r.souvenir.source or r.souvenir.id).split("#", 1)[0]  # résumé + rapport d'une mission
            groupes.setdefault(cle, []).append(r)
        par_requete.extend(list(groupes.values())[:MAX_SOURCES_ORIENTEES])
    candidats: list[Resultat] = []
    for c in fusionner(par_requete, seuil=reglages.seuil, o=o):
        s = reglages.expurgateur.souvenir(c.souvenir)
        if s is not None:
            candidats.append(c if s is c.souvenir else Resultat(s, c.score))
    return selectionner(
        candidats,
        limite=reglages.limite,
        budget=reglages.budget,
        max_par_source=reglages.max_par_source,
        exclure_ids=exclure_ids,
    )


# --- Noyau -----------------------------------------------------------------------------------------------


def limiter_noyau(souvenirs: list[Souvenir], budget: int) -> list[Souvenir]:
    """Plus récents d'abord tant que le budget le permet ; le premier est tronqué s'il dépasse seul."""
    choisis: list[Souvenir] = []
    total = 0
    for s in souvenirs:
        taille = len(s.contenu)
        if total + taille <= budget:
            choisis.append(s)
            total += taille
        elif not choisis and budget > 0:
            choisis.append(replace(s, contenu=s.contenu[: budget - 1] + "…"))
            total = budget
    return choisis


async def lire_noyau(
    conn: asyncpg.Pool | asyncpg.Connection,
    *,
    exclure_local: bool,
    budget: int = 4000,
    limite: int = 100,
    expurgateur: Expurgateur | None = None,
) -> list[Souvenir]:
    expurgateur = expurgateur or Expurgateur()
    lignes = await conn.fetch(
        f"SELECT {COLONNES} FROM memoires WHERE tags @> ARRAY[$1]::text[]"  # noqa: S608 — constante
        " AND valid_to IS NULL AND NOT archived"
        " AND (NOT $2 OR confidentialite <> 'local_uniquement') ORDER BY cree_le DESC, id LIMIT $3",
        TAG_NOYAU,
        exclure_local,
        limite,
    )
    noyau = [s for s in (expurgateur.souvenir(_souvenir(r)) for r in lignes) if s is not None]
    return limiter_noyau(noyau, budget)


async def compter(conn: asyncpg.Pool | asyncpg.Connection) -> dict[str, int]:
    ligne = await conn.fetchrow(
        "SELECT count(*) AS total, count(*) FILTER (WHERE tags @> ARRAY['noyau']) AS noyau,"
        " count(*) FILTER (WHERE confidentialite = 'local_uniquement') AS local FROM memoires"
        " WHERE valid_to IS NULL AND NOT archived"
    )
    assert ligne is not None
    return {"total": ligne["total"], "noyau": ligne["noyau"], "local_uniquement": ligne["local"]}


# --- Texte injecté au modèle -----------------------------------------------------------------------------


def _tronquer(texte: str, n: int = TAILLE_MAX_SOUVENIR) -> str:
    return texte if len(texte) <= n else texte[: n - 1] + "…"


def formater_souvenirs(resultats: list[Resultat]) -> str:
    if not resultats:
        return "(aucun souvenir pertinent)"
    blocs = []
    for r in resultats:
        s = r.souvenir
        tags = f" [tags : {', '.join(s.tags)}]" if s.tags else ""
        source = f", source {s.source}" if s.source else ""
        blocs.append(f"- ({s.type}, {s.cree_le.date().isoformat()}{source}){tags} {_tronquer(s.contenu)}")
    return "\n".join(blocs)


def formater_noyau(noyau: list[Souvenir]) -> str:
    return "\n".join(f"- ({s.cree_le.date().isoformat()}) {s.contenu}" for s in noyau)


@dataclass
class ContexteMemoire:
    noyau: list[Souvenir] = field(default_factory=list)
    souvenirs: list[Resultat] = field(default_factory=list)
    consultee: bool = True
    expurgateur: Expurgateur = field(default_factory=Expurgateur)

    def bloc(self) -> str:
        """Section mémoire des consignes système (noyau puis souvenirs), toujours expurgée."""
        if not self.consultee:
            return "\nSouvenirs pertinents :\n(mémoire indisponible pour ce message)"
        texte = ""
        if self.noyau:
            texte += f"\nNoyau (connaissances de référence, prioritaires) :\n{formater_noyau(self.noyau)}\n"
        texte += (
            f"\nSouvenirs pertinents (du plus pertinent au moins pertinent) :\n{formater_souvenirs(self.souvenirs)}"
        )
        return self.expurgateur.texte(texte)
