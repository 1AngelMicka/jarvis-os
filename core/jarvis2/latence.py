"""Latence de la voix mesurée étape par étape (`jarvis2 docteur`, lot K3).

Sans option, le diagnostic ne fait que des mesures légères, sans rien charger : adresse d'Ollama (127.0.0.1 plutôt
que « localhost », qui essaie souvent IPv6 d'abord sous Windows), temps de réponse d'Ollama, modèles gardés en
mémoire et durée restante (`keep_alive`), modèle Whisper présent, règle de fin de tour.

Avec `jarvis2 docteur --latence` (demande explicite) : préchauffage et mesure de chaque étape — chargement et
premier calcul de Whisper, transcription d'une seconde d'audio, juge de fin de tour, préchauffage du modèle Ollama
(gardé en mémoire `keep_alive`) et délai du premier mot. Ollama n'est **jamais démarré** : arrêté, il est signalé.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx

from .diagnostic import Verification
from .fin_tour import KEEP_ALIVE, JugeFinDeTour, evaluer

if TYPE_CHECKING:
    from .config import Parametres
    from .transcription import TranscripteurRobuste


def _ms(debut: float) -> float:
    return (time.perf_counter() - debut) * 1000


def verifier_adresse(url: str) -> Verification:
    hote = (urlparse(url).hostname or "").lower()
    if hote == "localhost":
        return Verification(
            "latence.adresse",
            "Latence · adresse d'Ollama",
            "attention",
            f"{url} : « localhost » peut coûter jusqu'à 2 s par appel sous Windows (IPv6 essayé d'abord)",
            aide="JARVIS2_OLLAMA_URL=http://127.0.0.1:11434",
        )
    return Verification("latence.adresse", "Latence · adresse d'Ollama", "ok", url)


def _reste(expire: str | None) -> str:
    if not expire:
        return "durée inconnue"
    try:
        fin = datetime.fromisoformat(expire.replace("Z", "+00:00"))
    except ValueError:
        return "durée inconnue"
    secondes = (fin - datetime.now(UTC)).total_seconds()
    if secondes > 10 * 365 * 86400:
        return "gardé en mémoire sans limite"
    return f"gardé encore {max(0, round(secondes / 60))} min"


async def mesurer_ollama(
    url: str, modele: str | None, complet: bool, transport: httpx.AsyncBaseTransport | None = None
) -> list[Verification]:
    url = url.rstrip("/")
    sortie: list[Verification] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.0), transport=transport) as client:
        debut = time.perf_counter()
        try:
            rep = await client.get(f"{url}/api/version")
            rep.raise_for_status()
        except httpx.HTTPError:
            return [
                Verification(
                    "latence.ollama",
                    "Latence · Ollama",
                    "info",
                    "arrêté ou injoignable : rien mesuré (le diagnostic ne le démarre jamais)",
                )
            ]
        aller_retour = _ms(debut)
        sortie.append(
            Verification(
                "latence.ollama",
                "Latence · Ollama",
                "ok" if aller_retour < 200 else "attention",
                f"répond en {aller_retour:.0f} ms",
            )
        )
        try:
            charges = (await client.get(f"{url}/api/ps")).json().get("models") or []
        except (httpx.HTTPError, ValueError):
            charges = []
        if charges:
            detail = " ; ".join(f"{m.get('name')} ({_reste(m.get('expires_at'))})" for m in charges[:4])
            sortie.append(Verification("latence.memoire", "Latence · modèles en mémoire", "ok", detail))
        else:
            sortie.append(
                Verification(
                    "latence.memoire",
                    "Latence · modèles en mémoire",
                    "info",
                    "aucun : le premier échange paiera le chargement du modèle",
                    aide="jarvis2 docteur --latence (préchauffage, keep_alive " + KEEP_ALIVE + ")",
                )
            )
        if not complet:
            return sortie
        if not modele:
            noms = [m.get("name") for m in charges] or []
            if not noms:
                try:
                    noms = [m.get("name") for m in (await client.get(f"{url}/api/tags")).json().get("models") or []]
                except (httpx.HTTPError, ValueError):
                    noms = []
            modele = str(noms[0]) if noms else None
        if not modele:
            sortie.append(
                Verification("latence.prechauffage", "Latence · préchauffage", "info", "aucun modèle installé")
            )
            return sortie
        debut = time.perf_counter()
        try:
            r = await client.post(
                f"{url}/api/generate", json={"model": modele, "keep_alive": KEEP_ALIVE}, timeout=180.0
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            sortie.append(
                Verification(
                    "latence.prechauffage", "Latence · préchauffage", "attention", f"{modele} : {type(exc).__name__}"
                )
            )
            return sortie
        sortie.append(
            Verification(
                "latence.prechauffage",
                "Latence · préchauffage",
                "ok",
                f"{modele} chargé en {_ms(debut):.0f} ms, gardé {KEEP_ALIVE}",
            )
        )
        corps = {
            "model": modele,
            "prompt": "Réponds seulement : d'accord.",
            "stream": True,
            "think": False,
            "keep_alive": KEEP_ALIVE,
            "options": {"num_predict": 8},
        }
        debut = time.perf_counter()
        premier: float | None = None
        try:
            async with client.stream("POST", f"{url}/api/generate", json=corps, timeout=60.0) as flux:
                async for ligne in flux.aiter_lines():
                    if premier is None and ligne.strip():
                        try:
                            morceau = json.loads(ligne).get("response")
                        except ValueError:
                            continue
                        if morceau:
                            premier = _ms(debut)
            total = _ms(debut)
        except httpx.HTTPError as exc:
            sortie.append(Verification("latence.premier_mot", "Latence · premier mot", "attention", type(exc).__name__))
            return sortie
        sortie.append(
            Verification(
                "latence.premier_mot",
                "Latence · premier mot",
                "ok" if (premier or total) < 1000 else "attention",
                f"{modele} : premier mot en {premier or total:.0f} ms, réponse courte en {total:.0f} ms",
            )
        )
    return sortie


async def mesurer_whisper(t: TranscripteurRobuste, complet: bool) -> list[Verification]:
    etat = t.etat()
    appareil = etat["appareil"]
    sur = appareil["libelle"] + (f" — {appareil['raison']}" if appareil.get("raison") else "")
    if not etat["telecharge"]:
        return [
            Verification(
                "latence.whisper",
                "Latence · transcription",
                "info",
                f"modèle Whisper « {t.modele} » non téléchargé ; calcul prévu sur : {sur}",
            )
        ]
    conseil = "" if etat["conseille"] else " (small ou medium conseillés : JARVIS2_MODELE_VOIX)"
    if not complet:
        return [
            Verification(
                "latence.whisper",
                "Latence · transcription",
                "ok",
                f"Whisper « {t.modele} » int8 sur {sur}{conseil} ; mesure : jarvis2 docteur --latence",
            )
        ]
    import numpy as np

    try:
        prechauffage = await t.prechauffer()
        debut = time.perf_counter()
        bruit = (np.random.default_rng(1).standard_normal(16000) * 0.01).astype(np.float32)
        await asyncio.to_thread(t.vad, bruit)
        vad = _ms(debut)
        debut = time.perf_counter()
        await asyncio.to_thread(t._whisper, bruit)
        calcul = _ms(debut)
    except Exception as exc:
        return [
            Verification("latence.whisper", "Latence · transcription", "erreur", f"{type(exc).__name__} : {exc}"[:300])
        ]
    appareil = t.etat()["appareil"]
    return [
        Verification(
            "latence.whisper",
            "Latence · transcription",
            "ok" if calcul < 1500 else "attention",
            f"Whisper « {t.modele} » sur {appareil['libelle']}{conseil} : chargement + préchauffage "
            f"{prechauffage:.0f} ms, VAD {vad:.0f} ms, 1 s d'audio en {calcul:.0f} ms",
        )
    ]


async def mesurer_fin_tour(juge: JugeFinDeTour | None, complet: bool) -> Verification:
    r = await evaluer("Est-ce que tu peux allumer la lumière du salon ?", None)
    detail = f"règle en {r.duree_ms:.2f} ms"
    if juge is not None and juge.modele and not complet:
        detail += f" ; petit modèle {juge.modele} (mesure : jarvis2 docteur --latence)"
    elif juge is not None and juge.modele:
        debut = time.perf_counter()
        avis = await juge.juger("je voudrais que tu")
        detail += (
            f" ; petit modèle {juge.modele} : {_ms(debut):.0f} ms"
            if avis is not None
            else f" ; petit modèle {juge.modele} sans réponse (Ollama arrêté ou trop lent)"
        )
    else:
        detail += " ; petit modèle : non configuré (JARVIS2_MODELE_FIN_TOUR, ex. qwen3:0.6b)"
    return Verification("latence.fin_tour", "Latence · fin de tour", "ok", detail)


async def mesurer(p: Parametres, complet: bool = False) -> list[Verification]:
    from .transcription import TranscripteurRobuste

    sortie = [verifier_adresse(p.ollama_url)]
    t = TranscripteurRobuste(p.dossier_modeles, p.modele_voix, p.voix_appareil)
    sortie.extend(await mesurer_whisper(t, complet))
    juge = JugeFinDeTour(p.ollama_url, p.modele_fin_tour) if p.modele_fin_tour else None
    sortie.append(await mesurer_fin_tour(juge, complet))
    sortie.extend(await mesurer_ollama(p.ollama_url, None, complet))
    return sortie
