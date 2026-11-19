"""Lot 14 · C 14 : niveaux public / semi-privé / privé, remplacement d'un fait (changement d'avis), versions,
détection de contradiction, routes et « Où partent mes données »."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis2 import blocs, contradiction, memoire, rappel
from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.consolidation import consolider
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import ServiceDialogue, SourceMemoire
from jarvis2.moteurs.base import Delta, Evenement, Fin, Message, Options, Reponse
from jarvis2.securite import appareils

from .test_agents import Scenario, systeme
from .test_memoire import MODELE, EncodeurFactice

pytestmark = pytest.mark.base


async def ajouter(pool: Base, contenu: str, **kw: Any) -> str:
    return await memoire.ajouter(
        pool, contenu, vecteur=await EncodeurFactice().encoder(contenu), modele=MODELE, origine="utilisateur", **kw
    )


# --- Synchronisation niveau ↔ confidentialité ----------------------------------------------------------------


async def test_niveau_et_confidentialite_synchronises(pool: Base) -> None:
    defaut = await ajouter(pool, "Le vélo est rangé dans le garage")
    local = await ajouter(pool, "Mon dossier médical est chez le docteur", confidentialite="local_uniquement")
    noyau = await ajouter(pool, "JARVIS répond en français", tags=["noyau"])
    public = await ajouter(pool, "Le site du projet est public", niveau="public")
    prive = await ajouter(pool, "Le code du portail", niveau="prive")
    lignes = {
        str(r["id"]): (r["niveau"], r["confidentialite"])
        for r in await pool.fetch("SELECT id, niveau, confidentialite FROM memoires")
    }
    assert lignes[defaut] == ("semi_prive", "normal")
    assert lignes[local] == ("prive", "local_uniquement")
    assert lignes[noyau] == ("public", "normal")
    assert lignes[public] == ("public", "normal")
    assert lignes[prive] == ("prive", "local_uniquement")
    with pytest.raises(ValueError, match="Niveau inconnu"):
        await ajouter(pool, "x", niveau="secret")
    # Changer le niveau garde l'invariant ; un souvenir remplacé ne change plus
    s = await memoire.changer_niveau(pool, defaut, "prive")
    assert s is not None and s.niveau == "prive" and s.confidentialite == "local_uniquement"
    s = await memoire.changer_niveau(pool, defaut, "public")
    assert s is not None and s.confidentialite == "normal"
    compte = await memoire.compter(pool)
    assert memoire.niveaux_de(compte) == {"public": 3, "semi_prive": 0, "prive": 2}
    assert compte["local_uniquement"] == 2
    # Blocs : public par défaut, niveau prioritaire sur la confidentialité
    b = await blocs.ecrire(pool, "style", "Phrases courtes.", "jarvis")
    assert (b.niveau, b.confidentialite) == ("public", "normal")
    b = await blocs.ecrire(pool, "style", "Phrases courtes.", "jarvis", "normal", niveau="prive")
    assert (b.niveau, b.confidentialite) == ("prive", "local_uniquement")
    b = await blocs.ecrire(pool, "style", "Phrases très courtes.", "jarvis")  # garde son niveau
    assert b.niveau == "prive" and b.en_dict()["niveau"] == "prive"
    b = await blocs.ecrire(pool, "style", "Phrases très courtes.", "jarvis", "normal")
    assert b.niveau == "public"
    with pytest.raises(blocs.ErreurBloc, match="Niveau"):
        await blocs.ecrire(pool, "style", "x", "jarvis", niveau="secret")


# --- Filtrage vers un moteur externe ---------------------------------------------------------------------------


async def test_filtrage_externe_par_niveau(pool: Base) -> None:
    for niveau in memoire.NIVEAUX:
        await ajouter(pool, f"Noyau {niveau} : la tortue mange de la salade", tags=["noyau"], niveau=niveau)
        await ajouter(pool, f"Souvenir {niveau} : la tortue dort sous la salade", niveau=niveau)
        await blocs.ecrire(pool, f"bloc-{niveau.replace('_', '-')}", f"Bloc {niveau}", "jarvis", niveau=niveau)

    # Noyau : public seulement vers l'extérieur, tout en local
    externe = await memoire.lire_noyau(pool, exclure_local=True)
    assert {s.niveau for s in externe} == {"public"}
    assert {s.niveau for s in await memoire.lire_noyau(pool, exclure_local=False)} == set(memoire.NIVEAUX)
    # Blocs : public seulement
    assert [b.niveau for b in await blocs.lister(pool, exclure_local=True)] == ["public"]
    assert len(await blocs.lister(pool, exclure_local=False)) == 3
    # Recherche : public + semi-privé, jamais privé
    trouves = await memoire.rechercher_multi(pool, EncodeurFactice(), "la tortue et la salade", exclure_local=True)
    assert {r.souvenir.niveau for r in trouves} == {"public", "semi_prive"}
    brut = await memoire.rechercher(pool, EncodeurFactice(), "tortue salade", limite=20, exclure_local=True)
    assert "prive" not in {r.souvenir.niveau for r in brut} and len(brut) == 4
    local = await memoire.rechercher_multi(pool, EncodeurFactice(), "la tortue et la salade", exclure_local=False)
    assert "prive" in {r.souvenir.niveau for r in local}
    # Nouveautés : public seulement
    depuis = datetime.now(UTC) - timedelta(hours=1)
    recents = await memoire.parcourir(pool, depuis=depuis, niveaux=memoire.VERS_EXTERNE["nouveautes"])
    assert {s.niveau for s in recents} == {"public"} and len(recents) == 2
    assert len(await memoire.parcourir(pool, depuis=depuis, exclure_local=True)) == 4


async def test_dialogue_externe_respecte_les_niveaux(pool: Base, tmp_path: Path) -> None:
    s = await systeme(pool, tmp_path, {"local": Scenario("local", "local", externe=False)})
    await ajouter(pool, "Préférence publique : réponses en vouvoyant", tags=["noyau"], niveau="public")
    await ajouter(pool, "Préférence semi-privée : réponses détaillées", tags=["noyau"], niveau="semi_prive")
    await ajouter(pool, "Le chat Zéphyr adore les croquettes au saumon")
    await ajouter(pool, "Le chat Zéphyr a un traitement vétérinaire secret", niveau="prive")
    await blocs.ecrire(pool, "public", "Bloc visible", "jarvis")
    await blocs.ecrire(pool, "semi", "Bloc semi caché", "jarvis", niveau="semi_prive")
    externe, ctx = await s["service"].consignes("Que mange le chat Zéphyr ?", externe=True)
    assert "vouvoyant" in externe and "détaillées" not in externe
    assert "Bloc visible" in externe and "Bloc semi caché" not in externe
    assert "croquettes" in externe and "vétérinaire" not in externe
    assert ctx.porte is None
    local, _ = await s["service"].consignes("Que mange le chat Zéphyr ?", externe=False)
    assert "détaillées" in local and "Bloc semi caché" in local
    # Porte de rappel : « merci » ne cherche pas, noyau et blocs restent
    poli, ctx = await s["service"].consignes("Merci JARVIS !", externe=True)
    assert ctx.porte == rappel.SANS_RECHERCHE["politesse"] and ctx.souvenirs == []
    assert "vouvoyant" in poli and "Bloc visible" in poli and "croquettes" not in poli
    # La détection d'un sujet privé cherche toujours, même pour un message que la porte laisserait passer
    await ajouter(pool, "Zut", niveau="prive")
    assert rappel.decider("zut").rappeler is False
    assert await s["service"].est_prive("zut") is True


# --- Remplacement, versions, contradiction ---------------------------------------------------------------------


async def test_changement_avis(pool: Base, tmp_path: Path) -> None:
    """« Je préfère le café le matin », puis « Finalement je préfère le thé le matin »."""
    encodeur = EncodeurFactice()
    cafe = await ajouter(pool, "Je préfère le café le matin", type_="fait", tags=["gouts"])
    await ajouter(pool, "Le jardin a besoin d'eau le soir", type_="fait")
    nouveau_texte = "Finalement je préfère le thé le matin"
    verdict = await contradiction.examiner(pool, encodeur, nouveau_texte, "fait")
    assert verdict.action == "remplacer" and verdict.cible is not None and verdict.cible.id == cafe
    assert "finalement" in verdict.raison
    the = await memoire.remplacer(
        pool, cafe, nouveau_texte, vecteur=await encodeur.encoder(nouveau_texte), modele=MODELE, raison=verdict.raison
    )
    ancien = await pool.fetchrow("SELECT valid_to, superseded_by FROM memoires WHERE id = $1", cafe)
    assert ancien["valid_to"] is not None and str(ancien["superseded_by"]) == the
    nouveau = await memoire.lire(pool, the)
    assert nouveau is not None and nouveau.remplace and nouveau.tags == ("gouts",) and nouveau.type == "fait"
    assert nouveau.niveau == "semi_prive"
    # La recherche ne renvoie plus que le nouveau
    trouves = await memoire.rechercher_multi(pool, encodeur, "Que bois-tu le matin, café ou thé ?", exclure_local=False)
    ids = [r.souvenir.id for r in trouves]
    assert the in ids and cafe not in ids
    # Historique : les deux, du plus ancien à l'actuel, depuis l'un ou l'autre
    for depart in (cafe, the):
        versions = await memoire.versions(pool, depart)
        assert [v.souvenir.id for v in versions] == [cafe, the]
        assert versions[0].superseded_by == the and versions[0].valid_to is not None
        assert versions[1].superseded_by is None and versions[1].valid_to is None
    with pytest.raises(memoire.DejaRemplace):
        await memoire.remplacer(pool, cafe, "Je préfère le chocolat le matin")
    with pytest.raises(memoire.SouvenirAbsent):
        await memoire.remplacer(pool, "00000000-0000-0000-0000-000000000000", "x")
    assert await memoire.changer_niveau(pool, cafe, "public") is None  # ancienne version : figée


class ConsolideurAvis(Scenario):
    async def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        self.recus = list(messages)
        texte = (
            '[{"contenu": "Finalement je préfère le thé le matin", "type": "fait", "importance": 0.6},'
            ' {"contenu": "Le jardin a besoin d\'eau le soir", "type": "fait", "importance": 0.4}]'
        )
        yield Delta(texte)
        yield Fin(Reponse(texte, "local-1"))


async def test_changement_avis_par_la_consolidation(pool: Base, tmp_path: Path) -> None:
    moteurs = {"local": ConsolideurAvis("local", "local", externe=False)}
    s = await systeme(pool, tmp_path, moteurs)
    cafe = await ajouter(pool, "Je préfère le café le matin", type_="fait")
    await ajouter(pool, "Le jardin a besoin d'eau le soir", type_="fait")
    conv = await s["depot"].creer("Boissons")
    await s["depot"].ajouter_message(conv.id, "utilisateur", "Finalement je préfère le thé le matin")
    avant = await pool.fetchval("SELECT count(*) FROM memoires")
    r = await consolider(pool, s["service"], datetime.now(UTC) - timedelta(hours=1))
    assert r["statut"] == "ok" and r["remplaces"] == 1 and r["doublons"] == 1 and r["ajoutes"] == 0
    assert await pool.fetchval("SELECT count(*) FROM memoires") == avant + 1  # rien d'effacé
    versions = await memoire.versions(pool, cafe)
    assert [v.souvenir.contenu for v in versions] == [
        "Je préfère le café le matin",
        "Finalement je préfère le thé le matin",
    ]
    assert versions[1].souvenir.canal_detail is not None and "consolidation" in versions[1].souvenir.canal_detail


def test_contradiction_deterministe() -> None:
    assert contradiction.contredit("Je préfère le café le matin", "Je préfère le café le matin !") is None
    assert contradiction.contredit("J'habite à Lyon", "J'habite à Grenoble") == "même clé « j'habite », autre valeur"
    assert "mon velo" in (contradiction.contredit("Mon vélo est rouge", "Mon vélo est bleu") or "")
    assert (
        contradiction.contredit("Je bois du café", "Je ne bois plus de café") == "marqueur de changement « ne … plus »"
    )
    assert contradiction.contredit("Je travaille chez Acme", "J'ai changé d'avis sur Acme") is not None
    assert contradiction.contredit("Le potager produit des tomates", "Le potager produit des courgettes") is None


# --- Routes et « Où partent mes données » ---------------------------------------------------------------------


@pytest.fixture
async def client(pool: Base) -> AsyncIterator[httpx.AsyncClient]:
    depot = DepotConversations(pool)
    source = SourceMemoire(pool, EncodeurFactice())
    service = ServiceDialogue(depot, {}, "x", source)
    ctx = Contexte(pool, depot, {}, service, "x", source)
    app = creer_app(Parametres(), ctx)
    app.state.ctx = ctx
    _, jeton = await appareils.creer(pool, "PC", "pc")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:8765",
        headers={"Authorization": f"Bearer {jeton}"},
    ) as c:
        yield c


async def test_routes_niveau_remplacer_versions(pool: Base, client: httpx.AsyncClient) -> None:
    ident = await ajouter(pool, "Je préfère le café le matin", type_="fait")
    liste = (await client.get("/v1/memoire/souvenirs")).json()["souvenirs"]
    assert liste[0]["niveau"] == "semi_prive" and liste[0]["remplace"] is False
    r = await client.put(f"/v1/memoire/souvenirs/{ident}/niveau", json={"niveau": "public"})
    assert r.status_code == 200 and r.json()["souvenir"]["niveau"] == "public"
    assert r.json()["souvenir"]["confidentialite"] == "normal"
    assert (await client.put(f"/v1/memoire/souvenirs/{ident}/niveau", json={"niveau": "secret"})).status_code == 422
    absent = "00000000-0000-0000-0000-000000000000"
    assert (await client.put(f"/v1/memoire/souvenirs/{absent}/niveau", json={"niveau": "prive"})).status_code == 404
    assert (await client.put("/v1/memoire/souvenirs/pas-un-id/niveau", json={"niveau": "prive"})).status_code == 422
    journal = await pool.fetchval("SELECT count(*) FROM audit WHERE action = 'memoire.niveau'")
    assert journal == 1

    r = await client.post(f"/v1/memoire/souvenirs/{ident}/remplacer", json={"contenu": "Je préfère le thé le matin"})
    assert r.status_code == 200
    corps = r.json()
    assert corps["ancien"]["id"] == ident and corps["nouveau"]["remplace"] is True
    assert corps["nouveau"]["niveau"] == "public"  # le niveau suit
    assert (
        await client.post(f"/v1/memoire/souvenirs/{ident}/remplacer", json={"contenu": "Chocolat"})
    ).status_code == 409
    assert (await client.post(f"/v1/memoire/souvenirs/{absent}/remplacer", json={"contenu": "x"})).status_code == 404
    assert (await client.put(f"/v1/memoire/souvenirs/{ident}/niveau", json={"niveau": "prive"})).status_code == 404

    versions = (await client.get(f"/v1/memoire/souvenirs/{corps['nouveau']['id']}/versions")).json()["versions"]
    assert [v["id"] for v in versions] == [ident, corps["nouveau"]["id"]]
    assert versions[0]["superseded_by"] == corps["nouveau"]["id"] and versions[0]["valid_to"] is not None
    assert versions[1]["valid_to"] is None and versions[1]["superseded_by"] is None
    assert (await client.get(f"/v1/memoire/souvenirs/{absent}/versions")).status_code == 404

    # Blocs : niveau accepté, prioritaire sur la confidentialité
    r = await client.put(
        "/v1/memoire/blocs/style", json={"contenu": "Court.", "confidentialite": "normal", "niveau": "prive"}
    )
    assert r.status_code == 200 and r.json()["niveau"] == "prive" and r.json()["confidentialite"] == "local_uniquement"
    assert (await client.put("/v1/memoire/blocs/style", json={"contenu": "x", "niveau": "secret"})).status_code == 422

    etat = (await client.get("/v1/memoire/etat")).json()
    assert etat["niveaux"] == {"public": 1, "semi_prive": 0, "prive": 0}


async def test_flux_decrit_la_memoire(pool: Base, client: httpx.AsyncClient) -> None:
    await ajouter(pool, "Un souvenir privé", niveau="prive")
    await ajouter(pool, "Un souvenir ordinaire")
    corps = (await client.get("/v1/donnees/flux")).json()
    m = corps["memoire"]
    assert m["niveaux"] == {"public": 0, "semi_prive": 1, "prive": 1}
    regles = {r["niveau"]: r for r in m["regles"]}
    assert list(regles) == list(memoire.NIVEAUX)
    assert "jamais" in regles["prive"]["vers_cloud"].lower()
    assert "seulement" in regles["semi_prive"]["vers_cloud"] and "noyau" in regles["semi_prive"]["vers_cloud"]
    assert "partout" in regles["public"]["vers_cloud"]
    assert m["porte_rappel"] == rappel.DESCRIPTION and str(rappel.LONGUEUR_MIN) in m["porte_rappel"]
