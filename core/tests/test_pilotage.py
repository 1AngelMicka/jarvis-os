"""Lot F : bloc d'actions validé par le Core, règles de protection, commandes rapides, « toujours autoriser »."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Sequence
from typing import Any

import httpx
import pytest

from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import ServiceDialogue
from jarvis2.moteurs.base import Delta, EtatSante, Evenement, Fin, InfoModele, Message, Moteur, Options, Reponse
from jarvis2.moteurs.telemetrie import EnregistreurMemoire, MoteurInstrumente
from jarvis2.pilotage import retirer_bloc
from jarvis2.securite import appareils
from jarvis2.securite.jokers import ErreurMotif, compiler, normaliser, remplacer

from .authentificateur import Authentificateur

ORIGINE = "http://localhost:8765"


class MoteurScript(Moteur):
    """Répond le texte qu'on lui donne (en deux morceaux) et garde les messages de son premier appel."""

    id = "script"
    nom = "Script"
    externe = False

    def __init__(self) -> None:
        self.texte = "Bonjour."
        self.recus: list[Message] = []

    async def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        if not self.recus:  # le premier appel (le titre automatique vient ensuite)
            self.recus = list(messages)
        moitie = len(self.texte) // 2
        yield Delta(self.texte[:moitie])
        yield Delta(self.texte[moitie:])
        yield Fin(Reponse(self.texte, "script-1"))

    async def list_models(self) -> list[InfoModele]:
        return [InfoModele("script-1", "Script", True)]

    async def health(self) -> EtatSante:
        return EtatSante(True)


# --- Motifs à jokers (sans base) ----------------------------------------------------------------------------


def test_normalisation_sans_accents_ni_ponctuation() -> None:
    assert normaliser("  Ouvre les MISSIONS, s'il te plaît ! ") == "ouvre les missions s il te plait"
    assert normaliser("Cœur") == "coeur"


def test_jokers_et_captures_avec_texte_d_origine() -> None:
    m = compiler("ouvre * missions")
    assert m.correspond("Ouvre les Missions !") == {}
    assert m.correspond("ouvre missions") == {}
    assert m.correspond("ouvre les missions demain") is None  # la phrase ENTIÈRE doit correspondre
    capte = compiler("recherche sur {sujet}").correspond("Recherche sur l'Été indien.")
    assert capte == {"sujet": "l'Été indien"}  # accents et majuscules gardés
    assert compiler("{a} et {b}").correspond("Pomme et Poire") == {"a": "Pomme", "b": "Poire"}
    # Règles : le motif est cherché n'importe où
    assert compiler("projet secret").correspond("Archiver le PROJET Secret, vite", contient=True) == {}


@pytest.mark.parametrize("motif", ["*", "  ", "{x}", "a{nom", "{Nom}", "{a} {a}", "x" * 201])
def test_motifs_refuses(motif: str) -> None:
    with pytest.raises(ErreurMotif):
        compiler(motif)


def test_motif_jamais_interprete_comme_expression_reguliere() -> None:
    m = compiler("(a+)+ [b] .*")
    # Parenthèses, « + » et crochets ne sont que de la ponctuation, retirée : le motif devient « a b * »
    assert m.normalise == "a b *"
    assert m.correspond("aaaa") is None and m.correspond("a b et la suite") == {}
    assert compiler("lance un.audit").correspond("lance un audit") == {}


def test_remplacer_les_captures() -> None:
    assert remplacer({"objectif": "Étudier {sujet}", "n": 3}, {"sujet": "x"}) == {"objectif": "Étudier x", "n": 3}
    with pytest.raises(ErreurMotif):
        remplacer({"objectif": "{inconnu}"}, {})


def test_retirer_le_bloc_d_actions() -> None:
    texte, blocs = retirer_bloc('Voici.\n<actions>[{"type": "naviguer", "vue": "agents"}]</actions>')
    assert texte == "Voici." and len(blocs) == 1
    texte, blocs = retirer_bloc("Sans bloc.")
    assert texte == "Sans bloc." and blocs == []
    texte, blocs = retirer_bloc('Coupé <actions>[{"type"')  # bloc non fermé : retiré quand même
    assert texte == "Coupé" and blocs


# --- Avec la base -------------------------------------------------------------------------------------------


@pytest.fixture
async def systeme(pool: Base) -> dict[str, Any]:
    depot = DepotConversations(pool)
    script = MoteurScript()
    moteurs = {"script": MoteurInstrumente(script, EnregistreurMemoire())}
    ctx = Contexte(pool, depot, moteurs, ServiceDialogue(depot, moteurs, "script"), "script")
    app = creer_app(Parametres(), ctx)
    app.state.ctx = ctx
    _, jeton = await appareils.creer(pool, "PC", "pc")
    entetes = {"Authorization": f"Bearer {jeton}", "Origin": ORIGINE}
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGINE, headers=entetes)
    return {"ctx": ctx, "client": client, "script": script}


async def dialoguer(client: httpx.AsyncClient, message: str) -> dict[str, dict[str, Any]]:
    evenements: dict[str, dict[str, Any]] = {}
    async with client.stream("POST", "/v1/dialogue", json={"message": message, "moteur": "script"}) as rep:
        assert rep.status_code == 200
        nom = ""
        async for ligne in rep.aiter_lines():
            if ligne.startswith("event: "):
                nom = ligne[7:]
            elif ligne.startswith("data: "):
                evenements[nom] = json.loads(ligne[6:])
    return evenements


async def creer_conversation(pool: Base, titre: str = "À ranger") -> str:
    return str((await DepotConversations(pool).creer(titre)).id)


@pytest.mark.base
async def test_bloc_valide_retire_et_classe(systeme: dict[str, Any], pool: Base) -> None:
    client, script = systeme["client"], systeme["script"]
    # Le journal d'audit n'est jamais vidé entre les tests (PostgreSQL) : on compte à partir d'ici
    avant = await pool.fetchval("SELECT count(*) FROM audit WHERE action = 'pilotage.actions'")
    conv = await creer_conversation(pool, "Voyage au Japon")
    script.texte = (
        "Je vous montre vos missions et je vous propose une recherche.\n<actions>["
        '{"type": "naviguer", "vue": "agents"},'
        f'{{"type": "ouvrir", "objet": "conversation", "id": "{conv}"}},'
        '{"type": "ouvrir", "objet": "conversation", "id": "00000000-0000-0000-0000-000000000000"},'
        '{"type": "proposer_mission", "mission": "recherche", "objectif": "Neuroplasticité chez l\'adulte"},'
        '{"type": "executer_shell", "commande": "rm -rf /"},'
        '{"type": "demander_action", "action": "conversation.supprimer", "parametres": {"conversation_id": "x"}}'
        "]</actions>"
    )
    ev = await dialoguer(client, "Montre-moi les missions")
    fin = ev["fin"]
    assert "<actions>" not in fin["texte"] and fin["texte"].endswith("une recherche.")
    types = [(a["type"], a["genre"]) for a in fin["actions"]]
    assert types == [
        ("naviguer", "immediate"),
        ("ouvrir", "immediate"),
        ("proposer_mission", "proposition"),
        ("demander_action", "proposition"),
    ]
    assert fin["actions"][1]["parametres"]["titre"] == "Voyage au Japon"
    assert fin["actions"][3]["niveau"] == "rouge"
    assert any("n'existe pas" in e for e in fin["actions_ecartees"])  # identifiant inventé : jamais transmis
    assert any("inconnu" in e for e in fin["actions_ecartees"])  # aucun shell, aucun type inventé
    # Rien n'a été lancé ni demandé : ce ne sont que des propositions
    assert await pool.fetchval("SELECT count(*) FROM missions") == 0
    assert await pool.fetchval("SELECT count(*) FROM demandes") == 0
    # L'historique garde le texte sans bloc, et les actions pour « Rouvrir »
    stocke = await pool.fetchrow("SELECT contenu, meta FROM messages WHERE role = 'jarvis'")
    assert stocke is not None and "<actions>" not in stocke["contenu"]
    meta = stocke["meta"] if isinstance(stocke["meta"], dict) else json.loads(stocke["meta"])
    assert len(meta["actions"]) == 4
    assert await pool.fetchval("SELECT count(*) FROM audit WHERE action = 'pilotage.actions'") == avant + 1
    # Les consignes expliquent le bloc au modèle
    assert "<actions>" in script.recus[0].contenu


@pytest.mark.base
async def test_mode_non_ecarte_tout_et_retire_les_consignes(systeme: dict[str, Any]) -> None:
    client, script = systeme["client"], systeme["script"]
    assert (await client.get("/v1/pilotage")).json()["mode"] == "demander"
    assert (await client.put("/v1/pilotage", json={"mode": "non"})).json() == {"mode": "non"}
    assert (await client.put("/v1/pilotage", json={"mode": "toujours"})).status_code == 422
    script.texte = 'Bien.<actions>[{"type": "naviguer", "vue": "agents"}]</actions>'
    fin = (await dialoguer(client, "Missions"))["fin"]
    assert fin["texte"] == "Bien." and fin["actions"] == []
    assert "<actions>" not in script.recus[0].contenu


@pytest.mark.base
async def test_sans_bloc_aucune_meta_d_actions(systeme: dict[str, Any]) -> None:
    systeme["script"].texte = "Simple discussion."
    fin = (await dialoguer(systeme["client"], "Bonjour"))["fin"]
    assert "actions" not in fin


@pytest.mark.base
async def test_bloc_illisible_ecarte(systeme: dict[str, Any]) -> None:
    systeme["script"].texte = "Voilà.<actions>naviguer vers agents</actions>"
    fin = (await dialoguer(systeme["client"], "x"))["fin"]
    assert fin["texte"] == "Voilà." and fin["actions"] == [] and fin["actions_ecartees"]


# --- Règles de protection -----------------------------------------------------------------------------------


@pytest.mark.base
async def test_regle_interdire_refuse_l_action_meme_approuvee(systeme: dict[str, Any], pool: Base) -> None:
    client = systeme["client"]
    conv = await creer_conversation(pool, "Projet Secret")
    demande = (
        await client.post(
            "/v1/actions",
            json={"action": "conversation.archiver", "parametres": {"conversation_id": conv, "titre": "Projet Secret"}},
        )
    ).json()["demande"]
    # Règle ajoutée après la demande : elle prime sur l'approbation
    r = await client.post(
        "/v1/regles", json={"genre": "interdire", "motif": "projet secret", "libelle": "Ne touche pas au projet secret"}
    )
    assert r.status_code == 200, r.text
    refus = await client.post(f"/v1/demandes/{demande['id']}/approuver", json={})
    assert refus.status_code == 409 and "règle de protection" in refus.json()["detail"]
    assert await pool.fetchval("SELECT archivee FROM conversations WHERE id = $1::uuid", conv) is False
    # Nouvelle demande : refusée tout de suite
    rep = await client.post(
        "/v1/actions",
        json={"action": "conversation.archiver", "parametres": {"conversation_id": conv, "titre": "Projet Secret"}},
    )
    assert rep.status_code == 422 and "règle de protection" in rep.json()["detail"]
    assert await pool.fetchval("SELECT count(*) FROM audit WHERE action = 'action.refusee_par_regle'") >= 2
    # Le motif n'est jamais écrit dans l'audit (il peut nommer un sujet exclu)
    assert (
        await pool.fetchval(
            "SELECT count(*) FROM audit WHERE action IN ('regle.ajoutee', 'action.refusee_par_regle')"
            " AND lower(details::text) LIKE '%secret%'"
        )
        == 0
    )


@pytest.mark.base
async def test_regle_ecarte_une_action_proposee_par_jarvis(systeme: dict[str, Any]) -> None:
    client, script = systeme["client"], systeme["script"]
    await client.post("/v1/regles", json={"genre": "interdire", "motif": "brevets", "libelle": "Pas de brevets"})
    script.texte = '<actions>[{"type": "proposer_mission", "objectif": "Déposer des brevets"}]</actions>Ok.'
    fin = (await dialoguer(client, "x"))["fin"]
    assert fin["actions"] == [] and "règle de protection" in fin["actions_ecartees"][0]
    # Les règles sont données au modèle, en silence
    assert "Pas de brevets" in script.recus[0].contenu


@pytest.mark.base
async def test_retirer_une_regle_est_jaune(systeme: dict[str, Any], pool: Base) -> None:
    client = systeme["client"]
    regle = (await client.post("/v1/regles", json={"genre": "interdire", "motif": "*secret*"})).json()["regle"]
    rep = (await client.post(f"/v1/regles/{regle['id']}/retirer")).json()
    assert rep["statut"] == "en_attente" and rep["demande"]["niveau"] == "jaune"
    assert rep["demande"]["toujours_possible"] is False  # affaiblir une protection se décide à chaque fois
    # La règle ne bloque pas son propre retrait
    ok = (await client.post(f"/v1/demandes/{rep['demande']['id']}/approuver", json={})).json()
    assert ok["statut"] == "executee"
    assert await pool.fetchval("SELECT count(*) FROM regles_protection") == 0


@pytest.mark.base
async def test_regle_demander_impose_la_demande(systeme: dict[str, Any], pool: Base) -> None:
    client, ctx = systeme["client"], systeme["ctx"]
    conv = await creer_conversation(pool, "Notes")
    # Une première approbation « toujours autoriser »…
    d = (
        await client.post(
            "/v1/actions", json={"action": "conversation.archiver", "parametres": {"conversation_id": conv}}
        )
    ).json()
    assert d["demande"]["toujours_possible"] is True
    await client.post(f"/v1/demandes/{d['demande']['id']}/approuver", json={"toujours": True})
    # …puis une règle « demander » : elle passe avant l'autorisation permanente
    await client.post("/v1/regles", json={"genre": "demander", "motif": "notes"})
    conv2 = await creer_conversation(pool, "Notes")
    rep = (
        await client.post(
            "/v1/actions",
            json={"action": "conversation.archiver", "parametres": {"conversation_id": conv2, "titre": "Notes"}},
        )
    ).json()
    assert rep["statut"] == "en_attente" and rep["regle"]
    assert ctx is not None


@pytest.mark.base
async def test_tester_un_motif(systeme: dict[str, Any]) -> None:
    client = systeme["client"]
    r = (await client.post("/v1/motifs/tester", json={"motif": "va sur {vue}", "texte": "Va sur Coûts"})).json()
    assert r == {"valide": True, "correspond": True, "captures": {"vue": "Coûts"}}
    r = (await client.post("/v1/motifs/tester", json={"motif": "*", "texte": "x"})).json()
    assert r["valide"] is False


# --- « Toujours autoriser » ---------------------------------------------------------------------------------


@pytest.mark.base
async def test_toujours_autoriser_une_action_jaune(systeme: dict[str, Any], pool: Base) -> None:
    client = systeme["client"]
    c1, c2 = await creer_conversation(pool), await creer_conversation(pool)
    d = (
        await client.post(
            "/v1/actions", json={"action": "conversation.archiver", "parametres": {"conversation_id": c1}}
        )
    ).json()
    ok = (await client.post(f"/v1/demandes/{d['demande']['id']}/approuver", json={"toujours": True})).json()
    assert ok["statut"] == "executee"
    # La suivante s'exécute sans demande
    rep = (
        await client.post(
            "/v1/actions", json={"action": "conversation.archiver", "parametres": {"conversation_id": c2}}
        )
    ).json()
    assert rep["statut"] == "executee" and rep["toujours_autorisee"] is True
    assert await pool.fetchval("SELECT archivee FROM conversations WHERE id = $1::uuid", c2) is True
    liste = (await client.get("/v1/autorisations")).json()["autorisations"]
    assert [a["action"] for a in liste] == ["conversation.archiver"] and liste[0]["utilisations"] == 1
    # Retirer protège : la suivante redemande
    assert (await client.post("/v1/autorisations/conversation.archiver/retirer")).json() == {"retiree": True}
    c3 = await creer_conversation(pool)
    rep = (
        await client.post(
            "/v1/actions", json={"action": "conversation.archiver", "parametres": {"conversation_id": c3}}
        )
    ).json()
    assert rep["statut"] == "en_attente"


@pytest.mark.base
async def test_toujours_autoriser_refuse_pour_rouge_et_non_autorisable(systeme: dict[str, Any], pool: Base) -> None:
    client, ctx = systeme["client"], systeme["ctx"]
    d = (
        await client.post(
            "/v1/actions",
            json={
                "action": "conversation.supprimer",
                "parametres": {"conversation_id": await creer_conversation(pool)},
            },
        )
    ).json()
    assert d["demande"]["toujours_possible"] is False
    # Même avec une clé d'accès, « toujours » est refusé pour une action 🔴
    cle = Authentificateur()
    options = (await client.post("/v1/cles/enregistrement/options")).json()
    await client.post("/v1/cles/enregistrement", json={"credential": cle.creer(options), "nom": "Clé"})
    defi = (await client.post(f"/v1/demandes/{d['demande']['id']}/options")).json()
    refus = await client.post(
        f"/v1/demandes/{d['demande']['id']}/approuver", json={"credential": cle.signer(defi), "toujours": True}
    )
    assert refus.status_code == 409 and "Toujours autoriser" in refus.json()["detail"]
    assert await pool.fetchval("SELECT count(*) FROM autorisations_permanentes") == 0
    # Une action 🔴 n'est jamais exécutée sans clé, même insérée de force dans les autorisations
    await pool.execute("INSERT INTO autorisations_permanentes (action) VALUES ('conversation.supprimer')")
    rep = (
        await client.post(
            "/v1/actions",
            json={
                "action": "conversation.supprimer",
                "parametres": {"conversation_id": await creer_conversation(pool)},
            },
        )
    ).json()
    assert rep["statut"] == "en_attente" and rep["demande"]["niveau"] == "rouge"
    # Un outil MCP (clic, navigateur…) n'est jamais « toujours autorisable »
    actions = {a["nom"]: a for a in (await client.get("/v1/actions")).json()["actions"]}
    assert actions["conversation.archiver"]["toujours_possible"] is True
    assert actions["conversation.supprimer"]["toujours_possible"] is False
    assert ctx.approbations.registre.actions["regle.supprimer"].peut_etre_toujours_autorisee is False


def test_outil_mcp_jamais_toujours_autorisable() -> None:
    from jarvis2.agents.mcp import GestionnaireMCP
    from jarvis2.securite.actions import creer_registre
    from jarvis2.securite.urgence import ArretUrgence

    registre = creer_registre(ArretUrgence(), GestionnaireMCP.depuis_config([]))
    assert registre.actions["mcp.appeler"].peut_etre_toujours_autorisee is False


# --- Commandes rapides --------------------------------------------------------------------------------------


@pytest.mark.base
async def test_commande_rapide_interface_sans_ia(systeme: dict[str, Any], pool: Base) -> None:
    client, script = systeme["client"], systeme["script"]
    corps = {
        "motif": "ouvre * missions",
        "cible": "interface",
        "action": "naviguer",
        "parametres": {"vue": "agents"},
        "phrase_test": "ouvre les missions",
    }
    cree = await client.post("/v1/commandes-rapides", json=corps)
    assert cree.status_code == 200, cree.text
    assert cree.json()["commande"]["niveau"] == "vert"
    rep = (await client.post("/v1/commandes-rapides/executer", json={"phrase": "Ouvre mes Missions !"})).json()
    assert rep["trouvee"] and rep["action"]["type"] == "naviguer" and rep["action"]["parametres"] == {"vue": "agents"}
    assert script.recus == []  # aucune IA
    assert (await client.post("/v1/commandes-rapides/executer", json={"phrase": "Bonjour JARVIS"})).json() == {
        "trouvee": False
    }
    assert await pool.fetchval("SELECT utilisations FROM commandes_rapides") == 1


@pytest.mark.base
async def test_commande_rapide_core_passe_par_les_approbations(systeme: dict[str, Any], pool: Base) -> None:
    client = systeme["client"]
    conv = await creer_conversation(pool, "Brouillon")
    corps = {
        "motif": "range la conversation {id}",
        "cible": "core",
        "action": "conversation.archiver",
        "parametres": {"conversation_id": "{id}"},
        "phrase_test": f"range la conversation {conv}",
    }
    commande = (await client.post("/v1/commandes-rapides", json=corps)).json()["commande"]
    assert commande["niveau"] == "jaune"
    rep = (await client.post("/v1/commandes-rapides/executer", json={"phrase": f"Range la conversation {conv}"})).json()
    assert rep["resultat"]["statut"] == "en_attente"  # 🟡 : la commande ne donne aucun droit en plus
    assert await pool.fetchval("SELECT archivee FROM conversations WHERE id = $1::uuid", conv) is False


@pytest.mark.base
async def test_commande_rapide_validations(systeme: dict[str, Any]) -> None:
    client = systeme["client"]
    base = {
        "motif": "ouvre les couts",
        "cible": "interface",
        "action": "naviguer",
        "parametres": {"vue": "couts"},
        "phrase_test": "ouvre les coûts",
    }
    assert (await client.post("/v1/commandes-rapides", json=base)).status_code == 200
    # Phrase de test qui ne correspond pas
    r = await client.post("/v1/commandes-rapides", json={**base, "phrase_test": "autre chose"})
    assert r.status_code == 422 and "phrase de test" in r.json()["detail"]
    # Jamais de shell, ni d'action inconnue
    for cible, action in (
        ("core", "shell"),
        ("core", "executer_commande"),
        ("interface", "proposer_mission"),
        ("systeme", "naviguer"),
    ):
        r = await client.post("/v1/commandes-rapides", json={**base, "cible": cible, "action": action})
        assert r.status_code == 422, (cible, action)
    # Vue inconnue
    r = await client.post("/v1/commandes-rapides", json={**base, "parametres": {"vue": "c:/windows"}})
    assert r.status_code == 422
    # Capture absente du motif
    r = await client.post(
        "/v1/commandes-rapides", json={**base, "action": "rechercher_memoire", "parametres": {"requete": "{sujet}"}}
    )
    assert r.status_code == 422
    # Vérifier sans enregistrer : conflits signalés
    v = (await client.post("/v1/commandes-rapides/verifier", json={**base, "motif": "ouvre *"})).json()
    assert v["valide"] and [c["motif"] for c in v["conflits"]] == ["ouvre les couts"]


@pytest.mark.base
async def test_commande_rapide_priorite_puis_precision(systeme: dict[str, Any]) -> None:
    client = systeme["client"]
    large = {
        "motif": "ouvre *",
        "cible": "interface",
        "action": "naviguer",
        "parametres": {"vue": "dialogue"},
        "phrase_test": "ouvre x",
    }
    precis = {
        "motif": "ouvre les couts",
        "cible": "interface",
        "action": "naviguer",
        "parametres": {"vue": "couts"},
        "phrase_test": "ouvre les couts",
    }
    await client.post("/v1/commandes-rapides", json=large)
    await client.post("/v1/commandes-rapides", json=precis)
    rep = (await client.post("/v1/commandes-rapides/executer", json={"phrase": "ouvre les coûts"})).json()
    assert rep["action"]["parametres"]["vue"] == "couts"  # priorité égale : le plus précis
    ident = rep["commande"]["id"]
    liste = (await client.get("/v1/commandes-rapides")).json()["commandes"]
    autre = next(c for c in liste if c["id"] != ident)
    await client.put(f"/v1/commandes-rapides/{autre['id']}", json={**large, "priorite": 10})
    rep = (await client.post("/v1/commandes-rapides/executer", json={"phrase": "ouvre les coûts"})).json()
    assert rep["action"]["parametres"]["vue"] == "dialogue"  # priorité réglée : elle l'emporte
    # Désactivée : ignorée
    await client.put(f"/v1/commandes-rapides/{autre['id']}", json={**large, "priorite": 10, "actif": False})
    rep = (await client.post("/v1/commandes-rapides/executer", json={"phrase": "ouvre les coûts"})).json()
    assert rep["action"]["parametres"]["vue"] == "couts"
    assert (await client.delete(f"/v1/commandes-rapides/{autre['id']}")).json() == {"supprimee": True}
    assert (await client.delete(f"/v1/commandes-rapides/{autre['id']}")).status_code == 404
