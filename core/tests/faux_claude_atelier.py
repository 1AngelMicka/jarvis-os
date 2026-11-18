"""Fausse CLI `claude` pour les ateliers : lit la consigne, écrit un fichier dans son dossier de travail (le
worktree), imite la sortie stream-json. FAUX_ATELIER=lent : attend 30 s (pour tester l'arrêt)."""

import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]


def ecrire(objet: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(objet, ensure_ascii=False) + "\n")
    sys.stdout.flush()


consigne = sys.stdin.buffer.read().decode("utf-8")
session = "session-reprise" if "--resume" in sys.argv else "session-1"
ecrire({"type": "system", "subtype": "init", "apiKeySource": "none", "session_id": session, "model": "faux"})
if os.environ.get("FAUX_ATELIER") == "lent":
    time.sleep(30)
nom = f"travail-{hashlib.sha256(consigne.encode()).hexdigest()[:6]}.txt"
Path(nom).write_text(consigne, encoding="utf-8")
ecrire(
    {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Write", "input": {"file_path": nom}}]}}
)
ecrire({"type": "assistant", "message": {"content": [{"type": "text", "text": f"Fichier {nom} écrit."}]}})
ecrire({"type": "result", "is_error": False, "result": f"Terminé : {nom}"})
