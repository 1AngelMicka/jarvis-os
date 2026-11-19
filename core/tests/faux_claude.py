"""Fausse CLI `claude` pour les tests : imite la sortie stream-json de Claude Code 2.1.

Scénario choisi par la variable FAUX_CLAUDE (lue dans l'environnement transmis par le moteur) :
- ok (défaut) : init (apiKeySource=none), deux morceaux de texte, résultat ;
- cle_api     : init avec apiKeySource=ANTHROPIC_API_KEY ;
- erreur      : résultat is_error ;
- lent        : attend 30 s avant de répondre (délai dépassé) ;
- sans_init   : texte sans événement init ;
- echo        : renvoie le prompt reçu sur l'entrée standard (morceau unique) ;
- limites     : comme ok, avec deux `rate_limit_event` (5 h mesurée, 7 jours sans utilisation donnée) ;
- refuse      : `rate_limit_event` rejeté (limite 5 h atteinte) puis résultat en erreur.
Écrit son PID dans FAUX_CLAUDE_PID si défini. Signale toute clé API présente dans son environnement.
"""

from __future__ import annotations

import json
import os
import sys
import time


def ecrire(objet: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(objet) + "\n")
    sys.stdout.flush()


def delta(texte: str) -> dict[str, object]:
    return {
        "type": "stream_event",
        "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": texte}},
    }


def main() -> int:
    if "--version" in sys.argv:
        print("9.9.9 (Claude Code)")
        return 0
    if os.environ.get("FAUX_CLAUDE_PID"):
        with open(os.environ["FAUX_CLAUDE_PID"], "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    scenario = os.environ.get("FAUX_CLAUDE", "ok")
    prompt = sys.stdin.read()
    fuites = sorted(k for k in os.environ if k in ("ANTHROPIC_API_KEY", "DATABASE_URL") or k.startswith("POSTGRES_"))
    modele = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "claude-sonnet-5-5"
    if scenario == "sans_init":
        ecrire(delta("bonjour"))
        ecrire({"type": "result", "is_error": False, "result": "bonjour"})
        return 0
    ecrire(
        {"type": "system", "subtype": "init", "apiKeySource": "ANTHROPIC_API_KEY" if scenario == "cle_api" else "none"}
    )
    if scenario in ("limites", "refuse"):
        ecrire(
            {
                "type": "rate_limit_event",
                "rate_limit_info": {
                    "status": "rejected" if scenario == "refuse" else "allowed_warning",
                    "rateLimitType": "five_hour",
                    "utilization": 1.0 if scenario == "refuse" else 0.42,
                    "resetsAt": int(time.time()) + 3600,
                },
            }
        )
    if scenario == "refuse":
        ecrire({"type": "result", "is_error": True, "result": "Limite de 5 heures atteinte"})
        return 1
    if scenario == "limites":
        ecrire({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "rateLimitType": "seven_day"}})
    if scenario == "lent":
        time.sleep(30)
    if scenario == "erreur":
        ecrire({"type": "result", "is_error": True, "result": "quota atteint"})
        return 1
    if fuites:
        texte = "FUITE:" + ",".join(fuites)
        ecrire(delta(texte))
    elif scenario == "echo":
        texte = prompt
        ecrire(delta(texte))
    elif scenario == "images":  # ce que la CLI voit : outils permis, dossier de travail, fichiers présents
        outils = sys.argv[sys.argv.index("--tools") + 1]
        fichiers = ",".join(sorted(os.listdir(os.getcwd())))
        texte = json.dumps({"outils": outils, "cwd": os.getcwd(), "fichiers": fichiers, "prompt": prompt})
        ecrire(delta(texte))
    else:
        texte = "Bonjour, Monsieur."
        ecrire(delta("Bonjour, "))
        ecrire(delta("Monsieur."))
    ecrire(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": texte,
            "duration_ms": 12,
            "total_cost_usd": 0.0012,
            "usage": {
                "input_tokens": 3,
                "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 7,
                "output_tokens": 5,
            },
            "modelUsage": {modele: {"outputTokens": 5}, "claude-haiku-5-5": {"outputTokens": 1}},
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
