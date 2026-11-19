"""Vision SUR DEMANDE : une image envoyée par l'utilisateur (capture qu'il a lui-même déclenchée) est décrite par un
modèle de vision LOCAL (Ollama). Rien n'est capturé en arrière-plan, l'image n'est pas gardée, rien ne sort du PC.

Modèle : `[connecteurs.ollama] modele_vision` de la configuration locale (ex. « qwen2.5vl:7b », « llava:7b »).
"""

from __future__ import annotations

import base64
import binascii
import re

import httpx

from .moteurs.base import Image

TAILLE_MAX = 8 * 1024 * 1024
ENTETE = re.compile(r"^data:image/(png|jpeg|webp);base64,")
QUESTION_DEFAUT = "Décris précisément ce que montre cette image, en français."


# Images jointes au dialogue : compressées par le navigateur (1 Mo visé), GIF gardé tel quel jusqu'à 3 Mo
TYPES_JOINTS = ("image/jpeg", "image/png", "image/webp", "image/gif")
TAILLE_MAX_JOINTE = 3 * 1024 * 1024
ENTETE_JOINTE = re.compile(r"^data:(image/(?:jpeg|png|webp|gif));base64,")


class ErreurVision(RuntimeError):
    pass


def type_reel(octets: bytes) -> str | None:
    """Type d'après les premiers octets (on ne croit pas l'en-tête de la data URL sur parole)."""
    if octets.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if octets.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if octets[:4] == b"RIFF" and octets[8:12] == b"WEBP":
        return "image/webp"
    if octets[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


def decoder_jointe(donnee: str) -> Image:
    """Image jointe à un message (data URL JPEG, PNG, WebP ou GIF, 3 Mo au plus) → `Image` gardée en mémoire."""
    entete = ENTETE_JOINTE.match(donnee)
    if entete is None:
        raise ErreurVision("Image jointe illisible : JPEG, PNG, WebP ou GIF attendu")
    try:
        octets = base64.b64decode(donnee[entete.end() :], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ErreurVision("Image jointe illisible") from exc
    if len(octets) > TAILLE_MAX_JOINTE:
        raise ErreurVision("Image jointe trop lourde (3 Mo au plus)")
    reel = type_reel(octets)
    if reel is None:
        raise ErreurVision("Le fichier joint n'est pas une image JPEG, PNG, WebP ou GIF")
    return Image(reel, octets)


def decoder(donnee: str) -> bytes:
    """Image en data URL (PNG, JPEG ou WebP) → octets ; refuse le reste et les images trop lourdes."""
    entete = ENTETE.match(donnee)
    if entete is None:
        raise ErreurVision("Image attendue en data URL PNG, JPEG ou WebP")
    try:
        octets = base64.b64decode(donnee[entete.end() :], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ErreurVision("Image illisible") from exc
    if len(octets) > TAILLE_MAX:
        raise ErreurVision("Image trop lourde (8 Mo au plus)")
    return octets


async def decrire(
    url_ollama: str,
    modele: str | None,
    image: bytes,
    question: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    if not modele:
        raise ErreurVision(
            "Aucun modèle de vision local : ajoutez [connecteurs.ollama] modele_vision (ex. « qwen2.5vl:7b ») à la "
            "configuration locale, puis `ollama pull` ce modèle"
        )
    corps = {
        "model": modele,
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": (question or QUESTION_DEFAUT)[:2000],
                "images": [base64.b64encode(image).decode()],
            }
        ],
    }
    try:
        async with httpx.AsyncClient(transport=transport, timeout=180) as client:
            reponse = await client.post(f"{url_ollama.rstrip('/')}/api/chat", json=corps)
    except httpx.HTTPError as exc:
        raise ErreurVision(f"Ollama injoignable : {exc}") from exc
    if reponse.status_code != 200:
        raise ErreurVision(f"Ollama a refusé ({reponse.status_code}) : {reponse.text[:200]}")
    texte = str((reponse.json().get("message") or {}).get("content") or "").strip()
    if not texte:
        raise ErreurVision("Le modèle de vision n'a rien répondu")
    return texte
