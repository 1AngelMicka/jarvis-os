"""OBS Studio par son serveur WebSocket (protocole v5, intégré à OBS 28 et suivants).

Une connexion courte par commande : Hello → Identify (mot de passe éventuel, jamais envoyé en clair : empreinte
SHA-256 avec le sel et le défi d'OBS) → requêtes → fermeture. Aucun abonnement aux événements.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any

from .websocket import ClientWebSocket, ErreurWebSocket

PORT_DEFAUT = 4455
DELAI = 6.0


class ErreurOBS(RuntimeError):
    """Message en français, affichable tel quel."""


def reponse_authentification(mot_de_passe: str, sel: str, defi: str) -> str:
    secret = base64.b64encode(hashlib.sha256((mot_de_passe + sel).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + defi).encode()).digest()).decode()


@dataclass
class ClientOBS:
    hote: str
    port: int = PORT_DEFAUT
    mot_de_passe: str | None = None

    async def executer(self, requetes: list[tuple[str, dict[str, Any] | None]]) -> list[dict[str, Any]]:
        """Envoie les requêtes dans l'ordre ; renvoie leurs `responseData`. Refus d'OBS : ErreurOBS."""
        try:
            return await asyncio.wait_for(self._executer(requetes), timeout=DELAI)
        except TimeoutError as exc:
            raise ErreurOBS(
                "OBS ne répond pas (WebSocket activé dans Outils → Paramètres du serveur WebSocket ?)"
            ) from exc
        except ErreurWebSocket as exc:
            if "4009" in str(exc):
                raise ErreurOBS("Mot de passe OBS refusé") from exc
            raise ErreurOBS(f"OBS injoignable : {exc}") from exc

    async def _executer(self, requetes: list[tuple[str, dict[str, Any] | None]]) -> list[dict[str, Any]]:
        ws = await ClientWebSocket.ouvrir(self.hote, self.port, protocole="obswebsocket.json")
        try:
            bonjour = json.loads(await ws.recevoir())
            if bonjour.get("op") != 0:
                raise ErreurOBS("Réponse inattendue : ce service n'est pas OBS")
            d = bonjour.get("d") or {}
            identite: dict[str, Any] = {"rpcVersion": 1, "eventSubscriptions": 0}
            auth = d.get("authentication")
            if auth:
                if not self.mot_de_passe:
                    raise ErreurOBS("OBS demande un mot de passe : enregistrez-le dans le connecteur")
                identite["authentication"] = reponse_authentification(
                    self.mot_de_passe, str(auth.get("salt", "")), str(auth.get("challenge", ""))
                )
            await ws.envoyer(json.dumps({"op": 1, "d": identite}))
            while (message := json.loads(await ws.recevoir())).get("op") != 2:
                pass  # Identified attendu
            sorties = []
            for type_requete, donnees in requetes:
                ident = secrets.token_hex(8)
                corps: dict[str, Any] = {"requestType": type_requete, "requestId": ident}
                if donnees:
                    corps["requestData"] = donnees
                await ws.envoyer(json.dumps({"op": 6, "d": corps}))
                while True:
                    message = json.loads(await ws.recevoir())
                    rd = message.get("d") or {}
                    if message.get("op") == 7 and rd.get("requestId") == ident:
                        break
                statut = rd.get("requestStatus") or {}
                if not statut.get("result"):
                    raise ErreurOBS(f"OBS a refusé « {type_requete} » : {statut.get('comment') or statut.get('code')}")
                sorties.append(rd.get("responseData") or {})
            return sorties
        finally:
            await ws.fermer()

    async def etat(self) -> dict[str, Any]:
        scenes, enreg, direct = await self.executer(
            [("GetSceneList", None), ("GetRecordStatus", None), ("GetStreamStatus", None)]
        )
        return {
            "scene": scenes.get("currentProgramSceneName"),
            # OBS liste les scènes du bas vers le haut : remises dans l'ordre affiché par OBS
            "scenes": [str(s.get("sceneName")) for s in reversed(scenes.get("scenes") or [])],
            "enregistrement": bool(enreg.get("outputActive")),
            "direct": bool(direct.get("outputActive")),
        }

    async def scenes(self) -> list[str]:
        return list((await self.etat())["scenes"])

    async def changer_scene(self, scene: str) -> None:
        if scene not in await self.scenes():
            raise ErreurOBS(f"Scène OBS inconnue : « {scene} »")
        await self.executer([("SetCurrentProgramScene", {"sceneName": scene})])

    async def enregistrement(self, demarrer: bool) -> None:
        await self.executer([("StartRecord" if demarrer else "StopRecord", None)])

    async def direct(self, demarrer: bool) -> None:
        await self.executer([("StartStream" if demarrer else "StopStream", None)])
