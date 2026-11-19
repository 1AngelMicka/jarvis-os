"""Commandes rapides : une phrase reconnue sans IA → une action déclarée, éditable par l'utilisateur.

- Le motif (jokers `*` et captures `{nom}`, voir securite/jokers.py) est comparé à la phrase ENTIÈRE, sans accents
  ni majuscules ni ponctuation. Jamais d'expression régulière fournie, jamais d'évaluation, jamais de shell.
- La cible est soit une action d'interface (naviguer, ouvrir…, validée comme celles du bloc d'actions de JARVIS),
  soit une action déclarée du Core : elle passe alors par la file d'approbations (🟢 exécutée, 🟡 / 🔴 demandée ;
  🔴 seulement avec une clé d'accès), règles de protection comprises. Une commande ne donne aucun droit en plus.
- Priorité réglable (-100 à 100) ; à priorité égale, le motif le plus précis l'emporte, puis le plus ancien.
- Chaque commande porte une phrase de test qui DOIT correspondre au motif : elle est vérifiée à l'enregistrement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from .db import Base, Ligne
from .pilotage import IMMEDIATES, ErreurPilotage, ServicePilotage
from .securite.jokers import ErreurMotif, Motif, compiler, remplacer

if TYPE_CHECKING:
    from .securite.permissions import Registre

NB_MAX_COMMANDES = 200
TAILLE_MAX_PHRASE = 300  # au-delà, ce n'est pas une commande : la phrase va à l'IA
COLONNES = (
    "id, motif, cible, action, parametres, priorite, phrase_test, actif, utilisations, derniere_utilisation,"
    " cree_le, maj_le"
)
# Actions d'interface permises : celles qui ne lancent rien (une mission ou un atelier se proposent, voir pilotage)
ACTIONS_INTERFACE = tuple(a for a in IMMEDIATES if a != "ouvrir")  # « ouvrir » demande un identifiant précis


class ErreurCommande(ValueError):
    """Message en français, affichable tel quel."""


@dataclass(frozen=True)
class Commande:
    id: UUID
    motif: str
    cible: str
    action: str
    parametres: dict[str, Any]
    priorite: int
    phrase_test: str
    actif: bool
    utilisations: int
    derniere_utilisation: str | None
    cree_le: str
    maj_le: str

    def en_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "id": str(self.id)}


def _commande(r: Ligne) -> Commande:
    params = r["parametres"]
    if isinstance(params, str):
        params = json.loads(params)
    return Commande(
        r["id"],
        r["motif"],
        r["cible"],
        r["action"],
        params or {},
        r["priorite"],
        r["phrase_test"],
        bool(r["actif"]),
        r["utilisations"],
        r["derniere_utilisation"].isoformat() if r["derniere_utilisation"] else None,
        r["cree_le"].isoformat(),
        r["maj_le"].isoformat(),
    )


@dataclass(frozen=True)
class Correspondance:
    commande: Commande
    captures: dict[str, str]
    parametres: dict[str, Any]


class ServiceCommandes:
    def __init__(self, pool: Base, registre: Registre, pilotage: ServicePilotage) -> None:
        self.pool = pool
        self.registre = registre
        self.pilotage = pilotage

    # --- Validation -----------------------------------------------------------------------------------------

    def niveau(self, cible: str, action: str) -> str:
        if cible == "interface":
            return "vert"
        a = self.registre.actions.get(action)
        return a.niveau if a else "inconnu"

    async def verifier(
        self, motif: str, cible: str, action: str, parametres: dict[str, Any], phrase_test: str
    ) -> dict[str, Any]:
        """Vérifie une commande avant de l'enregistrer ; renvoie l'action résolue pour la phrase de test."""
        try:
            compile = compiler(motif)
        except ErreurMotif as exc:
            raise ErreurCommande(str(exc)) from exc
        captures = compile.correspond(phrase_test)
        if captures is None:
            raise ErreurCommande("La phrase de test ne correspond pas au motif")
        if not isinstance(parametres, dict) or len(json.dumps(parametres)) > 2000:
            raise ErreurCommande("Paramètres : objet JSON de 2 000 caractères au plus")
        try:
            resolus = remplacer(parametres, captures)
        except ErreurMotif as exc:
            raise ErreurCommande(str(exc)) from exc
        assert isinstance(resolus, dict)
        return await self.resoudre(cible, action, resolus, "Avec la phrase de test : ")

    async def resoudre(self, cible: str, action: str, parametres: dict[str, Any], prefixe: str = "") -> dict[str, Any]:
        """Action prête à appliquer (interface) ou à demander (Core), paramètres déjà remplis par les captures."""
        if cible == "interface":
            if action not in ACTIONS_INTERFACE:
                raise ErreurCommande(
                    "Action d'interface inconnue : " + ", ".join(ACTIONS_INTERFACE) + " (jamais de commande système)"
                )
            try:
                return await self.pilotage.valider({**parametres, "type": action})
            except ErreurPilotage as exc:
                raise ErreurCommande(f"{prefixe}{exc}") from exc
        if cible != "core":
            raise ErreurCommande("Cible : interface ou core")
        declaree = self.registre.actions.get(action)
        if declaree is None:
            raise ErreurCommande(f"Action inconnue : « {action} » (seules les actions déclarées, jamais de shell)")
        try:
            libelle = declaree.resumer(parametres)
        except Exception:
            libelle = declaree.description
        return {"type": action, "niveau": declaree.niveau, "libelle": libelle, "parametres": parametres}

    # --- Liste et édition -----------------------------------------------------------------------------------

    async def lister(self) -> list[Commande]:
        lignes = await self.pool.fetch(f"SELECT {COLONNES} FROM commandes_rapides ORDER BY priorite DESC, cree_le")
        return [_commande(r) for r in lignes]

    async def obtenir(self, ident: UUID) -> Commande | None:
        ligne = await self.pool.fetchrow(f"SELECT {COLONNES} FROM commandes_rapides WHERE id = $1", ident)
        return _commande(ligne) if ligne else None

    async def creer(self, donnees: dict[str, Any]) -> Commande:
        await self.verifier(
            donnees["motif"], donnees["cible"], donnees["action"], donnees["parametres"], donnees["phrase_test"]
        )
        if (await self.pool.fetchval("SELECT count(*) FROM commandes_rapides") or 0) >= NB_MAX_COMMANDES:
            raise ErreurCommande(f"{NB_MAX_COMMANDES} commandes rapides au plus")
        ligne = await self.pool.fetchrow(
            f"INSERT INTO commandes_rapides (motif, cible, action, parametres, priorite, phrase_test, actif)"
            f" VALUES ($1, $2, $3, $4::text::jsonb, $5, $6, $7) RETURNING {COLONNES}",
            donnees["motif"].strip(),
            donnees["cible"],
            donnees["action"],
            json.dumps(donnees["parametres"]),
            donnees["priorite"],
            donnees["phrase_test"].strip(),
            donnees["actif"],
        )
        assert ligne is not None
        return _commande(ligne)

    async def modifier(self, ident: UUID, donnees: dict[str, Any]) -> Commande:
        await self.verifier(
            donnees["motif"], donnees["cible"], donnees["action"], donnees["parametres"], donnees["phrase_test"]
        )
        ligne = await self.pool.fetchrow(
            f"UPDATE commandes_rapides SET motif = $2, cible = $3, action = $4, parametres = $5::text::jsonb,"
            f" priorite = $6, phrase_test = $7, actif = $8, maj_le = now() WHERE id = $1 RETURNING {COLONNES}",
            ident,
            donnees["motif"].strip(),
            donnees["cible"],
            donnees["action"],
            json.dumps(donnees["parametres"]),
            donnees["priorite"],
            donnees["phrase_test"].strip(),
            donnees["actif"],
        )
        if ligne is None:
            raise LookupError("Commande rapide introuvable")
        return _commande(ligne)

    async def supprimer(self, ident: UUID) -> Commande | None:
        ligne = await self.pool.fetchrow(f"DELETE FROM commandes_rapides WHERE id = $1 RETURNING {COLONNES}", ident)
        return _commande(ligne) if ligne else None

    # --- Reconnaissance -------------------------------------------------------------------------------------

    async def trouver(self, phrase: str, sauf: UUID | None = None) -> list[Correspondance]:
        """Toutes les commandes actives qui captent la phrase, de la plus prioritaire à la moins prioritaire."""
        if not phrase.strip() or len(phrase) > TAILLE_MAX_PHRASE:
            return []
        trouvees: list[tuple[tuple[int, int, str], Correspondance]] = []
        for c in await self.lister():
            if not c.actif or c.id == sauf:
                continue
            try:
                motif: Motif = compiler(c.motif)
            except ErreurMotif:
                continue
            captures = motif.correspond(phrase)
            if captures is None:
                continue
            try:
                params = remplacer(c.parametres, captures)
            except ErreurMotif:
                continue
            assert isinstance(params, dict)
            trouvees.append(((-c.priorite, -motif.specificite, c.cree_le), Correspondance(c, captures, params)))
        return [t[1] for t in sorted(trouvees, key=lambda t: t[0])]

    async def noter_utilisation(self, ident: UUID) -> None:
        await self.pool.execute(
            "UPDATE commandes_rapides SET utilisations = utilisations + 1, derniere_utilisation = now() WHERE id = $1",
            ident,
        )
