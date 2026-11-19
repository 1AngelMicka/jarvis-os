"""Images jointes au dialogue : décodage vérifié, envoi à chaque famille de moteurs (factices), rien de gardé."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncGenerator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis2 import vision
from jarvis2.conversations import DepotConversations
from jarvis2.db import Base
from jarvis2.dialogue import ServiceDialogue
from jarvis2.moteurs.anthropic_api import MoteurAnthropic, preparer
from jarvis2.moteurs.base import (
    Delta,
    ErreurMoteur,
    EtatSante,
    Evenement,
    Fin,
    Image,
    InfoModele,
    Message,
    Moteur,
    Options,
    Reponse,
    Usage,
)
from jarvis2.moteurs.compatible_openai import MoteurCompatibleOpenAI
from jarvis2.moteurs.ollama import MoteurOllama
from jarvis2.moteurs.telemetrie import EnregistreurMemoire, MoteurInstrumente

from .test_claude_code import moteur as moteur_claude

# Plus petits fichiers valides de chaque type (signatures suffisantes pour le contrôle du Core)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 24
GIF = b"GIF89a" + b"\x00" * 24
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 16


def data_url(octets: bytes, type_mime: str = "image/png") -> str:
    return f"data:{type_mime};base64,{base64.b64encode(octets).decode()}"


# --- Décodage -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("octets", "annonce", "attendu"),
    [
        (PNG, "image/png", "image/png"),
        (JPEG, "image/jpeg", "image/jpeg"),
        (GIF, "image/gif", "image/gif"),
        (WEBP, "image/webp", "image/webp"),
        (PNG, "image/jpeg", "image/png"),  # l'en-tête ment : le type réel l'emporte
    ],
)
def test_decoder_jointe_types(octets: bytes, annonce: str, attendu: str) -> None:
    image = vision.decoder_jointe(data_url(octets, annonce))
    assert image.type_mime == attendu and image.donnees == octets


@pytest.mark.parametrize(
    "donnee",
    [
        "data:image/svg+xml;base64,PHN2Zz4=",  # SVG refusé (scripts possibles)
        data_url(b"<html>pas une image</html>"),  # contenu qui n'est pas une image
        "data:image/png;base64,@@@",  # base64 invalide
        "https://exemple.org/image.png",  # pas une data URL
        data_url(PNG + b"\x00" * vision.TAILLE_MAX_JOINTE),  # plus de 3 Mo
    ],
)
def test_decoder_jointe_refus(donnee: str) -> None:
    with pytest.raises(vision.ErreurVision):
        vision.decoder_jointe(donnee)


# --- Moteurs : format de chaque fournisseur ---------------------------------------------------------------------

AVEC_IMAGE = [
    Message("systeme", "Tu es JARVIS."),
    Message("utilisateur", "avant"),
    Message("assistant", "ok"),
    Message("utilisateur", "Que vois-tu ?", (Image("image/png", PNG), Image("image/gif", GIF))),
]


def test_anthropic_blocs_image_puis_texte() -> None:
    systeme, suite = preparer(AVEC_IMAGE)
    assert systeme == "Tu es JARVIS."
    assert suite[0]["content"] == "avant" and suite[1]["content"] == "ok"  # sans image : texte simple
    blocs = suite[2]["content"]
    assert [b["type"] for b in blocs] == ["image", "image", "text"]
    assert blocs[0]["source"] == {"type": "base64", "media_type": "image/png", "data": base64.b64encode(PNG).decode()}
    assert blocs[2]["text"] == "Que vois-tu ?"


async def test_anthropic_envoie_les_images() -> None:
    recu: dict[str, Any] = {}

    def gestion(requete: httpx.Request) -> httpx.Response:
        recu.update(json.loads(requete.content))
        lignes = [
            {"type": "message_start", "message": {"usage": {"input_tokens": 9}}},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Un chat."}},
            {"type": "message_delta", "usage": {"output_tokens": 3}},
        ]
        return httpx.Response(200, content="\n".join(f"data: {json.dumps(x)}" for x in lignes).encode())

    m = MoteurAnthropic(lambda: "cle", transport=httpx.MockTransport(gestion))
    assert m.vision
    fin = [e async for e in m.stream(AVEC_IMAGE)][-1]
    assert isinstance(fin, Fin) and fin.reponse.texte == "Un chat."
    assert recu["messages"][-1]["content"][0]["type"] == "image"
    await m.fermer()


async def test_compatible_openai_parties_image_url() -> None:
    recu: dict[str, Any] = {}

    def gestion(requete: httpx.Request) -> httpx.Response:
        recu.update(json.loads(requete.content))
        lignes = ['data: {"choices": [{"delta": {"content": "Un chat."}}]}', "data: [DONE]"]
        return httpx.Response(200, content="\n".join(lignes).encode())

    m = MoteurCompatibleOpenAI(
        "o", "OpenAI", "https://x/v1", "api", lambda: "k", modele="m", transport=httpx.MockTransport(gestion)
    )
    [e async for e in m.stream(AVEC_IMAGE)]
    assert recu["messages"][1]["content"] == "avant"
    parties = recu["messages"][-1]["content"]
    assert parties[0] == {"type": "text", "text": "Que vois-tu ?"}
    assert parties[1]["image_url"]["url"] == data_url(PNG)
    assert parties[2]["image_url"]["url"].startswith("data:image/gif;base64,")
    await m.fermer()


async def test_compatible_openai_modele_sans_vision_message_clair() -> None:
    m = MoteurCompatibleOpenAI(
        "o",
        "OpenAI",
        "https://x/v1",
        "api",
        lambda: "k",
        modele="texte-seul",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(400, json={"error": {"message": "image not supported"}})
        ),
    )
    with pytest.raises(ErreurMoteur, match="refuse les images"):
        [e async for e in m.stream(AVEC_IMAGE)]
    await m.fermer()


def transport_ollama(capacites: dict[str, list[str]], recu: dict[str, Any]) -> httpx.MockTransport:
    def gestion(requete: httpx.Request) -> httpx.Response:
        if requete.url.path == "/api/show":
            nom = json.loads(requete.content)["model"]
            return httpx.Response(200, json={"capabilities": capacites.get(nom, ["completion"])})
        if requete.url.path == "/api/chat":
            recu.update(json.loads(requete.content))
            lignes = [{"message": {"content": "Un chat."}, "done": False}, {"message": {"content": ""}, "done": True}]
            return httpx.Response(200, content="\n".join(json.dumps(x) for x in lignes).encode())
        return httpx.Response(404)

    return httpx.MockTransport(gestion)


async def test_ollama_modele_de_vision() -> None:
    recu: dict[str, Any] = {}
    m = MoteurOllama(modele="qwen3.5:2b", transport=transport_ollama({"qwen3.5:2b": ["completion", "vision"]}, recu))
    [e async for e in m.stream(AVEC_IMAGE)]
    assert recu["model"] == "qwen3.5:2b"
    assert recu["messages"][-1]["images"] == [base64.b64encode(PNG).decode(), base64.b64encode(GIF).decode()]
    assert "images" not in recu["messages"][1]
    await m.fermer()


async def test_ollama_bascule_sur_modele_vision_ou_refuse() -> None:
    recu: dict[str, Any] = {}
    capacites = {"vision:2b": ["completion", "vision"]}
    m = MoteurOllama(modele="texte:7b", modele_vision="vision:2b", transport=transport_ollama(capacites, recu))
    [e async for e in m.stream(AVEC_IMAGE)]
    assert recu["model"] == "vision:2b"  # le modèle choisi ne voit pas : modèle de vision de la configuration
    await m.fermer()
    seul = MoteurOllama(modele="texte:7b", transport=transport_ollama({}, {}))
    with pytest.raises(ErreurMoteur, match="ne lit pas les images"):
        [e async for e in seul.stream(AVEC_IMAGE)]
    await seul.fermer()


async def test_claude_code_images_par_chemin_puis_effacees(tmp_path: Path) -> None:
    m = moteur_claude("images", tmp_path)
    m.dossier_images = tmp_path / "images"
    fin = [e async for e in m.stream(AVEC_IMAGE)][-1]
    assert isinstance(fin, Fin)
    vu = json.loads(fin.reponse.texte)
    assert vu["outils"] == "Read"  # seul outil permis, et seulement avec des images
    assert vu["fichiers"] == "image-1.png,image-2.gif"
    assert Path(vu["cwd"]).parent == tmp_path / "images"
    assert str(Path(vu["cwd"]) / "image-1.png") in vu["prompt"] and "Read" in vu["prompt"]
    assert list((tmp_path / "images").iterdir()) == []  # effacées après la réponse
    # Sans image : aucun outil, dossier de travail habituel
    sans = json.loads([e async for e in m.stream(AVEC_IMAGE[:2])][-1].reponse.texte)  # type: ignore[union-attr]
    assert sans["outils"] == "" and Path(sans["cwd"]) == tmp_path


async def test_claude_code_efface_aussi_en_cas_d_erreur(tmp_path: Path) -> None:
    m = moteur_claude("erreur", tmp_path)
    m.dossier_images = tmp_path / "images"
    with pytest.raises(ErreurMoteur):
        [e async for e in m.stream(AVEC_IMAGE)]
    assert list((tmp_path / "images").iterdir()) == []


# --- Dialogue : routage, refus clair, rien de gardé -------------------------------------------------------------


class MoteurVoyant(Moteur):
    """Moteur factice qui note les images reçues."""

    def __init__(self, ident: str, vision: bool, externe: bool = False) -> None:
        self.id, self.nom, self.vision, self.externe = ident, ident.capitalize(), vision, externe
        self.recus: list[Sequence[Message]] = []

    async def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        self.recus.append(list(messages))
        yield Delta("vu")
        yield Fin(Reponse("vu", "m", Usage(), 0.0, {"source_auth": "none"}))

    async def list_models(self) -> list[InfoModele]:
        return []

    async def health(self) -> EtatSante:
        return EtatSante(True)


@pytest.mark.base
async def test_dialogue_transmet_les_images_sans_les_garder(pool: Base) -> None:
    voyant = MoteurVoyant("voyant", vision=True, externe=True)
    aveugle = MoteurVoyant("aveugle", vision=False)
    moteurs = {m.id: MoteurInstrumente(m, EnregistreurMemoire()) for m in (voyant, aveugle)}
    depot = DepotConversations(pool)
    service = ServiceDialogue(depot, moteurs, "voyant")
    service.titre_auto = False
    image = Image("image/png", PNG)
    evenements = [e async for e in service.repondre("  ", moteur="voyant", images=[image])]
    assert evenements[0].donnees["images"] == 1 and evenements[-1].type == "fin"
    dernier = voyant.recus[0][-1]
    assert dernier.images == (image,) and dernier.contenu == "Que montre cette image ?"
    # Base : seulement le type et le poids, jamais les octets
    meta = await pool.fetchval("SELECT meta FROM messages WHERE role = 'utilisateur'")
    assert meta == {"images": [{"type": "image/png", "octets": len(PNG)}]}
    # Message suivant : le modèle sait qu'il y avait une image, sans la recevoir de nouveau
    conv = evenements[0].donnees["conversation_id"]
    from uuid import UUID

    [e async for e in service.repondre("Et la couleur ?", UUID(conv), "voyant")]
    suite = voyant.recus[1]
    assert "1 image jointe à ce message, non conservée" in suite[1].contenu
    assert all(not m.images for m in suite)
    # Connecteur sans vision : refus clair, rien n'est envoyé
    with pytest.raises(ErreurMoteur, match="ne lit pas les images"):
        [e async for e in service.repondre("et ça ?", moteur="aveugle", images=[image])]
    assert aveugle.recus == []
    with pytest.raises(ValueError, match="5 images au plus"):
        [e async for e in service.repondre("trop", moteur="voyant", images=[image] * 6)]
