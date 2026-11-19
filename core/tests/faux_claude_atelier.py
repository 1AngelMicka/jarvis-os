"""Fausse CLI `claude` pour les ateliers : lit la consigne, écrit un fichier dans son dossier de travail (le
worktree), imite la sortie stream-json. FAUX_ATELIER=lent : attend 30 s (pour tester l'arrêt et la pause) ;
FAUX_ATELIER=echec : réponse en erreur ; FAUX_ATELIER_MARQUEUR=<fichier> : plante (code 1) tant que ce fichier
n'existe pas, puis le crée (pour tester la relance) ; FAUX_ATELIER_ARGS=<fichier> : y écrit ses arguments."""

import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]


def ecrire(objet: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(objet, ensure_ascii=False) + "\n")
    sys.stdout.flush()


consigne = sys.stdin.buffer.read().decode("utf-8")
session = "session-reprise" if "--resume" in sys.argv else "session-1"
if os.environ.get("FAUX_ATELIER_ARGS"):
    Path(os.environ["FAUX_ATELIER_ARGS"]).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
ecrire({"type": "system", "subtype": "init", "apiKeySource": "none", "session_id": session, "model": "faux"})
marqueur = os.environ.get("FAUX_ATELIER_MARQUEUR")
if marqueur and not Path(marqueur).exists():
    Path(marqueur).write_text("planté", encoding="utf-8")
    sys.stderr.write("plantage simulé\n")
    sys.exit(1)
if os.environ.get("FAUX_ATELIER") == "echec":
    ecrire({"type": "result", "is_error": True, "result": "Échec simulé"})
    sys.exit(0)
if os.environ.get("FAUX_ATELIER") == "lent":
    time.sleep(30)
nom = f"travail-{hashlib.sha256(consigne.encode()).hexdigest()[:6]}.txt"
Path(nom).write_text(consigne, encoding="utf-8")
ecrire(
    {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Write", "input": {"file_path": nom}}]}}
)
ecrire({"type": "assistant", "message": {"content": [{"type": "text", "text": f"Fichier {nom} écrit."}]}})
ecrire({"type": "result", "is_error": False, "result": f"Terminé : {nom}"})
