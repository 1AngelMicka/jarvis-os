"""Mémoire : recherche hybride et noyau, portés de JARVIS v1 (`memoire.py`) à l'identique.

Recherche d'un texte :
1. découpage du message en sous-questions (le message entier d'abord) ;
2. pour chacune, score = 0,75 × cosinus (embeddings) + 0,25 × plein texte français ;
3. fusion : par sous-question, résultats ≥ max(seuil, 80 % de son meilleur score), bonus léger (type, récence,
   orientation « qu'as-tu appris / quoi de neuf ») ; les 2 meilleurs de chaque sous-question passent d'abord ;
4. sélection : au plus N souvenirs, un budget de caractères, un par section de document, 3 par source.

Le **noyau** (souvenirs tagués `noyau`) est toujours injecté, plus récents d'abord, dans son propre budget.

Niveaux (`NIVEAUX`) : vers un moteur externe, un souvenir « public » part partout (noyau, blocs, souvenirs trouvés,
nouveautés), un « semi_prive » seulement s'il est trouvé pertinent pour le message, un « prive » jamais
(`VERS_EXTERNE`). Invariant : niveau « prive » ⇔ confidentialité « local_uniquement » (les deux colonnes restent
synchronisées, le code qui écrit `local_uniquement` continue de marcher).
Un sujet exclu par l'utilisateur est retiré de tout texte de mémoire injecté au modèle (`expurger`).
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal, cast, get_args

from .db import Base, Connexion, Executant, Ligne
from .db_sqlite import vecteur_octets
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

COLONNES = (
    "id, contenu, type, tags, source, confidentialite, origine, canal_detail, cree_le, maj_le, importance,"
    " access_count, niveau"
)

Niveau = Literal["public", "semi_prive", "prive"]
NIVEAUX: tuple[Niveau, ...] = get_args(Niveau)
NIVEAU_DEFAUT_SOUVENIR: Niveau = "semi_prive"
NIVEAU_DEFAUT_BLOC: Niveau = "public"
# Ce qui peut partir vers un moteur externe, par usage (source unique : requêtes et « Où partent mes données »)
VERS_EXTERNE: dict[str, tuple[Niveau, ...]] = {
    "noyau": ("public",),
    "blocs": ("public",),
    "nouveautes": ("public",),
    "recherche": ("public", "semi_prive"),
}
LIBELLES_USAGE = {
    "noyau": "le noyau",
    "blocs": "les blocs",
    "nouveautes": "les nouveautés",
    "recherche": "les souvenirs trouvés pertinents pour le message",
}
LIBELLES_NIVEAU: dict[Niveau, str] = {"public": "Public", "semi_prive": "Semi-privé", "prive": "Privé"}


def niveau_valide(niveau: str) -> Niveau:
    if niveau not in NIVEAUX:
        raise ValueError(f"Niveau inconnu : « {niveau} » ({', '.join(NIVEAUX)})")
    return niveau


def confidentialite_de(niveau: str) -> str:
    """Confidentialité synchronisée avec un niveau (« prive » ⇔ « local_uniquement »)."""
    return "local_uniquement" if niveau == "prive" else "normal"


def niveau_de(confidentialite: str, niveau: str | None, defaut: Niveau = NIVEAU_DEFAUT_SOUVENIR) -> Niveau:
    """Niveau d'une écriture : le niveau donné l'emporte ; sinon « prive » si local uniquement, sinon `defaut`."""
    if niveau is not None:
        return niveau_valide(niveau)
    return "prive" if confidentialite == "local_uniquement" else defaut


def usages_externes(niveau: str) -> list[str]:
    """Usages pour lesquels ce niveau peut partir vers un moteur externe (vide : jamais)."""
    return [u for u, niveaux in VERS_EXTERNE.items() if niveau in niveaux]


def regles_niveaux() -> list[dict[str, str]]:
    """Règles lisibles, générées depuis `VERS_EXTERNE` (« Où partent mes données »)."""
    regles = []
    for n in NIVEAUX:
        usages = usages_externes(n)
        if not usages:
            vers = "Ne part jamais vers une IA externe : reste sur ce PC."
        elif set(usages) == set(VERS_EXTERNE):
            vers = "Peut partir vers une IA externe partout : " + ", ".join(LIBELLES_USAGE[u] for u in usages) + "."
        else:
            vers = (
                "Part vers une IA externe seulement dans "
                + ", ".join(LIBELLES_USAGE[u] for u in usages)
                + " ; jamais dans "
                + ", ".join(LIBELLES_USAGE[u] for u in VERS_EXTERNE if u not in usages)
                + "."
            )
        if usages:
            vers += " Toujours après retrait des sujets exclus et masquage des secrets."
        regles.append({"niveau": n, "libelle": LIBELLES_NIVEAU[n], "vers_cloud": vers})
    return regles


def condition_niveaux(conn: Executant, parametre: str) -> str:
    """Condition « le niveau fait partie de la liste `parametre` » (tableau PostgreSQL ou liste JSON SQLite)."""
    if conn.dialecte == "sqlite":
        return f"niveau IN (SELECT value FROM json_each({parametre}))"  # noqa: S608 — « $n » constant
    return f"niveau = ANY({parametre}::text[])"


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
    importance: float = 0.5
    acces: int = 0
    niveau: str = NIVEAU_DEFAUT_SOUVENIR
    remplace: bool = False  # a une version antérieure (changement d'avis) : voir `versions`

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
            "importance": self.importance,
            "acces": self.acces,
            "niveau": self.niveau,
            "remplace": self.remplace,
        }


@dataclass(frozen=True, slots=True)
class Resultat:
    souvenir: Souvenir
    score: float
    similarite: float = 0.0  # composante vecteur (cosinus du modèle actif)
    texte: float = 0.0  # composante plein texte


def _souvenir(ligne: Ligne) -> Souvenir:
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
        importance=float(ligne.get("importance", 0.5) if ligne.get("importance") is not None else 0.5),
        acces=int(ligne.get("access_count") or 0),
        niveau=str(ligne.get("niveau") or niveau_de(ligne["confidentialite"], None)),
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
    conn: Executant,
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
    v = await encodeur.encoder(q)
    if conn.dialecte == "sqlite":
        return await _rechercher_sqlite(conn, encodeur.nom_modele, v, q, limite, exclure_local, origines)
    vecteur = vecteur_sql(v)
    lignes = await conn.fetch(
        f"""
        WITH req AS (
            SELECT $1::text::vector AS v, websearch_to_tsquery('french', $2) AS tsq,
                   ARRAY(SELECT DISTINCT unnest(tsvector_to_array(to_tsvector('french', $2)))) AS mots
        ), scores AS (
            SELECT m.*,
                   CASE WHEN m.embedding_model = $8 THEN COALESCE(1 - (m.embedding <=> req.v), 0)
                        ELSE COALESCE((SELECT 1 - (mv.vecteur <=> req.v) FROM memoire_vecteurs mv
                                       WHERE mv.memoire_id = m.id AND mv.modele = $8), 0) END AS similarite,
                   CASE WHEN m.tsv @@ req.tsq THEN 0.5 + 0.5 * ts_rank_cd(m.tsv, req.tsq, 32)
                        WHEN cardinality(req.mots) = 0 THEN 0
                        ELSE 0.45 * (SELECT count(*) FROM unnest(req.mots) AS mot
                                     WHERE m.tsv @@ quote_literal(mot)::tsquery)::float / cardinality(req.mots)
                   END AS texte
            FROM memoires m CROSS JOIN req
            WHERE m.valid_to IS NULL AND NOT m.archived
              AND (NOT $3 OR (m.confidentialite <> 'local_uniquement' AND m.niveau <> 'prive'))
              AND ($4::text[] IS NULL OR m.origine = ANY($4::text[]))
        )
        SELECT {COLONNES}, similarite, texte, $5 * similarite + $6 * texte AS score
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
    return [
        Resultat(_souvenir(r), round(float(r["score"]), 4), float(r["similarite"]), float(r["texte"])) for r in lignes
    ]


# Mots vides (équivalent approché du dictionnaire « french » de PostgreSQL, qui en retire davantage)
MOTS_VIDES = frozenset(
    [
        "a",
        "au",
        "aux",
        "avec",
        "ce",
        "ces",
        "cet",
        "cette",
        "d",
        "dans",
        "de",
        "des",
        "du",
        "elle",
        "elles",
        "en",
        "est",
        "et",
        "etre",
        "il",
        "ils",
        "j",
        "je",
        "l",
        "la",
        "le",
        "les",
        "leur",
        "leurs",
        "lui",
        "m",
        "ma",
        "mais",
        "me",
        "mes",
        "moi",
        "mon",
        "n",
        "ne",
        "nos",
        "notre",
        "nous",
        "on",
        "ou",
        "par",
        "pas",
        "pour",
        "qu",
        "que",
        "qui",
        "s",
        "sa",
        "se",
        "ses",
        "son",
        "sont",
        "sur",
        "t",
        "ta",
        "te",
        "tes",
        "toi",
        "ton",
        "tu",
        "un",
        "une",
        "vos",
        "votre",
        "vous",
        "y",
    ]
)


def mots(texte: str) -> list[str]:
    """Mots comparables : minuscules, sans accents (comme le tokeniseur FTS5 `unicode61 remove_diacritics 2`)."""
    sans_accents = "".join(c for c in unicodedata.normalize("NFKD", texte.lower()) if not unicodedata.combining(c))
    return re.findall(r"[^\W_]+", sans_accents)


def mots_requete(texte: str) -> list[str]:
    return list(dict.fromkeys(m for m in mots(texte) if m not in MOTS_VIDES))


async def _rechercher_sqlite(
    conn: Executant,
    modele: str,
    vecteur: list[float],
    q: str,
    limite: int,
    exclure_local: bool,
    origines: Sequence[str] | None,
) -> list[Resultat]:
    """Même score qu'avec PostgreSQL : 0,75 × cosinus (sqlite-vec) + 0,25 × plein texte (FTS5, BM25).

    Texte : 0,5 + 0,5 × r / (r + 1) (r = pertinence BM25) si TOUS les mots de la requête sont présents ; sinon
    0,45 × proportion des mots présents. Seuls les souvenirs actifs du modèle de l'encodeur sont comparés.
    """
    filtre = (
        " FROM memoires WHERE valid_to IS NULL AND NOT archived"
        " AND (NOT $1 OR (confidentialite <> 'local_uniquement' AND niveau <> 'prive'))"
        " AND ($2 IS NULL OR origine IN (SELECT value FROM json_each($2)))"
    )
    filtres = (exclure_local, list(origines) if origines else None)
    similarites = {
        str(r["id"]): float(r["s"] or 0.0)
        for r in await conn.fetch(
            "SELECT id, CASE WHEN embedding_model = $3 AND embedding IS NOT NULL"  # noqa: S608 — constantes
            " THEN 1 - vec_distance_cosine(embedding, $4)"
            " ELSE (SELECT 1 - vec_distance_cosine(mv.vecteur, $4) FROM memoire_vecteurs mv"
            " WHERE mv.memoire_id = memoires.id AND mv.modele = $3) END AS s" + filtre,
            *filtres,
            modele,
            vecteur_octets(vecteur),
        )
    }
    termes = mots_requete(q)
    pertinence: dict[str, float] = {}
    if termes:
        for r in await conn.fetch(
            "SELECT id, -bm25(memoires_fts) AS r FROM memoires_fts WHERE memoires_fts MATCH $1"
            " ORDER BY bm25(memoires_fts) LIMIT 500",
            " OR ".join(f'"{t}"' for t in termes),  # lettres et chiffres seulement : aucun guillemet possible
        ):
            if str(r["id"]) in similarites:
                pertinence[str(r["id"])] = max(float(r["r"]), 0.0)
    meilleurs = sorted(similarites, key=lambda i: -similarites[i])[: max(limite * 3, 30)]
    candidats = list(dict.fromkeys([*pertinence, *meilleurs]))
    if not candidats:
        return []
    lignes = await conn.fetch(
        f"SELECT {COLONNES} FROM memoires WHERE id IN (SELECT value FROM json_each($1))",  # noqa: S608 — constante
        candidats,
    )
    resultats = []
    for ligne in lignes:
        ident = str(ligne["id"])
        texte = 0.0
        if ident in pertinence:
            presents = set(mots(ligne["contenu"]))
            nb = sum(1 for t in termes if t in presents)
            r = pertinence[ident]
            texte = 0.5 + 0.5 * r / (r + 1) if nb == len(termes) else 0.45 * nb / len(termes)
        score = POIDS_VECTEUR * similarites[ident] + POIDS_TEXTE * texte
        resultats.append(Resultat(_souvenir(ligne), round(score, 4), similarites[ident], texte))
    resultats.sort(key=lambda x: (-x.score, -x.souvenir.cree_le.timestamp()))
    return resultats[:limite]


DIMENSION_COLONNE_PG = 384  # memoires.embedding : vector(384), le modèle d'origine (migration 001)


async def _va_dans_colonne(conn: Executant, modele: str | None, dimension: int) -> bool:
    """Le vecteur rejoint la colonne s'il vient du modèle qui la remplit déjà (ou si elle est vide)."""
    if conn.dialecte != "sqlite" and dimension != DIMENSION_COLONNE_PG:
        return False
    if modele is None:
        return True
    majoritaire = await conn.fetchval(
        "SELECT embedding_model FROM memoires WHERE embedding_model IS NOT NULL"
        " GROUP BY embedding_model ORDER BY count(*) DESC LIMIT 1"
    )
    return majoritaire is None or majoritaire == modele


async def ajouter(
    conn: Executant,
    contenu: str,
    *,
    type_: str = "note",
    tags: Sequence[str] = (),
    source: str | None = None,
    confidentialite: str = "normal",
    origine: str = "autre",
    vecteur: list[float] | None = None,
    modele: str | None = None,
    importance: float = 0.5,
    niveau: str | None = None,
) -> str:
    """Nouveau souvenir (plein texte indexé par le moteur : tsvector français ou FTS5).

    Niveau et confidentialité restent synchronisés : un `niveau` donné l'emporte (et fixe la confidentialité) ;
    sinon « prive » si `local_uniquement`, « public » pour un souvenir du noyau (il part déjà partout), sinon
    « semi_prive ».

    La colonne `embedding` garde le modèle d'origine de la base (384 dimensions sous PostgreSQL) ; le vecteur d'un
    autre modèle (ex. BAAI/bge-m3 après une bascule) va dans `memoire_vecteurs`, où la recherche le trouve.
    """
    niveau = niveau_de(confidentialite, niveau, "public" if TAG_NOYAU in tags else NIVEAU_DEFAUT_SOUVENIR)
    confidentialite = confidentialite_de(niveau)
    a_part = vecteur is not None and not await _va_dans_colonne(conn, modele, len(vecteur))
    if a_part:
        ident = await ajouter(
            conn,
            contenu,
            type_=type_,
            tags=tags,
            source=source,
            confidentialite=confidentialite,
            origine=origine,
            importance=importance,
            niveau=niveau,
        )
        assert vecteur is not None
        if conn.dialecte == "sqlite":
            await conn.execute(
                "INSERT INTO memoire_vecteurs (memoire_id, modele, vecteur) VALUES ($1, $2, $3)",
                ident,
                modele,
                vecteur_octets(vecteur),
            )
        else:
            await conn.execute(
                "INSERT INTO memoire_vecteurs (memoire_id, modele, vecteur) VALUES ($1, $2, $3::text::vector)",
                ident,
                modele,
                vecteur_sql(vecteur),
            )
        return ident
    if conn.dialecte == "sqlite":
        requete = (
            "INSERT INTO memoires (contenu, type, tags, source, confidentialite, origine, embedding, embedding_model,"
            " valid_from, observed_at, importance, niveau)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now(), now(), $9, $10) RETURNING id"
        )
        valeur: Any = vecteur_octets(vecteur) if vecteur is not None else None
    else:
        requete = (
            "INSERT INTO memoires (contenu, type, tags, source, confidentialite, origine, embedding, embedding_model,"
            " valid_from, observed_at, tsv, importance, niveau) VALUES ($1, $2, $3, $4, $5, $6, $7::text::vector, $8,"
            " now(), now(), to_tsvector('french', $1), $9, $10) RETURNING id"
        )
        valeur = vecteur_sql(vecteur) if vecteur is not None else None
    ident = await conn.fetchval(
        requete,
        contenu,
        type_,
        list(tags),
        source,
        confidentialite,
        origine,
        valeur,
        modele if vecteur else None,
        min(max(importance, 0.0), 1.0),
        niveau,
    )
    return str(ident)


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
    classement: str = "v2"  # « v1 » (score hybride de JARVIS v1) ou « v2 » (RRF + importance, memoire_v2.py)


async def rechercher_multi(
    conn: Executant,
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
    if reglages.classement == "v2":
        from .memoire_v2 import classer_v2

        par_requete = [classer_v2(r) for r in par_requete]
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


def _avec_tag(conn: Executant, parametre: str) -> str:
    """Condition « le souvenir porte ce tag » (tableau PostgreSQL ou tableau JSON SQLite)."""
    if conn.dialecte == "sqlite":
        return f"EXISTS (SELECT 1 FROM json_each(tags) WHERE value = {parametre})"  # noqa: S608 — « $n » constant
    return f"tags @> ARRAY[{parametre}]::text[]"


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
    conn: Executant,
    *,
    exclure_local: bool,
    budget: int = 4000,
    limite: int = 100,
    expurgateur: Expurgateur | None = None,
) -> list[Souvenir]:
    """Noyau ; `exclure_local` (moteur externe) : seulement les souvenirs « public » (`VERS_EXTERNE`)."""
    expurgateur = expurgateur or Expurgateur()
    lignes = await conn.fetch(
        f"SELECT {COLONNES} FROM memoires WHERE {_avec_tag(conn, '$1')}"  # noqa: S608 — constantes
        " AND valid_to IS NULL AND NOT archived"
        f" AND (NOT $2 OR (confidentialite <> 'local_uniquement' AND {condition_niveaux(conn, '$4')}))"
        " ORDER BY cree_le DESC, id LIMIT $3",
        TAG_NOYAU,
        exclure_local,
        limite,
        list(VERS_EXTERNE["noyau"]),
    )
    noyau = [s for s in (expurgateur.souvenir(_souvenir(r)) for r in lignes) if s is not None]
    return limiter_noyau(noyau, budget)


async def compter(conn: Executant) -> dict[str, int]:
    ligne = await conn.fetchrow(
        f"SELECT count(*) AS total, count(*) FILTER (WHERE {_avec_tag(conn, '$1')}) AS noyau,"  # noqa: S608 — constante
        " count(*) FILTER (WHERE confidentialite = 'local_uniquement') AS local,"
        " count(*) FILTER (WHERE niveau = 'public') AS public,"
        " count(*) FILTER (WHERE niveau = 'semi_prive') AS semi_prive,"
        " count(*) FILTER (WHERE niveau = 'prive') AS prive FROM memoires"
        " WHERE valid_to IS NULL AND NOT archived",
        TAG_NOYAU,
    )
    assert ligne is not None
    return {
        "total": ligne["total"],
        "noyau": ligne["noyau"],
        "local_uniquement": ligne["local"],
        **{n: int(ligne[n] or 0) for n in NIVEAUX},
    }


def niveaux_de(compte: dict[str, int]) -> dict[str, int]:
    """{"public": n, "semi_prive": n, "prive": n} extrait de `compter`."""
    return {n: int(compte.get(n, 0)) for n in NIVEAUX}


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
    blocs: list[Any] = field(default_factory=list)  # blocs.Bloc : textes éditables, toujours injectés
    souvenirs: list[Resultat] = field(default_factory=list)
    consultee: bool = True
    expurgateur: Expurgateur = field(default_factory=Expurgateur)
    domaines: list[dict[str, Any]] = field(default_factory=list)  # domaines de connaissance évoqués
    porte: str | None = None  # recherche sautée par la porte de rappel (`rappel.decider`) : sa raison

    def bloc(self) -> str:
        """Section mémoire des consignes système (noyau puis souvenirs), toujours expurgée."""
        if not self.consultee:
            return "\nSouvenirs pertinents :\n(mémoire indisponible pour ce message)"
        texte = ""
        if self.blocs:
            from .blocs import texte as texte_blocs

            texte += (
                f"\nBlocs de mémoire (tenus par l'utilisateur et JARVIS, prioritaires) :\n{texte_blocs(self.blocs)}\n"
            )
        if self.noyau:
            texte += f"\nNoyau (connaissances de référence, prioritaires) :\n{formater_noyau(self.noyau)}\n"
        if self.domaines:  # carte et niveau des domaines évoqués : avant les souvenirs
            from .connaissances import bloc_domaines

            texte += (
                f"\nDomaines de connaissance évoqués (carte conceptuelle, niveau) :\n{bloc_domaines(self.domaines)}\n"
            )
        if self.porte is not None and not self.souvenirs:
            texte += f"\nSouvenirs pertinents :\n(pas de recherche pour ce message : {self.porte})"
        else:
            texte += (
                f"\nSouvenirs pertinents (du plus pertinent au moins pertinent) :\n{formater_souvenirs(self.souvenirs)}"
            )
        return self.expurgateur.texte(texte)


# --- Parcourir la mémoire (vue Mémoire) et nouveautés -----------------------------------------------------

LIBELLES_ORIGINE = {
    "conversation": "conversations",
    "mission": "missions",
    "import_ia": "imports d'IA",
    "import_google": "synthèses Google",
    "profil": "profil",
    "ecoute": "écoute",
    "creation": "créations",
    "projet": "projets",
    "systeme": "système",
    "utilisateur": "vos notes",
    "connaissances": "connaissances",
    "autre": "autres",
}


async def parcourir(
    conn: Executant,
    *,
    origine: str | None = None,
    avant: datetime | None = None,
    depuis: datetime | None = None,
    limite: int = 50,
    exclure_local: bool = False,
    niveaux: Sequence[str] | None = None,
) -> list[Souvenir]:
    """Souvenirs vivants, du plus récent au plus ancien (pages : `avant` = date du dernier reçu).

    `niveaux` : seulement ces niveaux (ex. `VERS_EXTERNE["nouveautes"]` pour un moteur externe)."""
    conditions = ["valid_to IS NULL", "NOT archived"]
    valeurs: list[Any] = []
    if origine:
        valeurs.append(origine)
        conditions.append(f"origine = ${len(valeurs)}")
    if avant is not None:
        valeurs.append(avant)
        conditions.append(f"cree_le < ${len(valeurs)}")
    if depuis is not None:
        valeurs.append(depuis)
        conditions.append(f"cree_le >= ${len(valeurs)}")
    if exclure_local:
        conditions.append("confidentialite <> 'local_uniquement' AND niveau <> 'prive'")
    if niveaux is not None:
        valeurs.append(list(niveaux))
        conditions.append(condition_niveaux(conn, f"${len(valeurs)}"))
    valeurs.append(max(1, min(limite, 200)))
    lignes = await conn.fetch(
        f"SELECT {COLONNES} FROM memoires WHERE {' AND '.join(conditions)}"  # noqa: S608 — constantes
        f" ORDER BY cree_le DESC LIMIT ${len(valeurs)}",
        *valeurs,
    )
    return [_souvenir(ligne) for ligne in lignes]


async def par_origine(conn: Executant) -> dict[str, int]:
    lignes = await conn.fetch(
        "SELECT origine, count(*) AS n FROM memoires WHERE valid_to IS NULL AND NOT archived GROUP BY origine"
    )
    return {str(ligne["origine"]): int(ligne["n"]) for ligne in lignes}


def bloc_nouveautes(souvenirs: list[Souvenir], depuis: datetime, expurgateur: Expurgateur | None = None) -> str:
    """« Nouveautés de ta mémoire » depuis la dernière conversation : par origine, avec leurs thèmes."""
    expurgateur = expurgateur or Expurgateur()
    groupes: dict[str, list[str]] = {}
    for s in souvenirs:
        if expurgateur.mentionne(s.contenu):
            continue
        apercu = " ".join(s.contenu.split())
        apercu = apercu if len(apercu) <= 140 else apercu[:139].rsplit(" ", 1)[0] + "…"
        groupes.setdefault(s.origine, []).append(apercu)
    if not groupes:
        return ""
    lignes = [f"Nouveautés de ta mémoire depuis la dernière conversation ({depuis:%d/%m %H:%M} UTC) :"]
    for origine, apercus in groupes.items():
        lignes.append(f"- {LIBELLES_ORIGINE.get(origine, origine)} ({len(apercus)}) : " + " | ".join(apercus[:3]))
    return "\n".join(lignes)


# --- Niveau, remplacement (changement d'avis) et historique ----------------------------------------------------


class SouvenirAbsent(LookupError):
    """Aucun souvenir de cet identifiant."""


class DejaRemplace(ValueError):
    """Le souvenir a déjà été remplacé (ou n'est plus valide) : on agit sur sa version actuelle."""


_COLONNES_VERSION = f"{COLONNES}, valid_to, superseded_by"


async def lire(conn: Executant, ident: str) -> Souvenir | None:
    """Un souvenir (vivant ou non), avec son indicateur `remplace`."""
    ligne = await conn.fetchrow(f"SELECT {COLONNES} FROM memoires WHERE id = $1", ident)  # noqa: S608 — constante
    if ligne is None:
        return None
    return (await marquer_remplaces(conn, [_souvenir(ligne)]))[0]


async def marquer_remplaces(conn: Executant, souvenirs: Sequence[Souvenir]) -> list[Souvenir]:
    """`remplace` = le souvenir a une version antérieure (un autre souvenir pointe vers lui par `superseded_by`)."""
    if not souvenirs:
        return []
    ids = [s.id for s in souvenirs]
    if conn.dialecte == "sqlite":
        lignes = await conn.fetch(
            "SELECT DISTINCT superseded_by AS id FROM memoires"
            " WHERE superseded_by IN (SELECT value FROM json_each($1))",
            ids,
        )
    else:
        lignes = await conn.fetch(
            "SELECT DISTINCT superseded_by AS id FROM memoires WHERE superseded_by = ANY($1::uuid[])", ids
        )
    precedes = {str(r["id"]) for r in lignes}
    return [replace(s, remplace=s.id in precedes) for s in souvenirs]


async def changer_niveau(conn: Executant, ident: str, niveau: str) -> Souvenir | None:
    """Change le niveau d'un souvenir vivant (confidentialité synchronisée) ; None s'il est absent ou remplacé."""
    n = niveau_valide(niveau)
    ligne = await conn.fetchrow(
        "UPDATE memoires SET niveau = $2, confidentialite = $3, maj_le = now()"
        " WHERE id = $1 AND valid_to IS NULL AND superseded_by IS NULL RETURNING id",
        ident,
        n,
        confidentialite_de(n),
    )
    return None if ligne is None else await lire(conn, ident)


async def remplacer(
    base: Executant,
    ancien_id: str,
    contenu: str,
    *,
    vecteur: list[float] | None = None,
    modele: str | None = None,
    raison: str = "remplacement",
    niveau: str | None = None,
) -> str:
    """Remplace un fait (changement d'avis) : nouveau souvenir (même type, tags, source, origine, niveau sauf
    `niveau` donné), l'ancien reçoit `valid_to = now` et `superseded_by = nouveau`. Rien n'est effacé.

    La raison est gardée dans `canal_detail` du nouveau souvenir. Lève `SouvenirAbsent` ou `DejaRemplace`.
    """
    if hasattr(base, "acquire"):
        async with cast(Base, base).acquire() as c:
            return await remplacer(c, ancien_id, contenu, vecteur=vecteur, modele=modele, raison=raison, niveau=niveau)
    conn = cast(Connexion, base)
    async with conn.transaction():
        ancien = await conn.fetchrow(
            f"SELECT {_COLONNES_VERSION} FROM memoires WHERE id = $1",  # noqa: S608 — constante
            ancien_id,
        )
        if ancien is None:
            raise SouvenirAbsent(f"Souvenir introuvable : {ancien_id}")
        if ancien["superseded_by"] is not None or ancien["valid_to"] is not None:
            raise DejaRemplace("Ce souvenir a déjà été remplacé : modifiez sa version actuelle")
        a = _souvenir(ancien)
        nouveau = await ajouter(
            conn,
            contenu,
            type_=a.type,
            tags=a.tags,
            source=a.source,
            origine=a.origine,
            vecteur=vecteur,
            modele=modele,
            importance=a.importance,
            niveau=niveau if niveau is not None else a.niveau,
        )
        await conn.execute(
            "UPDATE memoires SET canal_detail = $2 WHERE id = $1", nouveau, (raison or "remplacement")[:200]
        )
        await conn.execute(
            "UPDATE memoires SET valid_to = now(), superseded_by = $2, maj_le = now() WHERE id = $1",
            ancien_id,
            nouveau,
        )
    return nouveau


@dataclass(frozen=True, slots=True)
class Version:
    souvenir: Souvenir
    valid_to: datetime | None
    superseded_by: str | None

    def en_dict(self) -> dict[str, Any]:
        return {
            **self.souvenir.en_dict(),
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "superseded_by": self.superseded_by,
        }


MAX_VERSIONS = 200


async def versions(conn: Executant, ident: str) -> list[Version]:
    """Historique d'un fait, de la plus ancienne version à l'actuelle (`superseded_by` suivi dans les deux sens)."""

    async def une(requete: str, valeur: str) -> Ligne | None:
        ligne: Ligne | None = await conn.fetchrow(
            f"SELECT {_COLONNES_VERSION} FROM memoires WHERE {requete} ORDER BY cree_le LIMIT 1",  # noqa: S608
            valeur,
        )
        return ligne

    depart = await une("id = $1", ident)
    if depart is None:
        return []
    chaine = [depart]
    vus = {str(depart["id"])}
    while len(chaine) < MAX_VERSIONS:  # vers le passé : qui pointait vers la plus ancienne connue
        avant = await une("superseded_by = $1", str(chaine[0]["id"]))
        if avant is None or str(avant["id"]) in vus:
            break
        vus.add(str(avant["id"]))
        chaine.insert(0, avant)
    while len(chaine) < MAX_VERSIONS and chaine[-1]["superseded_by"] is not None:  # vers l'actuelle
        apres = await une("id = $1", str(chaine[-1]["superseded_by"]))
        if apres is None or str(apres["id"]) in vus:
            break
        vus.add(str(apres["id"]))
        chaine.append(apres)
    souvenirs = await marquer_remplaces(conn, [_souvenir(r) for r in chaine])
    return [
        Version(s, r["valid_to"], str(r["superseded_by"]) if r["superseded_by"] is not None else None)
        for s, r in zip(souvenirs, chaine, strict=True)
    ]
