"""Faux serveur MCP (stdio, JSON-RPC 2.0 ligne par ligne) pour les tests : outils « echo » et « planter ».

« planter » arrête le processus sans répondre (plantage pendant un appel). Variable FAUX_MCP_OUTILS=1 : vingt outils
de plus, aux descriptions variées (choix des outils par le sens).
"""

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

OUTILS = [
    {
        "name": "echo",
        "description": "Répète le texte reçu",
        "inputSchema": {"type": "object", "properties": {"texte": {"type": "string"}}, "required": ["texte"]},
    },
    {"name": "planter", "description": "Arrête brutalement le serveur", "inputSchema": {"type": "object"}},
]
SUJETS = [
    ("meteo", "Prévisions météo et température de la ville"),
    ("calendrier", "Lire les rendez-vous du calendrier et de l'agenda"),
    ("courriel", "Chercher dans les courriels reçus"),
    ("fichiers", "Lister et lire les fichiers d'un dossier"),
    ("musique", "Lancer une chanson ou une liste de lecture"),
    ("traduction", "Traduire un texte dans une autre langue"),
    ("calculatrice", "Calculer une expression mathématique"),
    ("cartes", "Itinéraire et distance entre deux adresses"),
    ("notes", "Créer et lire des notes rapides"),
    ("taches", "Liste de tâches à faire et rappels"),
    ("photos", "Chercher des photos par date ou par lieu"),
    ("bourse", "Cours des devises et conversion"),
    ("recettes", "Recettes de cuisine et ingrédients"),
    ("sport", "Résultats sportifs et scores des matchs"),
    ("trains", "Horaires des trains et des bus"),
    ("dictionnaire", "Définition d'un mot et synonymes"),
    ("minuteur", "Démarrer un minuteur ou un compte à rebours"),
    ("wiki", "Résumé d'un article encyclopédique"),
    ("depots", "Lister les dépôts git et leurs branches"),
    ("imprimante", "État de l'imprimante et niveau d'encre"),
]
if os.environ.get("FAUX_MCP_OUTILS"):
    OUTILS += [{"name": n, "description": d, "inputSchema": {"type": "object"}} for n, d in SUJETS]


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
    elif methode == "tools/call" and message["params"].get("name") == "planter":
        sys.exit(3)
    elif methode == "tools/call":
        args = message["params"].get("arguments") or {}
        texte = f"écho : {args.get('texte', '')}"
        repondre(ident, {"content": [{"type": "text", "text": texte}], "isError": False})
    else:
        erreur = {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "inconnu"}}
        print(json.dumps(erreur), flush=True)
