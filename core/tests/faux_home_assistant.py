"""Faux Home Assistant (transport httpx simulé) : API REST, serveur MCP HTTP, jetons OAuth avec PKCE.

Aucun appel réseau réel : tout vit en mémoire. Le faux vérifie ce qu'un vrai Home Assistant vérifierait (jeton
porteur, vérifieur PKCE, identifiant de session MCP) et note chaque appel pour les assertions.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any
from urllib.parse import parse_qs

import httpx

JETON_LONGUE_DUREE = "jeton-longue-duree-du-faux-home-assistant"
ADRESSE = "http://192.168.1.30:8123"


class FauxHomeAssistant:
    def __init__(self) -> None:
        self.etats: dict[str, dict[str, Any]] = {
            "light.salon": {"state": "off", "attributes": {"friendly_name": "Salon"}},
            "switch.cafetiere": {"state": "off", "attributes": {"friendly_name": "Cafetière"}},
            "media_player.salon": {"state": "paused", "attributes": {"friendly_name": "Enceinte salon"}},
            "lock.entree": {"state": "locked", "attributes": {"friendly_name": "Porte d'entrée"}},
            "alarm_control_panel.maison": {"state": "disarmed", "attributes": {"friendly_name": "Alarme"}},
            "cover.portail": {"state": "closed", "attributes": {"friendly_name": "Portail", "device_class": "gate"}},
            "cover.volet": {"state": "open", "attributes": {"friendly_name": "Volet", "device_class": "shutter"}},
            "sensor.temperature": {"state": "21.5", "attributes": {"friendly_name": "Température"}},
        }
        self.services: list[tuple[str, dict[str, Any]]] = []  # (« domaine.service », corps)
        self.outils: list[tuple[str, dict[str, Any]]] = []  # appels d'outils MCP
        self.mcp_present = True
        self.defis: dict[str, str] = {}  # code d'autorisation → défi PKCE attendu
        self.acces_valides: set[str] = set()
        self.rafraichissements: set[str] = set()
        self.echanges = 0
        self.sessions: set[str] = set()
        self.formulaires: list[dict[str, str]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.repondre)

    def autoriser(self, code: str, defi: str) -> None:
        """L'utilisateur a accepté dans Home Assistant : ce code ne vaut que pour ce défi PKCE."""
        self.defis[code] = defi

    # --- routage ------------------------------------------------------------------------------------------------

    def repondre(self, requete: httpx.Request) -> httpx.Response:
        assert requete.url.host == "192.168.1.30" and requete.url.port == 8123
        chemin = requete.url.path
        if chemin == "/auth/token":
            return self._jeton(requete)
        porteur = requete.headers.get("authorization", "").removeprefix("Bearer ")
        if porteur != JETON_LONGUE_DUREE and porteur not in self.acces_valides:
            return httpx.Response(401, json={"message": "Unauthorized"})
        if chemin == "/api/mcp":
            return self._mcp(requete) if self.mcp_present else httpx.Response(404)
        if chemin == "/api/states" and requete.method == "GET":
            return httpx.Response(200, json=[{"entity_id": k, **v} for k, v in self.etats.items()])
        if chemin.startswith("/api/states/"):
            entite = chemin.removeprefix("/api/states/")
            if entite not in self.etats:
                return httpx.Response(404, json={"message": "Entity not found."})
            return httpx.Response(200, json={"entity_id": entite, **self.etats[entite]})
        if chemin.startswith("/api/services/") and requete.method == "POST":
            domaine, _, service = chemin.removeprefix("/api/services/").partition("/")
            corps = json.loads(requete.content or b"{}")
            self.services.append((f"{domaine}.{service}", corps))
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    def _jeton(self, requete: httpx.Request) -> httpx.Response:
        formulaire = {k: v[0] for k, v in parse_qs(requete.content.decode()).items()}
        self.formulaires.append(formulaire)
        if formulaire.get("grant_type") == "authorization_code":
            defi = self.defis.pop(formulaire.get("code", ""), None)
            verifieur = formulaire.get("code_verifier", "")
            calcule = base64.urlsafe_b64encode(hashlib.sha256(verifieur.encode()).digest()).rstrip(b"=").decode()
            if defi is None or calcule != defi:
                return httpx.Response(400, json={"error": "invalid_grant"})
            rafraichir = f"rafraichir-{len(self.rafraichissements)}"
            self.rafraichissements.add(rafraichir)
        elif formulaire.get("grant_type") == "refresh_token":
            if formulaire.get("refresh_token") not in self.rafraichissements:
                return httpx.Response(400, json={"error": "invalid_grant"})
            rafraichir = ""
        else:
            return httpx.Response(400, json={"error": "unsupported_grant_type"})
        self.echanges += 1
        acces = f"acces-{self.echanges}"
        self.acces_valides.add(acces)
        corps: dict[str, Any] = {"access_token": acces, "token_type": "Bearer", "expires_in": 1800}
        if rafraichir:
            corps["refresh_token"] = rafraichir
        return httpx.Response(200, json=corps)

    def _mcp(self, requete: httpx.Request) -> httpx.Response:
        assert "text/event-stream" in requete.headers.get("accept", "")
        message = json.loads(requete.content)
        methode, ident = message.get("method"), message.get("id")
        if methode == "initialize":
            session = f"session-{len(self.sessions) + 1}"
            self.sessions.add(session)
            resultat = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "ha"}}
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": ident, "result": resultat}, headers={"Mcp-Session-Id": session}
            )
        if requete.headers.get("mcp-session-id") not in self.sessions:
            return httpx.Response(400, json={"error": "session inconnue"})
        if ident is None:  # notification
            return httpx.Response(202)
        if methode == "tools/list":
            outils = [{"name": n, "inputSchema": {}} for n in ("GetLiveContext", "HassTurnOn", "HassTurnOff")]
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": ident, "result": {"tools": outils}})
        if methode == "tools/call":
            nom, arguments = message["params"]["name"], message["params"].get("arguments", {})
            self.outils.append((nom, arguments))
            if nom == "GetLiveContext":
                texte = "Live Context: Salon (light) : off ; Température : 21.5 °C"
            else:
                texte = json.dumps({"success": True, "targets": [arguments.get("name")]})
            # Réponse en flux SSE, comme le fait le transport « streamable HTTP »
            corps = {"jsonrpc": "2.0", "id": ident, "result": {"content": [{"type": "text", "text": texte}]}}
            flux = f"event: message\ndata: {json.dumps(corps)}\n\n"
            return httpx.Response(200, text=flux, headers={"Content-Type": "text/event-stream"})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "?"}})
