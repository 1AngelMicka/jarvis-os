"""Serveur MCP (stdio) lancé par Claude Code dans un atelier : son outil `autoriser` demande la décision au Core.

Claude Code l'appelle avant CHAQUE outil (`--permission-prompt-tool mcp__jarvis__autoriser`). L'adresse du Core et
le jeton propre à cette exécution d'atelier arrivent par l'environnement ; sans réponse du Core : refus.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx

OUTIL = {
    "name": "autoriser",
    "description": "Décision de JARVIS sur l'utilisation d'un outil par Claude Code dans un atelier",
    "inputSchema": {
        "type": "object",
        "properties": {"tool_name": {"type": "string"}, "input": {"type": "object"}, "tool_use_id": {"type": "string"}},
        "required": ["tool_name", "input"],
    },
}


def decision(arguments: dict[str, Any], client: httpx.Client | None = None) -> dict[str, Any]:
    url, jeton = os.environ.get("JARVIS2_ATELIER_URL"), os.environ.get("JARVIS2_ATELIER_JETON")
    if not url or not jeton:
        return {"behavior": "deny", "message": "Atelier mal configuré"}
    corps = {"tool_name": str(arguments.get("tool_name", "")), "input": arguments.get("input") or {}}
    try:
        with client or httpx.Client(timeout=660) as c:
            rep = c.post(url, json=corps, headers={"X-Atelier-Jeton": jeton})
            rep.raise_for_status()
            resultat: dict[str, Any] = rep.json()
            return resultat
    except (httpx.HTTPError, ValueError) as exc:
        return {"behavior": "deny", "message": f"JARVIS injoignable : {exc}"}


def traiter(message: dict[str, Any]) -> dict[str, Any] | None:
    methode, ident = message.get("method"), message.get("id")
    if ident is None:
        return None
    if methode == "initialize":
        resultat: Any = {
            "protocolVersion": (message.get("params") or {}).get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "jarvis", "version": "1"},
        }
    elif methode == "tools/list":
        resultat = {"tools": [OUTIL]}
    elif methode == "tools/call":
        params = message.get("params") or {}
        if params.get("name") != "autoriser":
            return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32602, "message": "Outil inconnu"}}
        texte = json.dumps(decision(params.get("arguments") or {}), ensure_ascii=False)
        resultat = {"content": [{"type": "text", "text": texte}]}
    else:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "Méthode inconnue"}}
    return {"jsonrpc": "2.0", "id": ident, "result": resultat}


def main() -> int:
    for ligne in sys.stdin:
        try:
            reponse = traiter(json.loads(ligne))
        except json.JSONDecodeError:
            continue
        if reponse is not None:
            sys.stdout.write(json.dumps(reponse, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0
