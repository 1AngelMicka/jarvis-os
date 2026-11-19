"""Fin de tour de parole (lot K3) : l'utilisateur a-t-il fini sa phrase, ou reprend-il son souffle ?

Deux étages, pour couper plus tôt sans couper la parole :
1. une règle instantanée sur le texte déjà transcrit (transcription anticipée) : une phrase qui finit par « et »,
   « mais », « euh », un article ou une virgule n'est pas finie ; une question ou une phrase ponctuée l'est ;
2. seulement quand la règle hésite, un **petit modèle local** (Ollama, `JARVIS2_MODELE_FIN_TOUR`, par exemple
   `qwen3:0.6b`) répond « oui » ou « non » en quelques centaines de millisecondes. Jamais Ollama démarré pour cela :
   arrêté ou trop lent, la règle seule décide. Le texte ne quitte pas le PC.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .voix import sans_accents

journal = logging.getLogger("jarvis2.fin_tour")

SEUIL_FINI = 0.7
DELAI_JUGE = 0.6  # secondes ; au-delà, la règle seule décide
KEEP_ALIVE = "30m"

_MOTS = """
et mais ou donc or ni car que qu qui quoi dont de d du des le la l les un une au aux a en par pour avec sans
dans sur sous vers chez entre mon ma mes ton ta tes son sa ses notre nos votre vos leur leurs ce cet cette
ces si quand comme parce puis alors euh heu hum hmm bah ben genre enfin bref je j tu il elle on nous vous ils
elles me te se m t s y tres plus moins aussi pas ne n est c ca cela lui leur quel quelle quels quelles
combien pourquoi comment
"""
MOTS_SUSPENDUS = frozenset(_MOTS.split())


@dataclass(frozen=True)
class FinDeTour:
    probabilite: float
    raison: str
    juge: str | None = None  # modèle consulté
    duree_ms: float = 0.0

    @property
    def fini(self) -> bool:
        return self.probabilite >= SEUIL_FINI

    def en_dict(self) -> dict[str, Any]:
        return {
            "fini": self.fini,
            "probabilite": round(self.probabilite, 2),
            "raison": self.raison,
            "juge": self.juge,
            "duree_ms": round(self.duree_ms, 1),
        }


def regle(texte: str) -> FinDeTour:
    t = texte.strip()
    if not t:
        return FinDeTour(0.0, "rien d'entendu")
    if t.endswith(("...", "…", ",", ";", ":", "-", "—")):
        return FinDeTour(0.15, "phrase suspendue")
    mots = sans_accents(t).lower().replace("'", " ").replace("’", " ").split()
    dernier = mots[-1].strip('.!?»"') if mots else ""
    if t.endswith(("?", "!")):
        return FinDeTour(0.95, "question ou exclamation")
    if dernier in MOTS_SUSPENDUS:
        return FinDeTour(0.1, f"finit par « {dernier} »")
    if t.endswith("."):
        return FinDeTour(0.8, "phrase ponctuée")
    if len(mots) <= 2:
        return FinDeTour(0.5, "phrase très courte")
    return FinDeTour(0.6, "sans ponctuation")


INVITE = (
    "Une personne parle à voix haute à son assistant. Le texte ci-dessous est-il une phrase TERMINÉE (elle a fini de "
    "parler) ? Réponds seulement « oui » ou « non ».\nTexte : « {texte} »"
)


class JugeFinDeTour:
    def __init__(self, url_ollama: str, modele: str, delai: float = DELAI_JUGE) -> None:
        self.url = url_ollama.rstrip("/")
        self.modele = modele.strip()
        self.delai = delai
        self.transport: httpx.AsyncBaseTransport | None = None  # essais

    async def juger(self, texte: str) -> bool | None:
        """Vrai / faux, ou None si le modèle n'a pas répondu à temps (Ollama arrêté : jamais démarré ici)."""
        if not self.modele:
            return None
        corps = {
            "model": self.modele,
            "prompt": INVITE.format(texte=texte[-400:]),
            "stream": False,
            "think": False,
            "keep_alive": KEEP_ALIVE,
            "options": {"temperature": 0, "num_predict": 3},
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.delai, connect=0.2), transport=self.transport
            ) as client:
                rep = await client.post(f"{self.url}/api/generate", json=corps)
            if rep.status_code != 200:
                return None
            reponse = sans_accents(str(rep.json().get("response", ""))).strip().lower()
        except (httpx.HTTPError, ValueError):
            return None
        if reponse.startswith("oui") or reponse.startswith("yes"):
            return True
        if reponse.startswith("non") or reponse.startswith("no"):
            return False
        return None


async def evaluer(texte: str, juge: JugeFinDeTour | None = None) -> FinDeTour:
    debut = time.perf_counter()
    r = regle(texte)
    if juge is None or not juge.modele or not 0.3 <= r.probabilite < SEUIL_FINI:
        return FinDeTour(r.probabilite, r.raison, None, (time.perf_counter() - debut) * 1000)
    avis = await juge.juger(texte)
    duree = (time.perf_counter() - debut) * 1000
    if avis is None:
        return FinDeTour(r.probabilite, f"{r.raison} (petit modèle sans réponse)", None, duree)
    return FinDeTour(0.9 if avis else 0.2, "petit modèle : " + ("phrase finie" if avis else "phrase pas finie"),
                     juge.modele, duree)  # fmt: skip
