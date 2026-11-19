"""Routeur par type de tâche (14 · B 11) : classifieur local, routes, privé jamais externe, scores mesurés dans
`telemetrie`, rétrogradation et rétablissement, retours de l'utilisateur."""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis2 import routage
from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.connecteurs import Connecteurs, Definition
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import ServiceDialogue
from jarvis2.moteurs.base import (
    Delta,
    EtatSante,
    Evenement,
    Fin,
    InfoModele,
    Message,
    Moteur,
    Options,
    Reponse,
    Usage,
)
from jarvis2.moteurs.telemetrie import EnregistreurBase, Mesure, MoteurInstrumente
from jarvis2.securite import appareils

CODE = "Peux-tu corriger ce code ?\n```python\nprint(1\n```"
HESITANT = (
    "J'ai repensé à la discussion d'hier avec mes voisins au sujet du jardin partagé, et je me demande ce que tu en "
    "penses, sans urgence."
)


class Faux(Moteur):
    def __init__(self, ident: str, famille: str, texte: str = "ok", disponible: bool = True) -> None:
        self.id, self.nom, self.famille = ident, f"Faux {ident}", famille  # type: ignore[assignment]
        self.externe = famille != "local"
        self.actif_par_defaut = True
        self.texte, self.disponible = texte, disponible
        self.appels: list[Options | None] = []

    async def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        self.appels.append(options)
        yield Delta(self.texte)
        yield Fin(Reponse(self.texte, (options.modele if options else None) or f"{self.id}-1", Usage(10, 2), 0.0, {}))

    async def list_models(self) -> list[InfoModele]:
        return [InfoModele(f"{self.id}-1", self.id, True), InfoModele("petit:0.5b", self.id, False)]

    async def health(self) -> EtatSante:
        return EtatSante(self.disponible, "prêt" if self.disponible else "arrêté")


# --- Règles -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [
        (CODE, "code"),
        ("Traceback (most recent call last):\n  File x\nValueError: non", "code"),
        ("Comment écrire une regex Python pour les dates ?", "code"),
        ("Pourquoi le télétravail est-il plus fatigant ? Compare les avantages et inconvénients.", "raisonnement"),
        ("Traduis « bonne nuit » en anglais", "rapide"),
        ("Salut !", "rapide"),
    ],
)
def test_regles_classent_et_disent_pourquoi(texte: str, attendu: str) -> None:
    c = routage.classer_regles(texte)
    assert c is not None and c.type == attendu and c.source == "regles"
    assert c.raison.startswith("règles : ")


def test_regles_hesitent_sans_signal_ou_a_egalite() -> None:
    assert routage.classer_regles(HESITANT) is None
    assert "aucune règle nette" in routage.raison_hesitation(HESITANT)
    assert routage.lire_mot("Code.") == "code" and routage.lire_mot("Je ne sais pas") is None


def test_score_mesure_succes_latence_et_avis() -> None:
    s = routage.Score("rapide", "x", appels=5, succes=5, latence_totale_ms=5 * 1000)
    assert s.valeur == 100 and s.etat == "bon"
    mal_note = routage.Score("rapide", "x", appels=5, succes=5, latence_totale_ms=5 * 1000, negatifs=2)
    assert mal_note.valeur == 50 and mal_note.etat == "retrogradee"
    lent = routage.Score("rapide", "x", appels=5, succes=5, latence_totale_ms=5 * 40_000)
    assert lent.valeur is not None and 70 <= lent.valeur < 80
    assert routage.Score("code", "x", appels=2, erreurs=2).etat == "rodage"  # trop peu de mesures


# --- Dialogue et API ------------------------------------------------------------------------------------------


@pytest.fixture
async def systeme(pool: Base, tmp_path: Path) -> dict[str, Any]:
    from jarvis2.securite.coffre import Coffre

    moteurs = {
        "compte": Faux("compte", "cli", "par le compte"),
        "cle": Faux("cle", "api", "par l'API"),
        "local": Faux("local", "local", "en local"),
        "ollama": Faux("ollama", "local", "code"),
    }
    defs = {i: Definition(MoteurInstrumente(m, EnregistreurBase(pool)), None) for i, m in moteurs.items()}
    connecteurs = Connecteurs(pool, defs, Coffre(tmp_path / "coffre.json"), prefere="compte")
    await connecteurs.charger()
    depot = DepotConversations(pool)
    service = ServiceDialogue(
        depot, connecteurs.moteurs, "compte", None, connecteurs, sujets_prives=(re.compile("santé", re.I),)
    )
    service.titre_auto = False
    ctx = Contexte(pool, depot, connecteurs.moteurs, service, "compte", connecteurs=connecteurs)
    app = creer_app(Parametres(), ctx)
    app.state.ctx = ctx
    _, jeton = await appareils.creer(pool, "PC", "pc")
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost:8765",
        headers={"Authorization": f"Bearer {jeton}"},
    )
    return {"client": client, "service": service, "moteurs": moteurs, "pool": pool, "connecteurs": connecteurs}


async def _fin(service: ServiceDialogue, texte: str, **kw: Any) -> dict[str, Any]:
    evs = [e async for e in service.repondre(texte, **kw)]
    return next(e for e in evs if e.type == "fin").donnees


async def _audit(pool: Base, action: str) -> int:
    return int(await pool.fetchval("SELECT count(*) FROM audit WHERE action = $1", action) or 0)


async def test_route_par_type_avec_raison_et_mesure(systeme: dict[str, Any]) -> None:
    client, service, pool = systeme["client"], systeme["service"], systeme["pool"]
    r = await client.put("/v1/routes/code", json={"connecteur": "cle", "modele": "gros-code"})
    assert r.status_code == 200
    fin = await _fin(service, CODE)
    assert fin["moteur"] == "cle" and fin["modele"] == "gros-code"
    route = fin["route"]
    assert route["type"] == "code" and route["source"] == "regles" and "bloc de code" in route["raison"]
    # Un message rapide garde le routeur habituel (préféré : le compte)
    rapide = await _fin(service, "Traduis « merci » en italien")
    assert rapide["moteur"] == "compte" and rapide["route"]["type"] == "rapide"
    lignes = await pool.fetch("SELECT moteur, meta FROM telemetrie WHERE operation = 'stream' ORDER BY id")
    assert [(lg["moteur"], routage._meta(lg["meta"]).get("route")) for lg in lignes] == [
        ("cle", "code"),
        ("compte", "rapide"),
    ]
    # Choix explicite : aucune route (le score ne mesure que les choix du routeur)
    impose = await _fin(service, CODE, moteur="local")
    assert impose["moteur"] == "local" and "route" not in impose


async def test_prive_ne_part_jamais_vers_un_moteur_externe(systeme: dict[str, Any]) -> None:
    client, service = systeme["client"], systeme["service"]
    r = await client.put("/v1/routes/prive", json={"connecteur": "cle"})
    assert r.status_code == 422 and "jamais vers un moteur externe" in r.json()["detail"]
    assert (await client.put("/v1/routes/prive", json={"connecteur": "local"})).status_code == 200
    fin = await _fin(service, "Mon rendez-vous santé de jeudi, en code ```x```")
    assert fin["moteur"] == "local" and fin["route"]["type"] == "prive" and fin["route"]["source"] == "prive"
    # Plus aucune IA locale : refus plutôt qu'une fuite
    for ident in ("local", "ollama"):
        assert (await client.post(f"/v1/connecteurs/{ident}/desactiver")).status_code == 200
    from jarvis2.moteurs.base import ErreurMoteur

    with pytest.raises(ErreurMoteur, match="Sujet privé"):
        await _fin(service, "Question de santé")
    tableau = (await client.get("/v1/routes")).json()
    prive = next(t for t in tableau["types"] if t["type"] == "prive")
    assert prive["actuel"] is None and all(c["connecteur"] in ("local", "ollama") for c in prive["candidats"])


async def test_retrogradation_puis_retablissement(systeme: dict[str, Any]) -> None:
    client, service, pool = systeme["client"], systeme["service"], systeme["pool"]
    avant = await _audit(pool, "routage.retrogradation")
    assert (await client.put("/v1/routes/code", json={"connecteur": "cle"})).status_code == 200
    enregistreur = EnregistreurBase(pool)
    for _ in range(routage.MIN_MESURES):
        await enregistreur.enregistrer(Mesure("cle", "m", "stream", "erreur", 50, meta={"route": "code"}))
    tableau = (await client.get("/v1/routes")).json()
    code = next(t for t in tableau["types"] if t["type"] == "code")
    cle = next(c for c in code["candidats"] if c["connecteur"] == "cle")
    assert cle["etat"] == "retrogradee" and cle["score"] == 0 and cle["erreurs"] == routage.MIN_MESURES
    assert code["actuel"] == "compte"
    assert tableau["historique"][0]["evenement"] == "retrogradee" and "erreurs" in tableau["historique"][0]["raison"]
    assert await _audit(pool, "routage.retrogradation") == avant + 1
    fin = await _fin(service, CODE)
    assert fin["moteur"] == "compte" and fin["route"]["retrogradees"] == [{"connecteur": "cle", "score": 0}]
    assert await _audit(pool, "routage.retrogradation") == avant + 1  # notée une seule fois
    # Rétablie par l'utilisateur : mesures d'avant ignorées, la route reprend
    r = await client.post("/v1/routes/code/retablir", json={"connecteur": "cle"})
    assert r.status_code == 200
    assert r.json()["historique"][0]["evenement"] == "retablie"
    assert (await _fin(service, CODE))["moteur"] == "cle"


async def test_retrogradation_des_mesures_anciennes_ignoree(systeme: dict[str, Any]) -> None:
    pool = systeme["pool"]
    vieux = (datetime.now(UTC) - routage.FENETRE - timedelta(hours=1)).astimezone(UTC)
    for _ in range(routage.MIN_MESURES):
        await pool.execute(
            "INSERT INTO telemetrie (moteur, operation, statut, latence_ms, meta, cree_le)"
            " VALUES ('cle', 'stream', 'erreur', 5, $1, $2)",
            {"route": "code"},
            vieux,
        )
    assert await routage.calculer_scores(pool) == {}


async def test_retours_de_l_utilisateur(systeme: dict[str, Any]) -> None:
    client, service, pool = systeme["client"], systeme["service"], systeme["pool"]
    fin = await _fin(service, "Traduis « oui » en espagnol")
    ident = fin["message_id"]
    for avis in ("positif", "negatif"):  # le dernier avis compte
        r = await client.post(f"/v1/messages/{ident}/retour", json={"avis": avis})
        assert r.status_code == 200 and r.json()["retour"] == avis
    scores = await routage.calculer_scores(pool)
    s = scores[("rapide", "compte")]
    assert (s.positifs, s.negatifs, s.appels) == (0, 1, 1)
    assert routage._meta(await pool.fetchval("SELECT meta FROM messages WHERE id = $1", ident))["retour"] == "negatif"
    assert (await client.post(f"/v1/messages/{ident}/retour", json={"avis": None})).status_code == 200
    assert (await routage.calculer_scores(pool))[("rapide", "compte")].negatifs == 0
    # Réponse non routée : rien à noter ; message inconnu : 404
    impose = await _fin(service, "Bonjour", moteur="cle")
    assert (
        await client.post(f"/v1/messages/{impose['message_id']}/retour", json={"avis": "positif"})
    ).status_code == 422
    assert (await client.post("/v1/messages/999999/retour", json={"avis": "positif"})).status_code == 404
    # Les retours ne comptent pas comme des appels dans les coûts
    resume = (await client.get("/v1/couts")).json()
    compte = next(c for c in resume["connecteurs"] if c["id"] == "compte")
    assert compte["jour"]["appels"] == 1


async def test_petit_modele_seulement_si_les_regles_hesitent_et_ollama_tourne(systeme: dict[str, Any]) -> None:
    client, moteurs = systeme["client"], systeme["moteurs"]
    essai = (await client.post("/v1/routes/essai", json={"texte": HESITANT})).json()
    assert essai["source"] == "defaut" and essai["type"] == "rapide" and "par défaut" in essai["raison"]
    assert moteurs["ollama"].appels == []  # aucun modèle choisi : jamais appelé
    tableau = (await client.put("/v1/routes/classifieur", json={"modele": "petit:0.5b"})).json()
    assert tableau["classifieur"]["modele"] == "petit:0.5b" and "petit:0.5b" in tableau["classifieur"]["modeles"]
    essai = (await client.post("/v1/routes/essai", json={"texte": HESITANT})).json()
    assert essai["source"] == "modele" and essai["type"] == "code" and "petit:0.5b" in essai["raison"]
    assert len(moteurs["ollama"].appels) == 1
    # Règles nettes : le petit modèle n'est pas consulté
    assert (await client.post("/v1/routes/essai", json={"texte": CODE})).json()["source"] == "regles"
    assert len(moteurs["ollama"].appels) == 1
    # Ollama arrêté : jamais démarré, les règles décident seules
    moteurs["ollama"].disponible = False
    essai = (await client.post("/v1/routes/essai", json={"texte": HESITANT})).json()
    assert essai["source"] == "defaut" and "Ollama arrêté" in essai["raison"]
    assert len(moteurs["ollama"].appels) == 1
    tableau = (await client.get("/v1/routes")).json()
    assert not tableau["classifieur"]["ollama_disponible"]


async def test_reglages_valides(systeme: dict[str, Any]) -> None:
    client = systeme["client"]
    assert (await client.put("/v1/routes/inconnu", json={"connecteur": None})).status_code == 404
    assert (await client.put("/v1/routes/code", json={"connecteur": "absent"})).status_code == 404
    tableau = (await client.get("/v1/routes")).json()
    assert [t["type"] for t in tableau["types"]] == list(routage.TYPES)
    assert tableau["seuil"] == routage.SEUIL and tableau["historique"] == []
