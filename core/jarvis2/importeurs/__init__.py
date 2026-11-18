"""Sources d'import : chaque source amène les données d'un autre outil dans la mémoire de JARVIS 2.

Source disponible : `jarvis_v1` (JARVIS v1, depuis une sauvegarde `pg_dump`). D'autres viendront (exports
d'assistants, notes Markdown…) : chacune vit dans son module et lit ses exclusions dans la configuration locale
(`[import.<nom>]`), jamais dans le code.
"""

from __future__ import annotations

from . import jarvis_v1

SOURCES = {jarvis_v1.NOM: jarvis_v1}

__all__ = ["SOURCES", "jarvis_v1"]
