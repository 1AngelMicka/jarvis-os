"""Import de l'héritage de l'ancien JARVIS, **en lecture seule** côté ancien JARVIS.

Chaîne :
1. une sauvegarde quotidienne de l'ancien Core (`pg_dump -Fc`, copiée sur le disque de données) est restaurée dans une base
   d'attente isolée `ancien_jarvis` (sans la table des jetons d'accès), dans le PostgreSQL de JARVIS 2 ;
2. les tables utiles sont copiées dans la base de JARVIS 2 avec le rôle applicatif, dans UNE transaction,
   identifiants et vecteurs compris ;
3. un rapport de comptage (source / présents / nouveaux / mis à jour) est rangé dans la table `imports`.

L'import est rejouable (rattrapage de la phase 9) : une ligne déjà présente n'est mise à jour que si elle a
changé depuis (`maj_le` plus récent) ; un message n'est jamais doublé (`ancien_id`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import asyncpg

journal = logging.getLogger("jarvis2.heritage")

BASE_ATTENTE = "ancien_jarvis"
TABLES_EXCLUES = ("jetons",)  # empreintes des jetons d'accès de l'ancien JARVIS : jamais restaurées


@dataclass(frozen=True)
class Table:
    source: str
    cible: str
    cle: tuple[str, ...]
    maj: str | None = "maj_le"  # colonne qui dit si une ligne a changé ; None = jamais mise à jour
    renommer: dict[str, str] = field(default_factory=dict)  # colonne source -> colonne cible
    ordre: str = ""


# Ordre imposé par les clés étrangères
TABLES = (
    Table("memoires", "memoires", ("id",)),
    Table("conversations", "conversations", ("id",)),
    Table("messages", "messages", ("ancien_id",), maj=None, renommer={"id": "ancien_id"}, ordre="id"),
    Table("profil_reponses", "profil_reponses", ("question_id",)),
    Table("missions", "missions", ("id",), maj=None),
    Table("creations", "creations", ("id",)),
    Table("creation_versions", "creation_versions", ("creation_id", "version"), maj=None),
    Table("creation_donnees", "creation_donnees", ("id",)),
    Table("taches", "chantiers", ("id",)),
)
# Les missions changent sans `maj_le` : on compare la fin de mission
MAJ_PARTICULIERES = {"missions": "termine_le"}


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
    distant, liste = "/tmp/ancien-jarvis.dump", "/tmp/ancien-jarvis.liste"  # noqa: S108
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
        _docker(
            conteneur,
            "pg_restore",
            "-U",
            proprio,
            "-d",
            BASE_ATTENTE,
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
            "-L",
            liste,
            distant,
        )
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


async def importer_table(source: asyncpg.Connection, cible: asyncpg.Connection, t: Table) -> dict[str, int]:
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
    tmp = f"import_{t.cible}"
    cols = [c for _, c in paires]
    await cible.execute(
        f"CREATE TEMP TABLE {tmp} (rang serial, {', '.join(f'{_ident(c)} text' for c in cols)}) ON COMMIT DROP"
    )
    if lignes:
        await cible.copy_records_to_table(tmp, records=[tuple(r) for r in lignes], columns=cols)
    maj = MAJ_PARTICULIERES.get(t.cible, t.maj)
    conflit = ", ".join(_ident(c) for c in t.cle)
    filtre_conflit = " WHERE ancien_id IS NOT NULL" if t.cle == ("ancien_id",) else ""
    if maj:
        mises = ", ".join(f"{_ident(c)} = EXCLUDED.{_ident(c)}" for c in cols if c not in t.cle)
        action = f"DO UPDATE SET {mises} WHERE {_ident(t.cible)}.{_ident(maj)} IS DISTINCT FROM EXCLUDED.{_ident(maj)}"
    else:
        action = "DO NOTHING"
    valeurs = ", ".join(f"{_ident(c)}::{types_cible[c]}" for c in cols)
    resultats = await cible.fetch(
        f"INSERT INTO {_ident(t.cible)} ({', '.join(map(_ident, cols))})"  # noqa: S608 — noms vérifiés
        f" SELECT {valeurs} FROM {tmp} ORDER BY rang"
        f" ON CONFLICT ({conflit}){filtre_conflit} {action} RETURNING (xmax = 0) AS nouveau"
    )
    jointure = " AND ".join(f"c.{_ident(k)}::text = s.{_ident(k)}" for k in t.cle)
    presents = await cible.fetchval(
        f"SELECT count(*) FROM {tmp} s WHERE EXISTS (SELECT 1 FROM {_ident(t.cible)} c WHERE {jointure})"  # noqa: S608
    )
    nouveaux = sum(1 for r in resultats if r["nouveau"])
    return {
        "source": len(lignes),
        "presents": int(presents),
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
        return all(c["presents"] == c["source"] for c in self.comptes.values())

    def texte(self) -> str:
        lignes = [
            f"Import de {self.source} (SHA-256 {self.empreinte[:16]}…)",
            f"{'table':<20}{'source':>8}{'présents':>10}{'nouveaux':>10}{'mis à jour':>12}",
        ]
        for table, c in self.comptes.items():
            lignes.append(f"{table:<20}{c['source']:>8}{c['presents']:>10}{c['nouveaux']:>10}{c['mis_a_jour']:>12}")
        lignes.append(
            "Complet : chaque ligne de la source est présente."
            if self.complet
            else "INCOMPLET : des lignes de la source manquent (voir « présents »)."
        )
        return "\n".join(lignes)


async def importer(url_attente: str, url_app: str, source: str, empreinte_source: str) -> Rapport:
    """Copie toutes les tables de l'héritage en une transaction ; tout ou rien."""
    src = await asyncpg.connect(url_attente)
    dst = await asyncpg.connect(url_app)
    try:
        async with src.transaction(readonly=True, isolation="repeatable_read"), dst.transaction():
            comptes = {}
            for t in TABLES:
                comptes[t.cible] = await importer_table(src, dst, t)
                journal.info("%s : %s", t.cible, comptes[t.cible])
            await dst.execute(
                "INSERT INTO imports (source, empreinte, comptes) VALUES ($1, $2, $3::jsonb)",
                source,
                empreinte_source,
                json.dumps(comptes),
            )
    finally:
        await src.close()
        await dst.close()
    return Rapport(source, empreinte_source, comptes)


REQUETES_TEMOINS = (
    "Quels sont mes objectifs ?",
    "Parle-moi de mes projets de développement",
    "Qu'as-tu appris sur la neuroplasticité ?",
    "Comment est-ce que je préfère travailler ?",
    "Quelles sont mes valeurs et qu'est-ce qui compte pour moi ?",
    "Quelle est l'architecture de JARVIS et où tourne le Core ?",
    "Qu'as-tu appris récemment grâce à tes missions ?",
    "Quelles décisions ai-je prises sur la sécurité ?",
)


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
        lignes = [
            f"Vecteurs : {len(self.similarites)} souvenirs ré-encodés, cosinus minimal "
            f"{min(self.similarites, default=0):.6f} -> {'même modèle' if self.vecteurs_identiques else 'ÉCART'}"
        ]
        for r in self.requetes:
            etat = "identiques" if r["identiques"] else "DIFFÉRENTS"
            lignes.append(f"  [{'privé' if r['local'] else 'externe'}] {r['requete']} : 5 premiers {etat}")
        return "\n".join(lignes)


async def verifier(url_attente: str, url_app: str, encodeur: Any, echantillon: int = 25) -> Verification:
    """Même modèle d'embeddings, et même classement de recherche que sur les données de l'ancien JARVIS."""
    from .embeddings import vecteur_sql
    from .memoire import rechercher_multi

    src = await asyncpg.connect(url_attente)
    dst = await asyncpg.connect(url_app)
    try:
        lignes = await dst.fetch(
            "SELECT id, contenu, embedding::text AS v FROM memoires WHERE embedding IS NOT NULL"
            " ORDER BY md5(id::text) LIMIT $1",
            echantillon,
        )
        similarites = []
        for ligne in lignes:
            nouveau = vecteur_sql(await encodeur.encoder(ligne["contenu"]))
            sim = await dst.fetchval("SELECT 1 - ($1::text::vector <=> $2::text::vector)", nouveau, ligne["v"])
            similarites.append(float(sim))
        requetes = []
        for q in REQUETES_TEMOINS:
            for local in (False, True):
                a = await rechercher_multi(src, encodeur, q, exclure_local=not local)
                b = await rechercher_multi(dst, encodeur, q, exclure_local=not local)
                ids_a = [r.souvenir.id for r in a[:5]]
                ids_b = [r.souvenir.id for r in b[:5]]
                requetes.append(
                    {"requete": q, "local": local, "identiques": ids_a == ids_b, "ancien": ids_a, "jarvis2": ids_b}
                )
    finally:
        await src.close()
        await dst.close()
    return Verification(similarites, requetes)


def resume_comptes(comptes: dict[str, Any]) -> str:
    return ", ".join(f"{t} {c['presents']}/{c['source']}" for t, c in comptes.items())
