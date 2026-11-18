"""Sauvegarde chiffrée de JARVIS 2, à garder hors du PC, et vérification par restauration réelle.

Archive `.jarvis2` : « JARVIS2S1 » + sel scrypt (16 octets) + nonce (12) + AES-256-GCM(tar.gz). Le tar contient :
- la base : copie cohérente du fichier SQLite (API de sauvegarde de SQLite), ou `pg_dump -Fc` de PostgreSQL ;
- la configuration locale (`config.toml`) et le dossier `recettes/` ;
- `manifeste.json` : version, date, moteur, nombre de lignes par table, dernière empreinte du journal d'audit.
Le coffre des clés d'API n'est PAS inclus (chiffré par Windows pour ce compte et ce PC) : les clés se ressaisissent.

`verifier` déchiffre, restaure dans une base TEMPORAIRE et compare : mêmes nombres de lignes, chaîne d'audit intacte
et même dernière empreinte. Une sauvegarde n'est réputée bonne qu'une fois vérifiée.
"""

from __future__ import annotations

import io
import json
import os
import secrets
import sqlite3
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from . import __version__

MAGIQUE = b"JARVIS2S1"
TABLES = ("memoires", "conversations", "messages", "appareils", "audit", "memory_blocks", "missions", "creations")


class ErreurSauvegarde(RuntimeError):
    pass


def _cle(phrase: str, sel: bytes) -> bytes:
    if len(phrase) < 12:
        raise ErreurSauvegarde("Phrase de passe trop courte (12 caractères au moins)")
    return Scrypt(salt=sel, length=32, n=2**15, r=8, p=1).derive(phrase.encode())


def chiffrer(donnees: bytes, phrase: str) -> bytes:
    sel, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    return MAGIQUE + sel + nonce + AESGCM(_cle(phrase, sel)).encrypt(nonce, donnees, MAGIQUE)


def dechiffrer(contenu: bytes, phrase: str) -> bytes:
    if not contenu.startswith(MAGIQUE):
        raise ErreurSauvegarde("Ce fichier n'est pas une sauvegarde de JARVIS 2")
    debut = len(MAGIQUE)
    sel, nonce, chiffre = contenu[debut : debut + 16], contenu[debut + 16 : debut + 28], contenu[debut + 28 :]
    try:
        return AESGCM(_cle(phrase, sel)).decrypt(nonce, chiffre, MAGIQUE)
    except Exception as exc:  # InvalidTag : mauvaise phrase ou fichier altéré
        raise ErreurSauvegarde("Phrase de passe incorrecte ou sauvegarde altérée") from exc


@dataclass
class Manifeste:
    version: str
    date: str
    stockage: str
    comptes: dict[str, int] = field(default_factory=dict)
    audit_dernier: str | None = None


def _comptes_sqlite(chemin: Path) -> tuple[dict[str, int], str | None]:
    conn = sqlite3.connect(str(chemin))
    try:
        comptes = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}  # noqa: S608
        ligne = conn.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
        return comptes, ligne[0] if ligne else None
    finally:
        conn.close()


def _ajouter(archive: tarfile.TarFile, nom: str, donnees: bytes) -> None:
    info = tarfile.TarInfo(nom)
    info.size = len(donnees)
    info.mtime = int(datetime.now(UTC).timestamp())
    archive.addfile(info, io.BytesIO(donnees))


def _dump_postgres(conteneur: str, utilisateur: str, base: str) -> bytes:
    """`pg_dump -Fc` dans le conteneur PostgreSQL (lecture seule de la base)."""
    resultat = subprocess.run(
        ["docker", "exec", conteneur, "pg_dump", "-U", utilisateur, "-Fc", base], capture_output=True, check=False
    )
    if resultat.returncode != 0:
        raise ErreurSauvegarde(f"pg_dump impossible : {resultat.stderr.decode('utf-8', 'replace')[:300]}")
    return resultat.stdout


def creer(
    destination: Path,
    phrase: str,
    stockage: str,
    chemin_sqlite: Path | None,
    dossier_config: Path,
    postgres: tuple[str, str, str] | None = None,
    comptes_pg: dict[str, int] | None = None,
    audit_pg: str | None = None,
) -> Path:
    """Écrit `jarvis2-AAAAMMJJ-HHMMSS.jarvis2` dans `destination` (dossier hors du PC de préférence)."""
    destination.mkdir(parents=True, exist_ok=True)
    tampon = io.BytesIO()
    with (
        tempfile.TemporaryDirectory(prefix="jarvis2-sauvegarde-") as tmp,
        tarfile.open(fileobj=tampon, mode="w:gz") as archive,
    ):
        if stockage == "sqlite":
            if chemin_sqlite is None or not chemin_sqlite.is_file():
                raise ErreurSauvegarde("Base SQLite introuvable")
            copie = Path(tmp) / "jarvis2.db"
            source, cible = sqlite3.connect(str(chemin_sqlite)), sqlite3.connect(str(copie))
            try:
                source.backup(cible)  # copie cohérente même si le Core écrit en même temps
            finally:
                source.close()
                cible.close()
            comptes, audit = _comptes_sqlite(copie)
            _ajouter(archive, "base/jarvis2.db", copie.read_bytes())
        else:
            if postgres is None:
                raise ErreurSauvegarde("Paramètres PostgreSQL manquants")
            _ajouter(archive, "base/jarvis2.dump", _dump_postgres(*postgres))
            comptes, audit = comptes_pg or {}, audit_pg
        config = dossier_config / "config.toml"
        if config.is_file():
            _ajouter(archive, "config/config.toml", config.read_bytes())
        recettes = dossier_config / "recettes"
        if recettes.is_dir():
            for f in sorted(recettes.glob("*.y*ml")):
                _ajouter(archive, f"config/recettes/{f.name}", f.read_bytes())
        manifeste = Manifeste(__version__, datetime.now(UTC).isoformat(), stockage, comptes, audit)
        _ajouter(archive, "manifeste.json", json.dumps(manifeste.__dict__, ensure_ascii=False, indent=2).encode())
    fichier = destination / f"jarvis2-{datetime.now(UTC):%Y%m%d-%H%M%S}.jarvis2"
    temporaire = fichier.with_suffix(".partiel")
    temporaire.write_bytes(chiffrer(tampon.getvalue(), phrase))
    os.replace(temporaire, fichier)  # jamais de sauvegarde à moitié écrite sous le nom final
    return fichier


def ouvrir(fichier: Path, phrase: str) -> tuple[Manifeste, tarfile.TarFile]:
    # archive en mémoire (BytesIO) : aucun fichier ouvert à fermer
    archive = tarfile.open(fileobj=io.BytesIO(dechiffrer(fichier.read_bytes(), phrase)), mode="r:gz")  # noqa: SIM115
    brut = archive.extractfile("manifeste.json")
    if brut is None:
        raise ErreurSauvegarde("Manifeste absent")
    return Manifeste(**json.loads(brut.read())), archive


def verifier_sqlite(fichier: Path, phrase: str) -> dict[str, Any]:
    """Restaure la base dans un dossier temporaire, puis compare au manifeste (lignes, chaîne d'audit)."""
    import asyncio

    from .db_sqlite import BaseSQLite
    from .securite import audit

    manifeste, archive = ouvrir(fichier, phrase)
    if manifeste.stockage != "sqlite":
        raise ErreurSauvegarde(
            "Sauvegarde PostgreSQL : vérifiez-la avec `jarvis2 sauvegarde verifier` en mode PostgreSQL"
        )
    brut = archive.extractfile("base/jarvis2.db")
    if brut is None:
        raise ErreurSauvegarde("Base absente de la sauvegarde")
    with tempfile.TemporaryDirectory(prefix="jarvis2-verification-") as tmp:
        base = Path(tmp) / "restauree.db"
        base.write_bytes(brut.read())
        comptes, dernier = _comptes_sqlite(base)

        async def chaine() -> int | None:
            b = await BaseSQLite.ouvrir(base)
            try:
                return await audit.verifier(b)
            finally:
                await b.close()

        rompue = asyncio.run(chaine())
    ecarts = {
        t: (manifeste.comptes.get(t), comptes.get(t)) for t in TABLES if manifeste.comptes.get(t) != comptes.get(t)
    }
    fichiers = [m.name for m in archive.getmembers()]
    return {
        "date": manifeste.date,
        "version": manifeste.version,
        "comptes": comptes,
        "ecarts": ecarts,
        "audit_intact": rompue is None and dernier == manifeste.audit_dernier,
        "fichiers": fichiers,
        "valide": not ecarts and rompue is None and dernier == manifeste.audit_dernier,
    }


def rotation(dossier: Path, garder: int = 7) -> list[Path]:
    """Garde les `garder` sauvegardes les plus récentes du dossier ; renvoie celles retirées."""
    toutes = sorted(dossier.glob("jarvis2-*.jarvis2"))
    retirees = toutes[:-garder] if garder > 0 else []
    for f in retirees:
        f.unlink()
    return retirees


def _psql(conteneur: str, utilisateur: str, base: str, requete: str) -> str:
    resultat = subprocess.run(
        ["docker", "exec", conteneur, "psql", "-U", utilisateur, "-d", base, "-tAc", requete],
        capture_output=True,
        check=False,
    )
    if resultat.returncode != 0:
        raise ErreurSauvegarde(f"psql : {resultat.stderr.decode('utf-8', 'replace')[:300]}")
    return resultat.stdout.decode().strip()


def verifier_postgres(fichier: Path, phrase: str, conteneur: str, utilisateur: str) -> dict[str, Any]:
    """Restaure le `pg_dump` dans une base TEMPORAIRE du même serveur, compare au manifeste, puis l'efface."""
    manifeste, archive = ouvrir(fichier, phrase)
    if manifeste.stockage != "postgres":
        raise ErreurSauvegarde("Sauvegarde SQLite : vérifiez-la en mode SQLite")
    brut = archive.extractfile("base/jarvis2.dump")
    if brut is None:
        raise ErreurSauvegarde("Base absente de la sauvegarde")
    temporaire = "jarvis2_verification_sauvegarde"
    _psql(conteneur, utilisateur, "postgres", f"DROP DATABASE IF EXISTS {temporaire} WITH (FORCE)")
    _psql(conteneur, utilisateur, "postgres", f"CREATE DATABASE {temporaire}")
    try:
        restauration = subprocess.run(
            ["docker", "exec", "-i", conteneur, "pg_restore", "-U", utilisateur, "-d", temporaire, "--no-owner"],
            input=brut.read(),
            capture_output=True,
            check=False,
        )
        if restauration.returncode not in (0, 1):  # 1 : avertissements non bloquants de pg_restore
            raise ErreurSauvegarde(f"pg_restore : {restauration.stderr.decode('utf-8', 'replace')[:300]}")
        comptes = {t: int(_psql(conteneur, utilisateur, temporaire, f"SELECT count(*) FROM {t}")) for t in TABLES}  # noqa: S608
        rompue = _psql(conteneur, utilisateur, temporaire, "SELECT audit_verifier()")
        dernier = _psql(conteneur, utilisateur, temporaire, "SELECT hash FROM audit ORDER BY id DESC LIMIT 1") or None
    finally:
        _psql(conteneur, utilisateur, "postgres", f"DROP DATABASE IF EXISTS {temporaire} WITH (FORCE)")
    ecarts = {
        t: (manifeste.comptes.get(t), comptes.get(t)) for t in TABLES if manifeste.comptes.get(t) != comptes.get(t)
    }
    intact = rompue == "" and dernier == manifeste.audit_dernier
    return {
        "date": manifeste.date,
        "version": manifeste.version,
        "comptes": comptes,
        "ecarts": ecarts,
        "audit_intact": intact,
        "fichiers": [m.name for m in archive.getmembers()],
        "valide": not ecarts and intact,
    }
