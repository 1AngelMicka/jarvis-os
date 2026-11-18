"""Phase 10 : créations en bac à sable, vision sur demande (modèle local), voix (mot d'éveil, transcription)."""

from __future__ import annotations

import base64
import time
from collections.abc import AsyncGenerator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis2 import creations, vision
from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.db import Base
from jarvis2.moteurs.base import Delta, Evenement, Fin, Message, Options, Reponse
from jarvis2.securite import appareils
from jarvis2.voix import analyser_eveil

from .test_agents import Scenario, systeme

pytestmark = pytest.mark.base
PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nfaux").decode()


class Createur(Scenario):
    async def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        self.recus = list(messages)
        version = "2" if "Page actuelle" in messages[-1].contenu else "1"
        page = f"<!doctype html><html><body><h1>Minuteur v{version}</h1><script>1</script></body></html>"
        texte = f"Voici :\n```html\n{page}\n```"
        yield Delta(texte)
        yield Fin(Reponse(texte, "local-1"))


class FauxTranscripteur:
    async def transcrire(self, audio: bytes) -> tuple[str, str | None]:
        assert audio == b"audio"
        return "Dis Jarvis, quelle heure est-il ?", "fr"


async def client(pool: Base, tmp_path: Path) -> tuple[httpx.AsyncClient, Contexte]:
    s = await systeme(pool, tmp_path, {"local": Createur("local", "local", externe=False)})
    ctx = Contexte(
        pool, s["depot"], s["connecteurs"].moteurs, s["service"], "local", connecteurs=s["connecteurs"],
        transcripteur=FauxTranscripteur(), modele_vision="essai-vision", url_ollama="http://ollama.local",
    )  # fmt: skip
    app = creer_app(Parametres(), ctx)
    app.state.ctx = ctx
    _, jeton = await appareils.creer(pool, "PC", "pc")
    c = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost:8765",
        headers={"Authorization": f"Bearer {jeton}"},
    )
    return c, ctx


async def test_creation_dans_un_bac_a_sable_isole(pool: Base, tmp_path: Path) -> None:
    c, _ = await client(pool, tmp_path)
    cree = (await c.post("/v1/creations", json={"titre": "Minuteur", "demande": "Un minuteur de cuisine"})).json()
    lien = (await c.get(f"/v1/creations/{cree['id']}/lien")).json()["url"]
    page = await c.get(lien, headers={"Authorization": ""})  # l'iframe n'envoie pas le jeton d'appareil
    assert page.status_code == 200 and "<h1>Minuteur v1</h1>" in page.text and page.text.startswith("<!doctype html>")
    csp = page.headers["content-security-policy"]
    assert "sandbox allow-scripts" in csp and "allow-same-origin" not in csp  # origine unique, isolée de JARVIS
    assert "connect-src 'none'" in csp and "default-src 'none'" in csp  # aucune requête réseau
    assert "frame-ancestors http://localhost:8765" in csp  # l'interface peut l'afficher, nul autre
    assert page.headers["cache-control"] == "no-store"
    # Lien falsifié ou expiré : refusé
    faux = lien.rsplit("&j=", 1)[0] + "&j=1.abcdef"
    assert (await c.get(faux)).status_code == 403
    expire = creations.jeton(cree["id"], 1, maintenant=time.time() - 2 * creations.DUREE_JETON)
    assert (await c.get(f"/creations/{cree['id']}?v=1&j={expire}")).status_code == 403
    # Modification : nouvelle version, l'ancienne reste
    modif = (await c.post(f"/v1/creations/{cree['id']}/modifier", json={"demande": "Ajoute un bouton pause"})).json()
    assert modif["version"] == 2
    lien2 = (await c.get(f"/v1/creations/{cree['id']}/lien")).json()["url"]
    assert "Minuteur v2" in (await c.get(lien2)).text
    assert [x["titre"] for x in (await c.get("/v1/creations")).json()["creations"]] == ["Minuteur"]


def test_extraire_html() -> None:
    assert creations.extraire_html("bla\n<!DOCTYPE html><p>x</p>") == "<!DOCTYPE html><p>x</p>"
    assert creations.extraire_html("```html\n<html></html>\n```") == "<html></html>"


async def test_vision_sur_demande_par_un_modele_local(
    pool: Base, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, ctx = await client(pool, tmp_path)
    vu: dict[str, Any] = {}

    def ollama(requete: httpx.Request) -> httpx.Response:
        import json

        corps = json.loads(requete.content)
        vu.update(corps)
        return httpx.Response(200, json={"message": {"content": "Une fenêtre de terminal ouverte."}})

    vrai = vision.decrire

    async def decrire(
        url: str, modele: str | None, image: bytes, question: str | None = None, transport: Any = None
    ) -> str:
        return await vrai(url, modele, image, question, httpx.MockTransport(ollama))

    monkeypatch.setattr(vision, "decrire", decrire)
    rep = await c.post("/v1/vision/decrire", json={"image": PNG, "question": "Qu'y a-t-il ?"})
    assert rep.status_code == 200 and rep.json()["description"] == "Une fenêtre de terminal ouverte."
    assert vu["model"] == "essai-vision" and vu["messages"][0]["images"]  # le modèle local reçoit l'image
    assert (await c.post("/v1/vision/decrire", json={"image": "https://exemple.org/x.png"})).status_code == 422
    ctx.modele_vision = None
    sans = await c.post("/v1/vision/decrire", json={"image": PNG})
    assert sans.status_code == 422 and "modele_vision" in sans.json()["detail"]


def test_mot_d_eveil() -> None:
    for phrase, commande in (
        ("Jarvis, quelle heure est-il ?", "quelle heure est-il ?"),
        ("dis Jarvis allume la lumière", "allume la lumière"),
        ("Hé JARVIS !", ""),
    ):
        t = analyser_eveil(phrase)
        assert t.eveil and t.commande == commande
    assert not analyser_eveil("Je parlais de Jarvis hier").eveil


async def test_transcription(pool: Base, tmp_path: Path) -> None:
    c, _ = await client(pool, tmp_path)
    rep = await c.post("/v1/voix/transcrire", content=b"audio", headers={"Content-Type": "audio/webm"})
    assert rep.json() == {
        "texte": "Dis Jarvis, quelle heure est-il ?",
        "eveil": True,
        "commande": "quelle heure est-il ?",
        "langue": "fr",
    }
    assert (await c.post("/v1/voix/transcrire", content=b"")).status_code == 422
