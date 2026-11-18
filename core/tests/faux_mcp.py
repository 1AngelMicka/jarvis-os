"""Faux serveur MCP (stdio, JSON-RPC 2.0 ligne par ligne) pour les tests : un outil « echo »."""

import json
import sys

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

OUTILS = [
    {
        "name": "echo",
        "description": "Répète le texte reçu",
        "inputSchema": {"type": "object", "properties": {"texte": {"type": "string"}}, "required": ["texte"]},
    }
]


def repondre(ident: object, resultat: object) -> None:
    print(json.dumps({"jsonrpc": "2.0", "id": ident, "result": resultat}, ensure_ascii=False), flush=True)


for ligne in sys.stdin:
    message = json.loads(ligne)
    methode, ident = message.get("method"), message.get("id")
    if ident is None:  # notification
        continue
    if methode == "initialize":
        repondre(
            ident, {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "faux"}}
        )
    elif methode == "tools/list":
        repondre(ident, {"tools": OUTILS})
    elif methode == "tools/call":
        args = message["params"].get("arguments") or {}
        texte = f"écho : {args.get('texte', '')}"
        repondre(ident, {"content": [{"type": "text", "text": texte}], "isError": False})
    else:
        erreur = {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "inconnu"}}
        print(json.dumps(erreur), flush=True)
