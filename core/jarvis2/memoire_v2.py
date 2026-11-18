"""Mémoire v2 : classement (RRF + importance), accès, oubli par archivage, bascule de modèle, export, banc.

Rien n'est jamais effacé : un souvenir oublié est ARCHIVÉ (réversible), un souvenir dépassé est REMPLACÉ
(`valid_to`, `superseded_by`).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from .db import Executant
from .db_sqlite import vecteur_octets
from .embeddings import Encodeur, vecteur_sql
from .memoire import Resultat, _avec_tag

journal = logging.getLogger("jarvis2.memoire")

Classement = Literal["v1", "v2"]
K_RRF = 60
FUSEAU = ZoneInfo("Europe/Paris")


# --- Classement v2 ------------------------------------------------------------------------------------------


def classer_v2(resultats: Sequence[Resultat]) -> list[Resultat]:
    """Fusion des rangs (RRF, k = 60) des deux signaux, mêlée au score hybride, pondérée par l'importance.

    score = (0,6 × hybride + 0,4 × RRF normalisé) × (0,85 + 0,3 × importance). Le RRF récompense un souvenir très
    bien classé par UN des deux signaux (mots exacts ou sens) ; l'importance départage deux souvenirs proches.
    La récence reste appliquée à la fusion des sous-questions (`memoire.bonus`).
    """
    if not resultats:
        return []
    rang_vecteur = {r.souvenir.id: i for i, r in enumerate(sorted(resultats, key=lambda r: -r.similarite), 1)}
    textuels = sorted((r for r in resultats if r.texte > 0), key=lambda r: -r.texte)
    rang_texte = {r.souvenir.id: i for i, r in enumerate(textuels, 1)}
    maximum = 2 / (K_RRF + 1)
    sortie = []
    for r in resultats:
        ident = r.souvenir.id
        rrf = 1 / (K_RRF + rang_vecteur[ident]) + (1 / (K_RRF + rang_texte[ident]) if ident in rang_texte else 0)
        score = (0.6 * r.score + 0.4 * rrf / maximum) * (0.85 + 0.3 * r.souvenir.importance)
        sortie.append(replace(r, score=round(score, 4)))
    sortie.sort(key=lambda r: (-r.score, -r.souvenir.cree_le.timestamp()))
    return sortie


# --- Accès et oubli -----------------------------------------------------------------------------------------


def _parmi(conn: Executant, colonne: str, parametre: str) -> str:
    if conn.dialecte == "sqlite":
        return f"{colonne} IN (SELECT value FROM json_each({parametre}))"  # noqa: S608 — noms constants
    return f"{colonne} = ANY({parametre}::uuid[])"


async def noter_acces(conn: Executant, ids: Sequence[str]) -> None:
    """Souvenirs injectés dans une réponse : compteur et date du dernier accès (base de l'oubli)."""
    if not ids:
        return
    await conn.execute(
        "UPDATE memoires SET access_count = access_count + 1, last_accessed_at = now()"  # noqa: S608 — constantes
        f" WHERE {_parmi(conn, 'id', '$1')}",
        list(ids),
    )


async def oublier(
    conn: Executant, jours: int = 180, importance_max: float = 0.3, maintenant: datetime | None = None
) -> int:
    """Archive (sans effacer) les souvenirs peu importants, jamais consultés, plus vieux que `jours`.

    Jamais : ce que l'utilisateur a dit lui-même (origine utilisateur, profil), le noyau, un souvenir déjà remplacé.
    """
    limite = (maintenant or datetime.now(UTC)) - timedelta(days=jours)
    statut = await conn.execute(
        "UPDATE memoires SET archived = true, maj_le = now()"  # noqa: S608 — constantes
        " WHERE NOT archived AND valid_to IS NULL AND access_count = 0 AND importance <= $1 AND cree_le < $2"
        f" AND origine NOT IN ('utilisateur', 'profil') AND NOT ({_avec_tag(conn, '$3')})",
        importance_max,
        limite,
        "noyau",
    )
    return int(statut.rsplit(" ", 1)[-1])


# --- Bascule de modèle d'embeddings sans interruption -------------------------------------------------------


async def manquants(conn: Executant, modele: str) -> int:
    """Souvenirs actifs sans vecteur du modèle `modele`."""
    valeur: Any = await conn.fetchval(
        "SELECT count(*) FROM memoires m WHERE m.valid_to IS NULL AND NOT m.archived"
        " AND (m.embedding_model IS DISTINCT FROM $1 OR m.embedding IS NULL)"
        " AND NOT EXISTS (SELECT 1 FROM memoire_vecteurs v WHERE v.memoire_id = m.id AND v.modele = $1)",
        modele,
    )
    return int(valeur or 0)


async def reencoder(conn: Executant, encodeur: Encodeur, lot: int = 64, maximum: int | None = None) -> int:
    """Ajoute le vecteur du modèle de `encodeur` aux souvenirs qui ne l'ont pas encore ; renvoie leur nombre."""
    faits = 0
    while maximum is None or faits < maximum:
        lignes = await conn.fetch(
            "SELECT m.id, m.contenu FROM memoires m WHERE m.valid_to IS NULL AND NOT m.archived"
            " AND (m.embedding_model IS DISTINCT FROM $1 OR m.embedding IS NULL)"
            " AND NOT EXISTS (SELECT 1 FROM memoire_vecteurs v WHERE v.memoire_id = m.id AND v.modele = $1)"
            " ORDER BY m.cree_le DESC LIMIT $2",
            encodeur.nom_modele,
            lot,
        )
        if not lignes:
            break
        for ligne in lignes:
            v = await encodeur.encoder(ligne["contenu"][:4000])
            if conn.dialecte == "sqlite":
                await conn.execute(
                    "INSERT INTO memoire_vecteurs (memoire_id, modele, vecteur) VALUES ($1, $2, $3)",
                    ligne["id"],
                    encodeur.nom_modele,
                    vecteur_octets(v),
                )
            else:
                await conn.execute(
                    "INSERT INTO memoire_vecteurs (memoire_id, modele, vecteur) VALUES ($1, $2, $3::text::vector)",
                    ligne["id"],
                    encodeur.nom_modele,
                    vecteur_sql(v),
                )
            faits += 1
        await asyncio.sleep(0)  # laisser respirer le Core pendant une longue bascule
    return faits


async def modele_actif(conn: Executant, defaut: str) -> str:
    valeur = await conn.fetchval("SELECT valeur FROM etat_systeme WHERE cle = 'memoire_modele'")
    etat = valeur if isinstance(valeur, dict) else {}
    return str(etat.get("actif") or defaut)


async def fixer_modele_actif(conn: Executant, modele: str) -> None:
    await conn.execute(
        "UPDATE etat_systeme SET valeur = $1, maj_le = now() WHERE cle = 'memoire_modele'",
        {"actif": modele, "le": datetime.now(UTC).isoformat()},
    )


@dataclass
class EtatBascule:
    actif: str
    cible: str | None = None
    restants: int = 0
    faits: int = 0
    erreur: str | None = None

    @property
    def en_cours(self) -> bool:
        return self.cible is not None and self.erreur is None


async def basculer(conn: Executant, nouvel: Encodeur, etat: EtatBascule, lot: int = 64) -> None:
    """Encode tout avec `nouvel`, PUIS bascule la recherche : jusque-là elle garde l'ancien modèle."""
    etat.cible = nouvel.nom_modele
    try:
        etat.restants = await manquants(conn, nouvel.nom_modele)
        while True:
            faits = await reencoder(conn, nouvel, lot=lot, maximum=lot)
            etat.faits += faits
            etat.restants = await manquants(conn, nouvel.nom_modele)
            if faits == 0 or etat.restants == 0:
                break
        await fixer_modele_actif(conn, nouvel.nom_modele)
        etat.actif, etat.cible = nouvel.nom_modele, None
        journal.info("Mémoire : recherche basculée sur %s (%d vecteurs calculés)", nouvel.nom_modele, etat.faits)
    except Exception as exc:  # la recherche continue avec l'ancien modèle
        journal.exception("Bascule de modèle interrompue")
        etat.erreur = str(exc)


# --- Export lisible en Markdown -----------------------------------------------------------------------------


async def exporter_markdown(conn: Executant, dossier: Path, blocs: Sequence[Any] = ()) -> list[Path]:
    """MEMORY.md (souvenirs actifs par type), USER.md et SOUL.md (blocs), journal/AAAA-MM-JJ.md.

    Export en lecture seule, régénéré à chaque appel ; la source reste la base.
    """
    lignes = await conn.fetch(
        "SELECT contenu, type, tags, source, confidentialite, cree_le FROM memoires"
        " WHERE valid_to IS NULL AND NOT archived ORDER BY type, cree_le DESC"
    )
    ecrits = []
    par_type: dict[str, list[str]] = {}
    par_jour: dict[str, list[str]] = {}
    for r in lignes:
        jour = r["cree_le"].astimezone(FUSEAU).date().isoformat()
        prive = " 🔒" if r["confidentialite"] == "local_uniquement" else ""
        contenu = " ".join(str(r["contenu"]).split())[:1200]
        par_type.setdefault(r["type"], []).append(f"- ({jour}{prive}) {contenu}")
        par_jour.setdefault(jour, []).append(f"- [{r['type']}{prive}] {contenu}")
    memoire_md = [
        "# MEMORY — souvenirs actifs",
        "",
        f"Export du {datetime.now(FUSEAU):%d/%m/%Y %H:%M}, {len(lignes)} souvenirs.",
        "",
    ]
    for type_, items in sorted(par_type.items()):
        memoire_md += [f"## {type_}", "", *items, ""]
    ecrits.append(await asyncio.to_thread(_ecrire, dossier / "MEMORY.md", memoire_md))
    blocs_par_label = {b.label: b for b in blocs}
    utilisateur = [b for label, b in blocs_par_label.items() if label not in ("persona", "ame")]
    ecrits.append(
        await asyncio.to_thread(
            _ecrire,
            dossier / "USER.md",
            ["# USER — ce que JARVIS sait de vous (blocs)", ""]
            + [f"## {b.label}\n\n{b.content}\n" for b in utilisateur],
        )
    )
    ame = [b for label, b in blocs_par_label.items() if label in ("persona", "ame")]
    ecrits.append(
        await asyncio.to_thread(
            _ecrire,
            dossier / "SOUL.md",
            ["# SOUL — personnalité de JARVIS (blocs persona)", ""] + [f"{b.content}\n" for b in ame],
        )
    )
    for jour, items in par_jour.items():
        ecrits.append(
            await asyncio.to_thread(_ecrire, dossier / "journal" / f"{jour}.md", [f"# Journal du {jour}", "", *items])
        )
    return ecrits


def _ecrire(chemin: Path, lignes: Sequence[str]) -> Path:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("\n".join(lignes).rstrip() + "\n", encoding="utf-8")
    return chemin


# --- Banc d'évaluation --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Question:
    question: str
    attendus: tuple[str, ...]  # identifiants de souvenirs ou fragments de leur contenu


@dataclass
class ResultatBanc:
    classement: str
    rappel_5: float
    mrr: float
    details: list[dict[str, Any]]

    def texte(self) -> str:
        return (
            f"{self.classement} : rappel@5 = {self.rappel_5:.2f}, MRR = {self.mrr:.3f} ({len(self.details)} questions)"
        )


def lire_banc(donnees: Any) -> list[Question]:
    if not isinstance(donnees, list):
        raise ValueError("Banc : liste de questions attendue")
    questions = []
    for q in donnees:
        if not isinstance(q, dict) or not q.get("question") or not q.get("attendus"):
            raise ValueError("Banc : chaque question a « question » et « attendus »")
        attendus = q["attendus"] if isinstance(q["attendus"], list) else [q["attendus"]]
        questions.append(Question(str(q["question"]), tuple(str(a) for a in attendus)))
    return questions


def _correspond(resultat: Resultat, attendu: str) -> bool:
    if re.fullmatch(r"[0-9a-f-]{36}", attendu):
        return resultat.souvenir.id == attendu
    return attendu.lower() in resultat.souvenir.contenu.lower()


async def evaluer(
    conn: Executant, encodeur: Encodeur, questions: Sequence[Question], classement: Classement
) -> ResultatBanc:
    """Rappel@5 et MRR (rang du premier souvenir attendu) de la recherche de conversation."""
    from .memoire import ReglagesRecherche, rechercher_multi

    reglages = ReglagesRecherche(classement=classement)
    details = []
    trouves_5 = 0
    rr = 0.0
    for q in questions:
        resultats = await rechercher_multi(conn, encodeur, q.question, exclure_local=False, reglages=reglages)
        rang = next((i for i, r in enumerate(resultats, 1) if any(_correspond(r, a) for a in q.attendus)), None)
        trouves_5 += 1 if rang is not None and rang <= 5 else 0
        rr += 1 / rang if rang else 0.0
        details.append({"question": q.question, "rang": rang})
    n = max(len(questions), 1)
    return ResultatBanc(classement, trouves_5 / n, rr / n, details)


async def modele_majoritaire(conn: Executant) -> str | None:
    """Modèle d'embeddings de la plupart des souvenirs (celui de la recherche avant toute bascule)."""
    ligne = await conn.fetchrow(
        "SELECT embedding_model, count(*) AS n FROM memoires WHERE embedding_model IS NOT NULL"
        " GROUP BY embedding_model ORDER BY n DESC LIMIT 1"
    )
    return str(ligne["embedding_model"]) if ligne else None
