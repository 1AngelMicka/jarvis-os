"""Moteur ollama, avec un transport HTTP simulé (Ollama n'est jamais démarré par les tests)."""

from __future__ import annotations

import json

import httpx
import pytest

from jarvis2.moteurs.base import Delta, ErreurMoteur, Fin, Message
from jarvis2.moteurs.ollama import MoteurOllama


def gestionnaire(requete: httpx.Request) -> httpx.Response:
    if requete.url.path == "/api/version":
        return httpx.Response(200, json={"version": "0.35.1"})
    if requete.url.path == "/api/tags":
        return httpx.Response(200, json={"models": [{"name": "qwen3.5:2b"}, {"name": "gemma4:12b"}]})
    if requete.url.path == "/api/chat":
        corps = json.loads(requete.content)
        assert corps["stream"] is True
        assert [m["role"] for m in corps["messages"]] == ["system", "user"]
        lignes = [
            {"message": {"role": "assistant", "content": "Bon"}, "done": False},
            {"message": {"role": "assistant", "content": "jour"}, "done": False},
            {"message": {"role": "assistant", "content": ""}, "done": True, "prompt_eval_count": 12, "eval_count": 4},
        ]
        return httpx.Response(200, content="\n".join(json.dumps(x) for x in lignes).encode())
    return httpx.Response(404)


MESSAGES = [Message("systeme", "S"), Message("utilisateur", "Salut")]


async def test_flux() -> None:
    m = MoteurOllama(transport=httpx.MockTransport(gestionnaire))
    evenements = [e async for e in m.stream(MESSAGES)]
    assert [e.texte for e in evenements if isinstance(e, Delta)] == ["Bon", "jour"]
    fin = evenements[-1]
    assert isinstance(fin, Fin)
    assert fin.reponse.texte == "Bonjour"
    assert fin.reponse.modele == "gemma4:12b"  # premier modèle par ordre alphabétique
    assert fin.reponse.usage.jetons_entree == 12 and fin.reponse.usage.jetons_sortie == 4
    assert fin.reponse.cout_usd == 0.0
    await m.fermer()


async def test_sante_et_modeles() -> None:
    m = MoteurOllama(transport=httpx.MockTransport(gestionnaire))
    assert (await m.health()).disponible
    assert [x.id for x in await m.list_models()] == ["gemma4:12b", "qwen3.5:2b"]


def refuse(requete: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refusé", request=requete)


async def test_ollama_arrete() -> None:
    m = MoteurOllama(modele="qwen3.5:2b", transport=httpx.MockTransport(refuse))
    sante = await m.health()
    assert not sante.disponible and "arrêté" in sante.detail
    assert await m.list_models() == []
    with pytest.raises(ErreurMoteur, match="arrêté"):
        await m.generate(MESSAGES)


async def test_modele_introuvable() -> None:
    m = MoteurOllama(modele="inconnu", transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(ErreurMoteur, match="introuvable"):
        await m.generate(MESSAGES)
