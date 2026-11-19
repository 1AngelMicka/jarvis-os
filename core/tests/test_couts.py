"""Coûts et transparence : jauges d'abonnement (rate_limit_event), dépenses par connecteur, plafond, pied de réponse."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis2 import couts
from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.connecteurs import Connecteurs, Definition
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import ServiceDialogue
from jarvis2.moteurs.base import (
    Delta,
    ErreurMoteur,
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
from jarvis2.moteurs.claude_code import Jauge, lire_limite
from jarvis2.moteurs.telemetrie import EnregistreurBase, Mesure, MoteurInstrumente
from jarvis2.securite import appareils

from .test_claude_code import MESSAGES, moteur

MAINTENANT = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


# --- Jauges d'abonnement ----------------------------------------------------------------------------------


def test_lire_limite_tolerant() -> None:
    j = lire_limite(
        {
            "type": "rate_limit_event",
            "rate_limit_info": {
                "status": "allowed",
                "rateLimitType": "five_hour",
                "utilization": 0.25,
                "resetsAt": 1_800_000_000,
            },
        },
        MAINTENANT,
    )
    assert j is not None and j.type == "five_hour" and j.utilisation == 0.25 and j.mesure_le == MAINTENANT
    assert j.reinitialisation == datetime.fromtimestamp(1_800_000_000, UTC)
    pourcent = lire_limite({"type": "rate_limit_event", "rateLimitType": "seven_day", "utilization": 42})
    assert pourcent is not None and pourcent.utilisation == pytest.approx(0.42)
    millis = lire_limite({"type": "rate_limit_event", "rateLimitType": "x", "resetsAt": 1_800_000_000_000})
    assert millis is not None and millis.reinitialisation == datetime.fromtimestamp(1_800_000_000, UTC)
    sans = lire_limite({"type": "rate_limit_event", "rate_limit_info": {"rateLimitType": "seven_day"}})
    assert sans is not None and sans.utilisation is None  # jamais 0 par défaut
    assert lire_limite({"type": "rate_limit_event", "rate_limit_info": {}}) is None
    assert lire_limite({"type": "result"}) is None
    assert Jauge.depuis_dict(j.en_dict()) == j


def test_jauges_inconnues_mesurees_puis_perimees() -> None:
    vides = couts.decrire_jauges([], MAINTENANT)
    assert [(g["type"], g["etat"]) for g in vides] == [("five_hour", "inconnu"), ("seven_day", "inconnu")]
    assert all("utilisation" not in g for g in vides)  # inconnu, pas 0
    recente = Jauge("five_hour", "allowed", 0.5, MAINTENANT + timedelta(hours=2), MAINTENANT - timedelta(minutes=5))
    ancienne = Jauge("five_hour", "allowed", 0.1, None, MAINTENANT - timedelta(hours=2))
    opus = Jauge("seven_day_opus", "allowed", 0.3, None, MAINTENANT - timedelta(minutes=31))
    g = {x["type"]: x for x in couts.decrire_jauges([ancienne, recente, opus], MAINTENANT)}
    assert (
        g["five_hour"]["etat"] == "mesure" and g["five_hour"]["utilisation"] == 0.5 and g["five_hour"]["age_s"] == 300
    )
    assert g["seven_day"]["etat"] == "inconnu"
    assert g["seven_day_opus"]["etat"] == "perime" and g["seven_day_opus"]["nom"] == "7 jours (Opus)"
    passee = Jauge("five_hour", "rejected", 1.0, MAINTENANT - timedelta(minutes=1), MAINTENANT - timedelta(minutes=2))
    assert couts.decrire_jauges([passee], MAINTENANT)[0]["etat"] == "perime"  # fenêtre déjà réinitialisée


async def test_flux_stream_json_avec_rate_limit_event(tmp_path: Path) -> None:
    m = moteur("limites", tmp_path)
    evenements = [e async for e in m.stream(MESSAGES)]
    fin = evenements[-1]
    assert isinstance(fin, Fin) and fin.reponse.texte == "Bonjour, Monsieur."
    limites = {x["type"]: x for x in fin.reponse.meta["limites"]}
    assert limites["five_hour"]["utilisation"] == pytest.approx(0.42)
    assert limites["five_hour"]["statut"] == "allowed_warning" and limites["five_hour"]["reinitialisation"]
    assert limites["seven_day"]["utilisation"] is None
    assert set(m.jauges) == {"five_hour", "seven_day"}
    g = {x["type"]: x for x in couts.decrire_jauges(m.jauges.values())}
    assert g["five_hour"]["etat"] == "mesure" and g["seven_day"]["etat"] == "mesure"


async def test_limite_atteinte_mesuree_meme_en_erreur(tmp_path: Path) -> None:
    m = moteur("refuse", tmp_path)
    with pytest.raises(ErreurMoteur, match="5 heures"):
        _ = [e async for e in m.stream(MESSAGES)]
    assert m.jauges["five_hour"].statut == "rejected" and m.jauges["five_hour"].utilisation == 1.0


# --- Dépenses, plafond, pied de réponse ----------------------------------------------------------------------


class Payant(Moteur):
    def __init__(self, ident: str, famille: str, cout: float = 0.0, texte: str = "ok") -> None:
        self.id, self.nom, self.famille = ident, f"Faux {ident}", famille  # type: ignore[assignment]
        self.externe = famille != "local"
        self.actif_par_defaut = True
        self.cout, self.texte = cout, texte

    async def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        yield Delta(self.texte)
        meta: dict[str, Any] = {"cout_estime": True} if self.cout else {}
        if self.famille == "cli":
            meta["cout_equivalent_api_usd"] = 0.01
        yield Fin(Reponse(self.texte, f"{self.id}-1", Usage(100, 20), self.cout, meta))

    async def list_models(self) -> list[InfoModele]:
        return [InfoModele(f"{self.id}-1", self.id, True)]

    async def health(self) -> EtatSante:
        return EtatSante(True, "prêt")


@pytest.fixture
async def systeme(pool: Base, tmp_path: Path) -> dict[str, Any]:
    from jarvis2.securite.coffre import Coffre

    moteurs = {
        "compte": Payant("compte", "cli", texte="par le compte"),
        "cle": Payant("cle", "api", cout=4.0, texte="par l'API"),
        "local": Payant("local", "local", texte="en local"),
    }
    defs = {
        i: Definition(MoteurInstrumente(m, EnregistreurBase(pool)), "cle" if i == "cle" else None)
        for i, m in moteurs.items()
    }
    connecteurs = Connecteurs(pool, defs, Coffre(tmp_path / "coffre.json"), prefere="cle")
    await connecteurs.charger()
    depot = DepotConversations(pool)
    service = ServiceDialogue(depot, connecteurs.moteurs, "compte", None, connecteurs)
    service.titre_auto = False  # un titre automatique serait un appel payant de plus
    ctx = Contexte(pool, depot, connecteurs.moteurs, service, "compte", connecteurs=connecteurs)
    app = creer_app(Parametres(), ctx)
    app.state.ctx = ctx
    _, jeton = await appareils.creer(pool, "PC", "pc")
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost:8765",
        headers={"Authorization": f"Bearer {jeton}"},
    )
    return {"client": client, "connecteurs": connecteurs, "service": service, "pool": pool}


async def test_depenses_par_connecteur_jour_et_mois(systeme: dict[str, Any], pool: Base) -> None:
    enregistreur = EnregistreurBase(pool)
    await enregistreur.enregistrer(Mesure("cle", "m", "stream", "ok", 10, jetons_entree=7, cout_usd=1.5))
    await enregistreur.enregistrer(Mesure("cle", "m", "stream", "erreur", 10))
    await enregistreur.enregistrer(
        Mesure("compte", "s", "stream", "ok", 10, jetons_sortie=3, meta={"cout_equivalent_api_usd": 0.2})
    )
    hier = couts.debut_jour() - timedelta(hours=1)
    await pool.execute(
        "INSERT INTO telemetrie (moteur, operation, statut, latence_ms, cout_usd, cree_le) VALUES ('cle', 'stream',"
        " 'ok', 5, 2.0, $1)",
        hier.astimezone(UTC),
    )
    r = (await systeme["client"].get("/v1/couts")).json()
    cartes = {c["id"]: c for c in r["connecteurs"]}
    cle = cartes["cle"]
    assert cle["payant"] and cle["jour"]["cout_usd"] == 1.5 and cle["jour"]["appels"] == 2
    assert cle["jour"]["erreurs"] == 1 and cle["jour"]["jetons_entree"] == 7 and cle["plafond"] is None
    attendu_mois = 3.5 if hier >= couts.debut_mois() else 1.5
    assert cle["mois"]["cout_usd"] == attendu_mois and r["total_mois_usd"] == attendu_mois
    assert cartes["compte"]["equivalent_api_usd"] == 0.2 and not cartes["compte"]["payant"]
    assert len(r["jours"]) == couts.JOURS_HISTORIQUE and r["jours"][-1]["cout_usd"] == 1.5
    assert r["jours"][-2]["par_connecteur"] == {"cle": 2.0}
    assert [g["etat"] for g in r["jauges"]] == ["inconnu", "inconnu"]


async def test_plafond_alerte_puis_refus_et_autre_ia(systeme: dict[str, Any]) -> None:
    client, service, c = systeme["client"], systeme["service"], systeme["connecteurs"]
    assert (await client.put("/v1/connecteurs/compte/plafond", json={"plafond_usd": 5})).status_code == 422
    assert (await client.put("/v1/connecteurs/cle/plafond", json={"plafond_usd": -1})).status_code == 422
    assert (await client.put("/v1/connecteurs/cle/plafond", json={"plafond_usd": 10})).status_code == 200
    assert c.plafond("cle") == 10
    # 4 $ puis 8 $ : alerte à 80 % sous la deuxième réponse, avec le pied (durée, jetons, coût estimé)
    premiere = [e async for e in service.repondre("Un")]
    fin = next(e for e in premiere if e.type == "fin").donnees
    assert fin["moteur"] == "cle" and "plafond" not in fin
    assert fin["cout_usd"] == 4.0 and fin["cout_estime"] and fin["jetons_entree"] == 100
    assert isinstance(fin["duree_ms"], int)
    deuxieme = [e async for e in service.repondre("Deux")]
    alerte = next(e for e in deuxieme if e.type == "fin").donnees["plafond"]
    assert alerte["alerte"] and not alerte["atteint"] and alerte["part"] == 0.8
    # 12 $ : plafond dépassé ; le routeur passe à une autre IA
    _ = [e async for e in service.repondre("Trois")]
    assert await c.plafond_atteint("cle")
    assert await c.router() == "compte"
    # Choix explicite du connecteur au plafond : avertissement clair, réponse par une autre IA
    evs = [e async for e in service.repondre("Quatre", moteur="cle")]
    assert "Plafond de dépenses atteint" in evs[0].donnees["avertissement"]
    assert next(e for e in evs if e.type == "fin").donnees["moteur"] == "compte"
    # Appel direct (conseil, titres, missions) : refus clair par la garde de la télémétrie
    with pytest.raises(ErreurMoteur, match="Plafond de dépenses atteint"):
        _ = [e async for e in c.moteurs["cle"].stream(MESSAGES)]
    r = (await client.get("/v1/couts")).json()
    carte = next(x for x in r["connecteurs"] if x["id"] == "cle")
    assert carte["plafond"]["atteint"] and carte["estime"]
    # Plafond retiré : le connecteur reprend
    assert (await client.put("/v1/connecteurs/cle/plafond", json={"plafond_usd": None})).status_code == 200
    assert not await c.plafond_atteint("cle") and await c.router() == "cle"


async def test_plafond_atteint_sans_autre_ia_refuse(systeme: dict[str, Any]) -> None:
    client, service, c = systeme["client"], systeme["service"], systeme["connecteurs"]
    assert (await client.put("/v1/connecteurs/cle/plafond", json={"plafond_usd": 0})).status_code == 200
    for ident in ("compte", "local"):
        assert (await client.post(f"/v1/connecteurs/{ident}/desactiver")).status_code == 200
    assert await c.router() is None
    with pytest.raises(ErreurMoteur, match="Plafond de dépenses atteint"):
        _ = [e async for e in service.repondre("Salut", moteur="cle")]
    carte = next(x for x in (await client.get("/v1/connecteurs")).json()["connecteurs"] if x["id"] == "cle")
    assert carte["payant"] and carte["plafond_mensuel_usd"] == 0
