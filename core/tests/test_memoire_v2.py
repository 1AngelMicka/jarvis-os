"""Phase 8 : classement v2 et banc, blocs versionnés, accès et oubli, bascule de modèle, consolidation, export."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import AsyncGenerator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jarvis2 import blocs, memoire
from jarvis2.consolidation import consolider, extraire_faits
from jarvis2.db import Base
from jarvis2.memoire_v2 import (
    EtatBascule,
    Question,
    basculer,
    evaluer,
    exporter_markdown,
    manquants,
    modele_actif,
    modele_majoritaire,
    noter_acces,
    oublier,
)
from jarvis2.moteurs.base import Delta, Evenement, Fin, Message, Options, Reponse

from .test_agents import Scenario, systeme
from .test_memoire import MODELE, EncodeurFactice

pytestmark = pytest.mark.base


async def ajouter(pool: Base, contenu: str, **kw: object) -> str:
    return await memoire.ajouter(
        pool,
        contenu,
        origine=str(kw.pop("origine", "conversation")),
        vecteur=await EncodeurFactice().encoder(contenu),
        modele=MODELE,
        **kw,  # type: ignore[arg-type]
    )


# --- Classement v2 et banc ----------------------------------------------------------------------------------


async def test_banc_v2_progresse_face_a_v1(pool: Base) -> None:
    """Deux souvenirs presque identiques : v1 prend le plus récent, v2 le plus important (l'utilisateur l'a dit)."""
    bon = await ajouter(pool, "Le code du wifi de la maison est soleil42", importance=0.95)
    await ajouter(pool, "Le code du wifi de la maison était lune17", importance=0.05)
    rdv = await ajouter(pool, "Rendez-vous chez le dentiste mardi à 9 h", importance=0.9)
    await ajouter(pool, "Le dentiste du quartier a changé de rue mardi", importance=0.1)
    await ajouter(pool, "Les tomates du potager mûrissent en été", importance=0.5)
    questions = [Question("Quel est le code du wifi de la maison ?", (bon,)), Question("dentiste mardi", (rdv,))]
    v1 = await evaluer(pool, EncodeurFactice(), questions, "v1")
    v2 = await evaluer(pool, EncodeurFactice(), questions, "v2")
    assert v2.mrr > v1.mrr and v2.rappel_5 >= v1.rappel_5
    assert [d["rang"] for d in v2.details] == [1, 1]


# --- Blocs ----------------------------------------------------------------------------------------------------


async def test_blocs_versionnes_injectes_et_prives(pool: Base, tmp_path: Path) -> None:
    await blocs.ecrire(pool, "preferences", "Répondre en vouvoyant, sans jargon.", "appareil:pc")
    b = await blocs.ecrire(pool, "preferences", "Répondre en vouvoyant, sans jargon, avec des exemples.", "jarvis")
    assert b.version == 2
    await blocs.ecrire(pool, "sante", "Allergie aux arachides.", "appareil:pc", "local_uniquement")
    versions = await blocs.historique(pool, "preferences")
    assert [v["version"] for v in versions] == [2, 1] and versions[1]["auteur"] == "appareil:pc"
    with pytest.raises(blocs.ErreurBloc, match="trop long"):
        await blocs.ecrire(pool, "preferences", "x" * 3000, "jarvis")
    with pytest.raises(blocs.ErreurBloc, match="Nom"):
        await blocs.ecrire(pool, "Pas Bon", "x", "jarvis")
    s = await systeme(pool, tmp_path, {"local": Scenario("local", "local", externe=False)})
    externe, _ = await s["service"].consignes("bonjour", externe=True)
    local, _ = await s["service"].consignes("bonjour", externe=False)
    assert "avec des exemples" in externe and "arachides" not in externe  # bloc privé : jamais vers l'extérieur
    assert "arachides" in local


async def test_noyau_converti_en_blocs_sans_rien_effacer(pool: Base) -> None:
    await ajouter(pool, "JARVIS répond en français", tags=["noyau"])
    await ajouter(pool, "Code de l'alarme : 1234", tags=["noyau"], confidentialite="local_uniquement")
    total = await pool.fetchval("SELECT count(*) FROM memoires")
    assert await blocs.noyau_en_blocs(pool) == {"noyau": 1, "noyau-prive": 1}
    assert await pool.fetchval("SELECT count(*) FROM memoires") == total
    assert await memoire.lire_noyau(pool, exclure_local=False) == []  # plus injecté deux fois
    par_label = {b.label: b for b in await blocs.lister(pool)}
    assert "français" in par_label["noyau"].content and par_label["noyau-prive"].confidentialite == "local_uniquement"


# --- Accès et oubli -------------------------------------------------------------------------------------------


async def test_oubli_archive_sans_effacer(pool: Base) -> None:
    vieux = await ajouter(pool, "Une note sans importance", importance=0.1)
    consulte = await ajouter(pool, "Une note consultée", importance=0.1)
    dit = await ajouter(pool, "Ce que j'ai dit moi-même", importance=0.1, origine="utilisateur")
    importante = await ajouter(pool, "Une note importante", importance=0.9)
    await noter_acces(pool, [consulte])
    assert await pool.fetchval("SELECT access_count FROM memoires WHERE id = $1", consulte) == 1
    dans_un_an = datetime.now(UTC) + timedelta(days=365)
    assert await oublier(pool, maintenant=dans_un_an) == 1
    archives = {str(r["id"]) for r in await pool.fetch("SELECT id FROM memoires WHERE archived")}
    assert archives == {vieux}
    assert await pool.fetchval("SELECT count(*) FROM memoires") == 4  # rien d'effacé
    assert {dit, importante, consulte}.isdisjoint(archives)


# --- Bascule de modèle --------------------------------------------------------------------------------------


class EncodeurNouveau:
    """Autre modèle, autre dimension (comme bge-m3 face à MiniLM)."""

    nom_modele = "essai/nouveau-modele-64"

    async def encoder(self, texte: str) -> list[float]:
        v = [0.0] * 64
        for mot in re.findall(r"\w+", texte.lower()):
            v[int(hashlib.sha256(mot.encode()).hexdigest(), 16) % 64] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]


async def test_bascule_de_modele_sans_interruption(pool: Base) -> None:
    jardin = await ajouter(pool, "Le potager produit des tomates anciennes")
    await ajouter(pool, "La voiture est au garage")
    assert await modele_majoritaire(pool) == MODELE
    nouveau = EncodeurNouveau()
    assert await manquants(pool, nouveau.nom_modele) == 2
    # Pendant la bascule, l'ancien modèle répond toujours
    assert (await memoire.rechercher(pool, EncodeurFactice(), "tomates du potager", limite=1))[0].souvenir.id == jardin
    etat = EtatBascule(MODELE)
    await basculer(pool, nouveau, etat, lot=1)
    assert etat.actif == nouveau.nom_modele and etat.restants == 0 and etat.faits == 2
    assert await modele_actif(pool, MODELE) == nouveau.nom_modele
    resultat = (await memoire.rechercher(pool, nouveau, "tomates du potager", limite=1))[0]
    assert resultat.souvenir.id == jardin and resultat.similarite > 0.3  # vecteurs du nouveau modèle comparés (0 sinon)


# --- Consolidation --------------------------------------------------------------------------------------------


class Consolideur(Scenario):
    async def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        self.recus = list(messages)
        texte = (
            '[{"contenu": "L\'utilisateur prépare un marathon en avril", "type": "projet", "importance": 0.8},'
            ' {"contenu": "Le potager produit des tomates anciennes", "type": "fait", "importance": 0.4}]'
        )
        yield Delta(texte)
        yield Fin(Reponse(texte, "local-1"))


async def test_consolidation_locale_sans_doublon_ni_effacement(pool: Base, tmp_path: Path) -> None:
    moteurs = {"compte": Scenario("compte", "cli"), "local": Consolideur("local", "local", externe=False)}
    s = await systeme(pool, tmp_path, moteurs)
    await ajouter(pool, "Le potager produit des tomates anciennes")
    conv = await s["depot"].creer("Sport")
    await s["depot"].ajouter_message(conv.id, "utilisateur", "Je prépare un marathon pour avril")
    avant = await pool.fetchval("SELECT count(*) FROM memoires")
    r = await consolider(pool, s["service"], datetime.now(UTC) - timedelta(hours=1))
    assert r["statut"] == "ok" and r["ajoutes"] == 1 and r["doublons"] == 1 and r["moteur"] == "local"
    assert await pool.fetchval("SELECT count(*) FROM memoires") == avant + 1
    ligne = await pool.fetchrow("SELECT importance, source, type FROM memoires WHERE contenu LIKE '%marathon%'")
    assert (
        ligne["type"] == "projet"
        and abs(ligne["importance"] - 0.8) < 1e-6
        and ligne["source"].startswith("consolidation:")
    )
    # Sans IA locale : ignorée (rien ne quitte le PC)
    moteurs["local"].dispo = False
    assert (await consolider(pool, s["service"], datetime.now(UTC)))["statut"] == "ignoree"


def test_extraire_faits_tolere_le_bruit() -> None:
    assert extraire_faits('Voici : [{"contenu": "A", "type": "bizarre", "importance": 7}]') == [
        {"contenu": "A", "type": "note", "importance": 1.0}
    ]
    assert extraire_faits("rien") == []


# --- Export Markdown ------------------------------------------------------------------------------------------


async def test_export_markdown(pool: Base, tmp_path: Path) -> None:
    await ajouter(pool, "Le potager produit des tomates anciennes", type_="fait")
    await blocs.ecrire(pool, "persona", "Calme, précis, un brin d'humour.", "jarvis")
    await blocs.ecrire(pool, "preferences", "Vouvoiement.", "jarvis")
    fichiers = await exporter_markdown(pool, tmp_path / "md", await blocs.lister(pool))
    noms = {f.name for f in fichiers}
    assert {"MEMORY.md", "USER.md", "SOUL.md"} <= noms and any(f.parent.name == "journal" for f in fichiers)
    assert "tomates anciennes" in (tmp_path / "md" / "MEMORY.md").read_text(encoding="utf-8")
    assert "humour" in (tmp_path / "md" / "SOUL.md").read_text(encoding="utf-8")
    assert "Vouvoiement" in (tmp_path / "md" / "USER.md").read_text(encoding="utf-8")


def test_bge_m3_propose_par_jarvis() -> None:
    """BAAI/bge-m3 (cité par la documentation) est connu de fastembed une fois JARVIS chargé, sans téléchargement."""
    from fastembed import TextEmbedding

    from jarvis2.embeddings import _ajouter_modeles

    _ajouter_modeles(TextEmbedding)
    modele = next(m for m in TextEmbedding.list_supported_models() if m["model"] == "BAAI/bge-m3")
    assert modele["dim"] == 1024
