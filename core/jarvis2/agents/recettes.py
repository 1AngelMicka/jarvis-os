"""Recettes : une consigne envoyée à JARVIS selon une planification, résultat livré sur le canal choisi.

Une recette est un fichier YAML partageable dans le dossier `recettes/` de la configuration locale :

    nom: Point du matin
    planification: "30 7 * * 1-5"      # cron : minute heure jour mois jour-de-semaine (heure de Paris)
    consigne: |
      Fais le point sur mes projets en cours, en cinq lignes.
    connecteur: auto                   # ou l'identifiant d'un connecteur (ollama, claude_code…)
    livraison: conversation            # « conversation » (une conversation par exécution) ou « memoire »
    active: true

Le planificateur (battement toutes les 30 s) lance chaque recette à son heure, une seule fois, jamais pendant
l'arrêt d'urgence. Une recette n'agit pas : elle ne fait que demander une réponse (aucune action 🟡 ni 🔴).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

import yaml
from croniter import croniter

from .. import memoire
from ..db import Base
from ..dialogue import ServiceDialogue
from ..securite.urgence import ArretUrgence

journal = logging.getLogger("jarvis2.recettes")

FUSEAU = ZoneInfo("Europe/Paris")
IDENT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
Livraison = Literal["conversation", "memoire"]


class ErreurRecette(ValueError):
    pass


@dataclass(frozen=True)
class Recette:
    id: str
    nom: str
    planification: str
    consigne: str
    connecteur: str | None = None
    livraison: Livraison = "conversation"
    active: bool = True

    def prochaine(self, apres: datetime) -> datetime:
        """Prochaine exécution strictement après `apres` (calculée à l'heure de Paris)."""
        suivante: datetime = croniter(self.planification, apres.astimezone(FUSEAU)).get_next(datetime)
        return suivante.astimezone(UTC)

    def en_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyser(ident: str, donnees: Any) -> Recette:
    if not IDENT.match(ident):
        raise ErreurRecette(f"{ident} : nom de fichier invalide (minuscules, chiffres, - et _)")
    if not isinstance(donnees, dict):
        raise ErreurRecette(f"{ident} : une table YAML est attendue")
    manquants = [c for c in ("nom", "planification", "consigne") if not donnees.get(c)]
    if manquants:
        raise ErreurRecette(f"{ident} : champs manquants ({', '.join(manquants)})")
    planification = str(donnees["planification"]).strip()
    if not croniter.is_valid(planification):
        raise ErreurRecette(f"{ident} : planification cron invalide « {planification} »")
    livraison = donnees.get("livraison", "conversation")
    if livraison not in ("conversation", "memoire"):
        raise ErreurRecette(f"{ident} : livraison « conversation » ou « memoire » attendue")
    connecteur = donnees.get("connecteur")
    return Recette(
        id=ident,
        nom=str(donnees["nom"])[:120],
        planification=planification,
        consigne=str(donnees["consigne"]).strip()[:20_000],
        connecteur=None if connecteur in (None, "", "auto") else str(connecteur),
        livraison=livraison,
        active=bool(donnees.get("active", True)),
    )


def charger(dossier: Path) -> tuple[list[Recette], list[str]]:
    """Recettes du dossier (fichiers .yaml / .yml) et erreurs de lecture, sans jamais lever."""
    recettes: list[Recette] = []
    erreurs: list[str] = []
    if not dossier.is_dir():
        return recettes, erreurs
    for fichier in sorted([*dossier.glob("*.yaml"), *dossier.glob("*.yml")]):
        try:
            recettes.append(analyser(fichier.stem, yaml.safe_load(fichier.read_text(encoding="utf-8"))))
        except (OSError, yaml.YAMLError, ErreurRecette) as exc:
            erreurs.append(str(exc) if isinstance(exc, ErreurRecette) else f"{fichier.name} : {exc}")
    return recettes, erreurs


class Planificateur:
    def __init__(
        self,
        base: Base,
        dialogue: ServiceDialogue,
        dossier: Path,
        urgence: ArretUrgence,
        intervalle: float = 30.0,
    ) -> None:
        self.base = base
        self.dialogue = dialogue
        self.dossier = dossier
        self.urgence = urgence
        self.intervalle = intervalle
        self.depart = datetime.now(UTC)  # une recette jamais exécutée attend sa première heure après le démarrage
        self.en_cours: set[str] = set()

    def recettes(self) -> tuple[list[Recette], list[str]]:
        return charger(self.dossier)

    async def derniere(self, ident: str) -> dict[str, Any] | None:
        ligne = await self.base.fetchrow(
            "SELECT id, declencheur, debut, fin, statut, conversation_id, resultat, erreur"
            " FROM executions_recettes WHERE recette = $1 ORDER BY id DESC LIMIT 1",
            ident,
        )
        return dict(ligne) if ligne else None

    async def battement(self, maintenant: datetime | None = None) -> list[str]:
        """Lance les recettes dues ; renvoie leurs identifiants."""
        maintenant = maintenant or datetime.now(UTC)
        lancees = []
        recettes, _ = self.recettes()
        for r in recettes:
            if not r.active or r.id in self.en_cours:
                continue
            derniere = await self.derniere(r.id)
            reference = derniere["debut"] if derniere else self.depart
            if r.prochaine(reference) <= maintenant:
                lancees.append(r.id)
                await self.executer(r, "planification")
        return lancees

    async def boucle(self) -> None:
        while True:
            try:
                await self.battement()
            except Exception:  # une recette en échec ne doit jamais arrêter les autres
                journal.exception("Battement du planificateur en échec")
            await asyncio.sleep(self.intervalle)

    async def executer(self, r: Recette, declencheur: str = "manuel") -> dict[str, Any]:
        """Exécute la recette maintenant ; le résultat est livré puis gardé dans `executions_recettes`."""
        if self.urgence.actif:
            ident = await self.base.fetchval(
                "INSERT INTO executions_recettes (recette, declencheur, statut, fin, erreur)"
                " VALUES ($1, $2, 'ignoree', now(), 'arrêt d''urgence actif') RETURNING id",
                r.id,
                declencheur,
            )
            return {"id": ident, "statut": "ignoree"}
        self.en_cours.add(r.id)
        ident = await self.base.fetchval(
            "INSERT INTO executions_recettes (recette, declencheur, statut) VALUES ($1, $2, 'en_cours') RETURNING id",
            r.id,
            declencheur,
        )
        conversation_id: UUID | None = None
        try:
            texte = ""
            with self.urgence.suivre():
                async for ev in self.dialogue.repondre(r.consigne, moteur=r.connecteur):
                    if ev.type == "debut":
                        conversation_id = UUID(ev.donnees["conversation_id"])
                        titre = f"Recette : {r.nom} — {datetime.now(FUSEAU):%d/%m %H:%M}"
                        await self.dialogue.depot.renommer(conversation_id, titre, "auto")
                    elif ev.type == "fin":
                        texte = ev.donnees["texte"]
                    elif ev.type == "erreur":
                        raise RuntimeError(ev.donnees["message"])
            if r.livraison == "memoire" and self.dialogue.memoire is not None:
                source = self.dialogue.memoire
                await memoire.ajouter(
                    self.base,
                    f"[Recette « {r.nom} », {datetime.now(FUSEAU):%d/%m/%Y %H:%M}]\n{texte}",
                    type_="note",
                    tags=["recette"],
                    source=f"recette:{r.id}",
                    origine="systeme",
                    vecteur=await source.encodeur.encoder(texte),
                    modele=source.encodeur.nom_modele,
                )
            await self.base.execute(
                "UPDATE executions_recettes SET statut = 'ok', fin = now(), conversation_id = $2, resultat = $3"
                " WHERE id = $1",
                ident,
                conversation_id,
                texte[:20_000],
            )
            return {"id": ident, "statut": "ok", "conversation_id": conversation_id}
        except Exception as exc:
            journal.warning("Recette %s en échec : %s", r.id, exc)
            await self.base.execute(
                "UPDATE executions_recettes SET statut = 'erreur', fin = now(), conversation_id = $2, erreur = $3"
                " WHERE id = $1",
                ident,
                conversation_id,
                str(exc)[:2000],
            )
            return {"id": ident, "statut": "erreur", "erreur": str(exc)}
        finally:
            self.en_cours.discard(r.id)
