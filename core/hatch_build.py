"""Construction du paquet : l'interface compilée est livrée dans la roue distribuable (`jarvis2/web`).

L'installation de développement (`uv sync`, mode éditable) n'en a pas besoin : le Core sert alors celle du dépôt.
Sans interface compilée, la roue est construite sans elle (avertissement ; `jarvis2 docteur` le signale et le Core
affiche une page d'explication), sauf si `JARVIS2_EXIGER_INTERFACE=1` (CI, publication) : la construction échoue.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

AIDE_INTERFACE = "cd interface ; npm install ; npm run build"


class InterfaceLivree(BuildHookInterface):  # type: ignore[misc]
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name != "wheel" or version == "editable":
            return
        depot = Path(self.root).parent
        for nom in ("LICENSE", "NOTICE"):  # licence Apache 2.0 : texte et mentions livrés avec le paquet
            if (depot / nom).is_file():
                build_data["force_include"][str(depot / nom)] = f"jarvis2/{nom}"
        dist = depot / "interface" / "dist"
        if (dist / "index.html").is_file():
            build_data["force_include"][str(dist)] = "jarvis2/web"
        elif os.environ.get("JARVIS2_EXIGER_INTERFACE") == "1":
            raise RuntimeError(f"Interface non compilée : {AIDE_INTERFACE}")
        else:
            self.app.display_warning(
                f"Interface non compilée : roue construite SANS interface ({AIDE_INTERFACE}, puis reconstruire)."
            )
