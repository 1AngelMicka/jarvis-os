"""Faux pont Philips Hue (transport httpx simulé) et faux OBS (serveur WebSocket v5 sur 127.0.0.1).

Aucun appel réseau réel : le pont n'existe qu'en mémoire ; OBS écoute sur la boucle locale, port éphémère.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import struct
from typing import Any

import httpx

from jarvis2.maison.obs import reponse_authentification
from jarvis2.maison.websocket import cle_acceptee, lire_trame, trame

CLE_PONT = "cle-du-faux-pont-0123456789"


class FauxPont:
    def __init__(self) -> None:
        self.bouton = False
        self.lumieres: dict[str, dict[str, Any]] = {
            "1": {"name": "Salon", "state": {"on": False, "bri": 127, "reachable": True}},
            "2": {"name": "Bureau", "state": {"on": True, "bri": 254, "reachable": True}},
        }
        self.groupes: dict[str, dict[str, Any]] = {"1": {"name": "Séjour", "type": "Room", "action": {}}}
        self.scenes = {"abc123": {"name": "Lecture", "group": "1"}}
        self.appels: list[tuple[str, str, Any]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.repondre)

    def repondre(self, requete: httpx.Request) -> httpx.Response:
        assert requete.url.scheme == "https" and requete.url.host.startswith("192.168.")
        chemin = requete.url.path.removeprefix("/api").strip("/")
        corps = json.loads(requete.content) if requete.content else None
        self.appels.append((requete.method, chemin, corps))
        if chemin == "" and requete.method == "POST":
            if not self.bouton:
                return httpx.Response(200, json=[{"error": {"type": 101, "description": "link button not pressed"}}])
            return httpx.Response(200, json=[{"success": {"username": CLE_PONT}}])
        cle, _, suite = chemin.partition("/")
        if cle != CLE_PONT:
            return httpx.Response(200, json=[{"error": {"type": 1, "description": "unauthorized user"}}])
        if requete.method == "GET":
            return httpx.Response(
                200, json={"lights": self.lumieres, "groups": self.groupes, "scenes": self.scenes}[suite]
            )
        morceaux = suite.split("/")
        if morceaux[0] == "lights":
            self.lumieres[morceaux[1]]["state"].update(corps)
        elif morceaux[0] == "groups":
            self.groupes.setdefault(morceaux[1], {"action": {}})["action"].update(corps)
        return httpx.Response(200, json=[{"success": {k: v}} for k, v in (corps or {}).items()])


class FauxOBS:
    """Serveur WebSocket v5 minimal : Hello (avec ou sans mot de passe), Identify, requêtes utiles à JARVIS."""

    def __init__(self, mot_de_passe: str | None = None) -> None:
        self.mot_de_passe = mot_de_passe
        self.scene = "Caméra"
        self.scenes = ["Caméra", "Écran", "Pause"]  # ordre affiché par OBS
        self.enregistrement = False
        self.direct = False
        self.requetes: list[str] = []
        self.serveur: asyncio.Server | None = None
        self.port = 0

    async def demarrer(self) -> None:
        self.serveur = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self.serveur.sockets[0].getsockname()[1]

    async def arreter(self) -> None:
        if self.serveur is not None:
            self.serveur.close()
            await self.serveur.wait_closed()

    async def _client(self, lecteur: asyncio.StreamReader, ecrivain: asyncio.StreamWriter) -> None:
        try:
            entete = (await lecteur.readuntil(b"\r\n\r\n")).decode()
            cle = next(
                x.split(":", 1)[1].strip() for x in entete.split("\r\n") if x.lower().startswith("sec-websocket-key")
            )
            ecrivain.write(
                (
                    "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {cle_acceptee(cle)}\r\nSec-WebSocket-Protocol: obswebsocket.json\r\n\r\n"
                ).encode()
            )

            def envoyer(message: dict[str, Any]) -> None:
                ecrivain.write(trame(0x1, json.dumps(message).encode(), None))

            sel, defi = base64.b64encode(os.urandom(8)).decode(), base64.b64encode(os.urandom(8)).decode()
            bonjour: dict[str, Any] = {"obsWebSocketVersion": "5.5.0", "rpcVersion": 1}
            if self.mot_de_passe:
                bonjour["authentication"] = {"challenge": defi, "salt": sel}
            envoyer({"op": 0, "d": bonjour})
            ecrivain.write(trame(0x9, b"ping", None))  # le client doit répondre « pong » et continuer
            while True:
                opcode, charge = await lire_trame(lecteur)
                if opcode == 0x8:
                    break
                if opcode != 0x1:
                    continue
                message = json.loads(charge)
                if message["op"] == 1:
                    attendu = reponse_authentification(self.mot_de_passe, sel, defi) if self.mot_de_passe else None
                    if attendu and message["d"].get("authentication") != attendu:
                        ecrivain.write(trame(0x8, struct.pack("!H", 4009), None))
                        break
                    envoyer({"op": 2, "d": {"negotiatedRpcVersion": 1}})
                elif message["op"] == 6:
                    envoyer({"op": 5, "d": {"eventType": "Bruit", "eventData": {}}})  # un événement à ignorer
                    envoyer({"op": 7, "d": self._requete(message["d"])})
                await ecrivain.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            ecrivain.close()

    def _requete(self, d: dict[str, Any]) -> dict[str, Any]:
        type_requete, donnees = d["requestType"], d.get("requestData") or {}
        self.requetes.append(type_requete)
        reponse: dict[str, Any] = {}
        ok = True
        if type_requete == "GetSceneList":
            reponse = {
                "currentProgramSceneName": self.scene,
                "scenes": [{"sceneName": s, "sceneIndex": i} for i, s in enumerate(reversed(self.scenes))],
            }
        elif type_requete == "SetCurrentProgramScene":
            self.scene = donnees["sceneName"]
        elif type_requete == "GetRecordStatus":
            reponse = {"outputActive": self.enregistrement}
        elif type_requete == "GetStreamStatus":
            reponse = {"outputActive": self.direct}
        elif type_requete in ("StartRecord", "StopRecord"):
            self.enregistrement = type_requete == "StartRecord"
        elif type_requete in ("StartStream", "StopStream"):
            ok = not (type_requete == "StartStream" and self.direct)
            self.direct = type_requete == "StartStream"
        else:
            ok = False
        statut = {"result": ok, "code": 100 if ok else 501, **({} if ok else {"comment": "refusé"})}
        return {
            "requestType": type_requete,
            "requestId": d["requestId"],
            "requestStatus": statut,
            "responseData": reponse,
        }
