"""Tâches de nuit de la mémoire (heure de Paris) : résumés des conversations 3 h 15, consolidation 3 h 30, oubli par
archivage 3 h 45, export 4 h ; extractions de connaissances reportées (aucune IA dans la journée) 3 h 50."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .agents.recettes import TacheSysteme
from .blocs import lister as lister_blocs
from .consolidation import consolider
from .db import Base
from .dialogue import ServiceDialogue
from .memoire_v2 import exporter_markdown, oublier
from .titrage import resumer_recentes

if TYPE_CHECKING:
    from .connaissances import ServiceConnaissances


def taches_memoire(
    base: Base, dialogue: ServiceDialogue, dossier_export: Path, connaissances: ServiceConnaissances | None = None
) -> list[TacheSysteme]:
    async def consolidation(derniere: datetime | None) -> dict[str, Any]:
        depuis = derniere or datetime.now(UTC) - timedelta(days=1)
        return await consolider(base, dialogue, depuis)

    async def resumes(derniere: datetime | None) -> dict[str, Any]:
        return await resumer_recentes(base, dialogue, derniere)

    async def oubli(_: datetime | None) -> dict[str, Any]:
        return {"archives": await oublier(base)}

    async def export(_: datetime | None) -> dict[str, Any]:
        fichiers = await exporter_markdown(base, dossier_export, await lister_blocs(base))
        return {"fichiers": len(fichiers), "dossier": str(dossier_export)}

    async def reprise(_: datetime | None) -> dict[str, Any]:
        assert connaissances is not None
        return await connaissances.reprendre()

    taches = [
        TacheSysteme("resumes", "Résumé de chaque conversation (privé : IA locale)", "15 3 * * *", resumes),
        TacheSysteme("consolidation", "Consolidation de la mémoire (IA locale)", "30 3 * * *", consolidation),
        TacheSysteme("oubli", "Archivage des souvenirs oubliés", "45 3 * * *", oubli),
        TacheSysteme("export", "Export Markdown de la mémoire", "0 4 * * *", export),
    ]
    if connaissances is not None:
        taches.append(TacheSysteme("connaissances", "Extractions de connaissances reportées", "50 3 * * *", reprise))
    return taches
