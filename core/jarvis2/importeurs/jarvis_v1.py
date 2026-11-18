"""Source d'import « jarvis_v1 » : l'assistant JARVIS v1 (FastAPI + PostgreSQL + pgvector).

Lecture seule côté JARVIS v1. Chaîne :
1. une sauvegarde `pg_dump -Fc` de JARVIS v1 (fournie par l'utilisateur) est restaurée dans une base d'attente
   isolée du PostgreSQL de JARVIS 2, sans la table des jetons d'accès ;
2. les tables utiles sont copiées avec le rôle applicatif, dans UNE transaction, identifiants et vecteurs compris,
   en écartant ce que la configuration locale exclut (données de tiers, par exemple) ;
3. un rapport (source / présents / exclus / nouveaux / mis à jour) est rangé dans la table `imports`.

Rejouable (rattrapage) : une ligne n'est mise à jour que si elle a changé, un message n'est jamais doublé.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import asyncpg

from ..config_locale import ExclusionsImport
from ..embeddings import Encodeur, vecteur_sql
from ..memoire import rechercher_multi

journal = logging.getLogger("jarvis2.importeurs.jarvis_v1")

NOM = "jarvis_v1"
BASE_ATTENTE = "import_jarvis_v1"
TABLES_EXCLUES = ("jetons",)  # empreintes des jetons d'accès de JARVIS v1 : jamais restaurées
MODELE_V1 = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"  # modèle des vecteurs de JARVIS v1

REQUETES_TEMOINS = (  # utilisées si la configuration locale n'en donne pas
    "Quels sont mes objectifs ?",
    "Parle-moi de mes projets",
    "Qu'as-tu appris récemment grâce à tes missions ?",
    "Comment est-ce que je préfère travailler ?",
    "Quelles décisions ai-je prises ?",
)


@dataclass(frozen=True)
class Table:
    source: str
    cible: str
    cle: tuple[str, ...]
    maj: str | None = "maj_le"  # colonne qui dit si une ligne a changé ; None = jamais mise à jour
    renommer: dict[str, str] = field(default_factory=dict)  # colonne source -> colonne cible
    ordre: str = ""
    # Colonnes de JARVIS 2 absentes de JARVIS v1 : expression SQL sur la table temporaire (colonnes en texte)
    complements: dict[str, str] = field(default_factory=dict)
    # Colonnes filtrées par la configuration locale : (colonne de source, colonne de contenu)
    filtre: tuple[str | None, str] | None = None
    # Références vers une ligne peut-être écartée : colonne -> table ; mise à NULL si la cible manque
    references: dict[str, str] = field(default_factory=dict)


# Ordre imposé par les clés étrangères
TABLES = (
    Table(
        "memoires",
        "memoires",
        ("id",),
        complements={
            "embedding_model": f"CASE WHEN embedding IS NOT NULL THEN '{MODELE_V1}' END",
            "valid_from": "cree_le::timestamptz",
            "observed_at": "cree_le::timestamptz",
        },
        filtre=("source", "contenu"),
    ),
    Table("conversations", "conversations", ("id",)),
    Table(
        "messages",
        "messages",
        ("ancien_id",),
        maj=None,
        renommer={"id": "ancien_id"},
        ordre="id",
        filtre=(None, "contenu"),
    ),
    Table("profil_reponses", "profil_reponses", ("question_id",), references={"souvenir_id": "memoires"}),
    Table("missions", "missions", ("id",), maj="termine_le"),  # une mission change sans « maj_le »
    Table("creations", "creations", ("id",)),
    Table("creation_versions", "creation_versions", ("creation_id", "version"), maj=None),
    Table("creation_donnees", "creation_donnees", ("id",)),
    Table("taches", "chantiers", ("id",)),
)


def empreinte(chemin: Path) -> str:
    h = hashlib.sha256()
    with chemin.open("rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def _docker(conteneur: str, *args: str, entree: bytes | None = None) -> bytes:
    resultat = subprocess.run(
        ["docker", "exec", "-i", conteneur, *args], input=entree, capture_output=True, check=False, timeout=600
    )
    if resultat.returncode != 0:
        raise RuntimeError(f"docker exec {' '.join(args[:2])} : {resultat.stderr.decode('utf-8', 'replace')[:500]}")
    return resultat.stdout


def restaurer_sauvegarde(sauvegarde: Path, conteneur: str, proprio: str) -> None:
    """(Re)crée la base d'attente à partir d'une sauvegarde `pg_dump -Fc`, sans les tables exclues."""
    # Fichiers temporaires DANS le conteneur PostgreSQL, effacés à la fin
    distant, liste = "/tmp/import-jarvis-v1.dump", "/tmp/import-jarvis-v1.liste"  # noqa: S108
    subprocess.run(
        ["docker", "cp", str(sauvegarde), f"{conteneur}:{distant}"], check=True, capture_output=True, timeout=600
    )
    try:
        psql = ("psql", "-v", "ON_ERROR_STOP=1", "-q", "-U", proprio, "-d", "postgres")
        _docker(conteneur, *psql, "-c", f"DROP DATABASE IF EXISTS {BASE_ATTENTE}")
        _docker(conteneur, *psql, "-c", f"CREATE DATABASE {BASE_ATTENTE}")
        _docker(conteneur, *psql, "-c", f"REVOKE ALL ON DATABASE {BASE_ATTENTE} FROM PUBLIC")
        sommaire = _docker(conteneur, "pg_restore", "-l", distant).decode("utf-8", "replace").splitlines()
        # Tout objet qui porte le nom d'une table exclue (table, données, séquence, index) est écarté
        gardes = [
            ligne for ligne in sommaire if not any(f" {t} " in f"{ligne} " or f" {t}_" in ligne for t in TABLES_EXCLUES)
        ]
        _docker(conteneur, "sh", "-c", f"cat > {liste}", entree="\n".join(gardes).encode())
        _docker(conteneur, "pg_restore", "-U", proprio, "-d", BASE_ATTENTE, "--no-owner", "--no-privileges",
                "--exit-on-error", "-L", liste, distant)  # fmt: skip
    finally:
        _docker(conteneur, "rm", "-f", distant, liste)


async def _colonnes(conn: asyncpg.Connection, table: str) -> dict[str, str]:
    lignes = await conn.fetch(
        "SELECT attname, format_type(atttypid, atttypmod) AS type FROM pg_attribute"
        " WHERE attrelid = $1::regclass AND attnum > 0 AND NOT attisdropped ORDER BY attnum",
        table,
    )
    return {r["attname"]: r["type"] for r in lignes}


def _ident(nom: str) -> str:
    return '"' + nom.replace('"', '""') + '"'


async def importer_table(
    source: asyncpg.Connection, cible: asyncpg.Connection, t: Table, exclusions: ExclusionsImport
) -> dict[str, int]:
    """Copie une table de la base d'attente vers JARVIS 2 (dans la transaction ouverte sur `cible`)."""
    types_cible = await _colonnes(cible, t.cible)
    colonnes_source = await _colonnes(source, t.source)
    paires = [(s, t.renommer.get(s, s)) for s in colonnes_source if t.renommer.get(s, s) in types_cible]
    manquantes = [c for c in colonnes_source if t.renommer.get(c, c) not in types_cible]
    if manquantes:
        raise RuntimeError(f"{t.source} : colonnes sans équivalent dans {t.cible} : {', '.join(manquantes)}")
    # Tout passe en texte puis est re-typé côté cible : vecteurs, tsvector, tableaux et JSON arrivent intacts.
    select = ", ".join(f"{_ident(s)}::text" for s, _ in paires)
    ordre = f" ORDER BY {_ident(t.ordre)}" if t.ordre else ""
    lignes = await source.fetch(f"SELECT {select} FROM {_ident(t.source)}{ordre}")  # noqa: S608 — noms vérifiés
    cols = [c for _, c in paires]
    exclus = 0
    if t.filtre is not None:
        i_source = cols.index(t.filtre[0]) if t.filtre[0] else None
        i_contenu = cols.index(t.filtre[1])
        gardees = [
            r for r in lignes if not exclusions.exclut(r[i_source] if i_source is not None else None, r[i_contenu])
        ]
        exclus = len(lignes) - len(gardees)
        lignes = gardees
    tmp = f"import_{t.cible}"
    await cible.execute(
        f"CREATE TEMP TABLE {tmp} (rang serial, {', '.join(f'{_ident(c)} text' for c in cols)}) ON COMMIT DROP"
    )
    if lignes:
        await cible.copy_records_to_table(tmp, records=[tuple(r) for r in lignes], columns=cols)
    for colonne, table in t.references.items():  # référence vers une ligne écartée : retirée, pas d'échec
        await cible.execute(
            f"UPDATE {tmp} SET {_ident(colonne)} = NULL WHERE {_ident(colonne)} IS NOT NULL"  # noqa: S608
            f" AND NOT EXISTS (SELECT 1 FROM {_ident(table)} r WHERE r.id::text = {tmp}.{_ident(colonne)})"
        )
    toutes = cols + list(t.complements)
    expressions = [f"{_ident(c)}::{types_cible[c]}" for c in cols]
    expressions += [f"({expr})::{types_cible[c]}" for c, expr in t.complements.items()]
    conflit = ", ".join(_ident(c) for c in t.cle)
    filtre_conflit = " WHERE ancien_id IS NOT NULL" if t.cle == ("ancien_id",) else ""
    if t.maj:
        mises = ", ".join(f"{_ident(c)} = EXCLUDED.{_ident(c)}" for c in toutes if c not in t.cle)
        change = f"{_ident(t.cible)}.{_ident(t.maj)} IS DISTINCT FROM EXCLUDED.{_ident(t.maj)}"
        action = f"DO UPDATE SET {mises} WHERE {change}"
    else:
        action = "DO NOTHING"
    resultats = await cible.fetch(
        f"INSERT INTO {_ident(t.cible)} ({', '.join(map(_ident, toutes))})"  # noqa: S608 — noms vérifiés
        f" SELECT {', '.join(expressions)} FROM {tmp} ORDER BY rang"
        f" ON CONFLICT ({conflit}){filtre_conflit} {action} RETURNING (xmax = 0) AS nouveau"
    )
    jointure = " AND ".join(f"c.{_ident(k)}::text = s.{_ident(k)}" for k in t.cle)
    presents = await cible.fetchval(
        f"SELECT count(*) FROM {tmp} s WHERE EXISTS (SELECT 1 FROM {_ident(t.cible)} c WHERE {jointure})"  # noqa: S608
    )
    nouveaux = sum(1 for r in resultats if r["nouveau"])
    return {
        "source": len(lignes) + exclus,
        "presents": int(presents),
        "exclus": exclus,
        "nouveaux": nouveaux,
        "mis_a_jour": len(resultats) - nouveaux,
    }


@dataclass
class Rapport:
    source: str
    empreinte: str
    comptes: dict[str, dict[str, int]]

    @property
    def complet(self) -> bool:
        """Chaque ligne de la source est présente, ou écartée volontairement par la configuration locale."""
        return all(c["presents"] + c["exclus"] == c["source"] for c in self.comptes.values())

    def texte(self) -> str:
        lignes = [
            f"Import {NOM} de {self.source} (SHA-256 {self.empreinte[:16]}…)",
            f"{'table':<20}{'source':>8}{'présents':>10}{'exclus':>8}{'nouveaux':>10}{'mis à jour':>12}",
        ]
        for table, c in self.comptes.items():
            lignes.append(
                f"{table:<20}{c['source']:>8}{c['presents']:>10}{c['exclus']:>8}{c['nouveaux']:>10}{c['mis_a_jour']:>12}"
            )
        lignes.append(
            "Complet : chaque ligne de la source est présente ou volontairement exclue."
            if self.complet
            else "INCOMPLET : des lignes de la source manquent (voir « présents »)."
        )
        return "\n".join(lignes)


async def importer(
    url_attente: str,
    url_app: str,
    source: str,
    empreinte_source: str,
    exclusions: ExclusionsImport | None = None,
) -> Rapport:
    """Copie toutes les tables en une transaction ; tout ou rien."""
    exclusions = exclusions or ExclusionsImport()
    src = await asyncpg.connect(url_attente)
    dst = await asyncpg.connect(url_app)
    try:
        async with src.transaction(readonly=True, isolation="repeatable_read"), dst.transaction():
            comptes = {}
            for t in TABLES:
                comptes[t.cible] = await importer_table(src, dst, t, exclusions)
                journal.info("%s : %s", t.cible, comptes[t.cible])
            await dst.execute(
                "INSERT INTO imports (source, empreinte, comptes) VALUES ($1, $2, $3::jsonb)",
                f"{NOM}:{source}",
                empreinte_source,
                json.dumps(comptes),
            )
    finally:
        await src.close()
        await dst.close()
    return Rapport(source, empreinte_source, comptes)


@dataclass
class Verification:
    similarites: list[float]
    requetes: list[dict[str, Any]]

    @property
    def vecteurs_identiques(self) -> bool:
        return bool(self.similarites) and min(self.similarites) >= 0.999

    @property
    def recherches_identiques(self) -> bool:
        return all(r["identiques"] for r in self.requetes)

    def texte(self) -> str:
        minimum = min(self.similarites, default=0)
        lignes = [
            f"Vecteurs : {len(self.similarites)} souvenirs ré-encodés, cosinus minimal {minimum:.6f} -> "
            f"{'même modèle' if self.vecteurs_identiques else 'ÉCART'}"
        ]
        for r in self.requetes:
            etat = "identiques" if r["identiques"] else "DIFFÉRENTS"
            lignes.append(f"  [{'privé' if r['local'] else 'externe'}] {r['requete']} : 5 premiers {etat}")
        return "\n".join(lignes)


async def verifier(
    url_attente: str, url_app: str, encodeur: Encodeur, requetes: Sequence[str] = (), echantillon: int = 25
) -> Verification:
    """Même modèle d'embeddings, et même classement de recherche que sur les données de JARVIS v1.

    La base d'attente n'a pas les colonnes de la mémoire v2 : elle reçoit une vue équivalente le temps de la
    comparaison (transaction annulée à la fin, la base d'attente reste telle que restaurée).
    """
    src = await asyncpg.connect(url_attente)
    dst = await asyncpg.connect(url_app)
    try:
        lignes = await dst.fetch(
            "SELECT id, contenu, embedding::text AS v FROM memoires WHERE embedding_model = $1"
            " ORDER BY md5(id::text) LIMIT $2",
            encodeur.nom_modele,
            echantillon,
        )
        similarites = []
        for ligne in lignes:
            nouveau = vecteur_sql(await encodeur.encoder(ligne["contenu"]))
            sim = await dst.fetchval("SELECT 1 - ($1::text::vector <=> $2::text::vector)", nouveau, ligne["v"])
            similarites.append(float(sim))
        resultats = []
        async with src.transaction():
            await src.execute(
                "ALTER TABLE memoires ADD COLUMN embedding_model text, ADD COLUMN valid_to timestamptz,"
                " ADD COLUMN archived boolean NOT NULL DEFAULT false"
            )
            await src.execute("UPDATE memoires SET embedding_model = $1 WHERE embedding IS NOT NULL", MODELE_V1)
            for q in requetes or REQUETES_TEMOINS:
                for local in (False, True):
                    a = await rechercher_multi(src, encodeur, q, exclure_local=not local)
                    b = await rechercher_multi(dst, encodeur, q, exclure_local=not local)
                    ids_a = [r.souvenir.id for r in a[:5]]
                    ids_b = [r.souvenir.id for r in b[:5]]
                    resultats.append(
                        {"requete": q, "local": local, "identiques": ids_a == ids_b, "v1": ids_a, "jarvis2": ids_b}
                    )
            raise _Annuler
    except _Annuler:
        pass
    finally:
        await src.close()
        await dst.close()
    return Verification(similarites, resultats)


class _Annuler(Exception):
    """Annule la transaction de comparaison sur la base d'attente."""
