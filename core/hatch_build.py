"""Construction du paquet : l'interface compilée est livrée dans la roue distribuable (`jarvis2/web`).

L'installation de développement (`uv sync`, mode éditable) n'en a pas besoin : le Core sert alors celle du dépôt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class InterfaceLivree(BuildHookInterface):  # type: ignore[misc]
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name != "wheel" or version == "editable":
            return
        dist = Path(self.root).parent / "interface" / "dist"
        if not (dist / "index.html").is_file():
            raise RuntimeError("Interface non compilée : cd interface ; npm install ; npm run build")
        build_data["force_include"][str(dist)] = "jarvis2/web"
