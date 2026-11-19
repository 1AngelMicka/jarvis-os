"""JARVIS pilote l'interface : le bloc d'actions de ses réponses, validé par le Core.

Quand l'utilisateur le demande, le modèle termine sa réponse par `<actions>[…]</actions>` (JSON). Le Core :
1. retire le bloc du texte (rien n'est affiché ni lu à voix haute) ;
2. valide chaque action contre une liste fermée (types, vues, identifiants qui existent, longueurs) ; le reste est
   écarté et compté, jamais exécuté ;
3. applique les règles de protection (une action qui en touche une « interdire » est écartée) ;
4. classe chaque action :
   - `immediate` (naviguer, ouvrir, rechercher dans la mémoire, régler thème / animations) : l'interface l'applique
     d'elle-même en mode « oui », propose un bouton en mode « demander » ;
   - `proposition` (lancer une mission, un atelier, demander une action déclarée, ajouter une règle) : TOUJOURS un
     bouton que l'utilisateur clique, quel que soit le mode (protection contre l'injection de prompt). Le clic passe
     par les routes habituelles : la mission par `POST /v1/missions`, une action déclarée par la file d'approbations
     (🟡 / 🔴), la règle par `POST /v1/regles`.
Le modèle n'exécute jamais rien lui-même : il propose, le Core vérifie, l'utilisateur décide.
Mode (etat_systeme « pilotage ») : `oui`, `demander` (défaut), `non` (aucune consigne, tout bloc est écarté).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from .db import Base, Executant
from .securite import regles
from .securite.jokers import ErreurMotif, compiler

Mode = Literal["oui", "demander", "non"]
MODES: tuple[Mode, ...] = ("oui", "demander", "non")
NB_MAX_ACTIONS = 5
TAILLE_MAX_BLOC = 6000

# Vues et panneaux que l'interface sait ouvrir (même liste que `VUES_PILOTABLES` de l'interface)
VUES: dict[str, str] = {
    "dialogue": "Dialogue",
    "historique": "Historique",
    "activite": "Activité",
    "demandes": "Demandes",
    "securite": "Sécurité",
    "memoire": "Mémoire",
    "connaissances": "Savoir",
    "agents": "Agents (missions, créations)",
    "ateliers": "Ateliers",
    "connecteurs": "Connecteurs",
    "couts": "Coûts",
    "reglages": "Réglages",
    "accueil": "Installation",
}
OUVRABLES: dict[str, tuple[str, str, str]] = {  # type → (table, colonne du titre, libellé)
    "conversation": ("conversations", "titre", "la conversation"),
    "mission": ("missions", "objectif", "la mission"),
    "creation": ("creations", "titre", "la création"),
    "atelier": ("ateliers", "nom", "l'atelier"),
}
REGLAGES_INTERFACE: dict[str, tuple[str, ...]] = {
    "theme": ("jarvis", "studio", "atelier", "console"),
    "animations": ("systeme", "normales", "reduites"),
}
TYPES_MISSION = ("recherche", "brainstorm", "revue")
IMMEDIATES = ("naviguer", "ouvrir", "rechercher_memoire", "regler")
PROPOSITIONS = ("proposer_mission", "proposer_atelier", "demander_action", "ajouter_regle")

_BLOC = re.compile(r"<actions>(.*?)(?:</actions>|$)", re.IGNORECASE | re.DOTALL)
_ANCRE = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")

CONSIGNES = """Piloter l'interface : SEULEMENT si l'utilisateur te demande d'aller quelque part, d'ouvrir un élément, \
de chercher dans ta mémoire, de changer le thème ou de lancer quelque chose, termine ta réponse par un bloc \
<actions>[…]</actions> contenant un tableau JSON (5 actions au plus). Simple discussion : aucun bloc.
Types :
- {{"type": "naviguer", "vue": "<{vues}>", "ancre": "<section des réglages, facultatif>"}}
- {{"type": "ouvrir", "objet": "conversation|mission|creation|atelier", "id": "<identifiant connu>"}}
- {{"type": "rechercher_memoire", "requete": "<mots>"}}
- {{"type": "regler", "cle": "theme|animations", "valeur": "<jarvis|studio|atelier|console>"}} \
(animations : systeme|normales|reduites)
- {{"type": "proposer_mission", "mission": "recherche|brainstorm|revue", "objectif": "<objectif précis>"}}
- {{"type": "proposer_atelier", "projet": "<{projets}>", "nom": "<tâche>"}}
- {{"type": "demander_action", "action": "<action déclarée>", "parametres": {{…}}}} (actions : {actions})
- {{"type": "ajouter_regle", "genre": "interdire|demander", "motif": "<mots ; * = tout>", "libelle": "<règle>"}}
Une mission, un atelier, une action déclarée ou une règle ne sont que des PROPOSITIONS que l'utilisateur valide \
d'un clic sous ta réponse : écris « je vous propose de… », jamais « c'est lancé » ni « c'est fait ». N'invente jamais \
d'identifiant : n'ouvre que ce que tu connais. Une suppression, un envoi ou une publication ne passent que par \
« demander_action » (l'utilisateur approuve, avec sa clé d'accès pour une action 🔴)."""


class ErreurPilotage(ValueError):
    """Message en français, affichable tel quel."""


@dataclass
class Extraction:
    texte: str  # réponse sans le bloc d'actions
    actions: list[dict[str, Any]]
    ecartees: list[str]  # raisons (jamais le contenu proposé)
    bloc: bool  # un bloc était présent

    def meta(self) -> dict[str, Any]:
        if not self.bloc:
            return {}
        return {"actions": self.actions, **({"actions_ecartees": self.ecartees} if self.ecartees else {})}


def retirer_bloc(texte: str) -> tuple[str, list[str]]:
    """(texte sans aucun bloc `<actions>`, contenus des blocs). Un bloc non fermé court jusqu'à la fin."""
    blocs = [m.group(1) for m in _BLOC.finditer(texte)]
    if not blocs:
        return texte, []
    propre = _BLOC.sub("", texte)
    propre = re.sub(r"```(?:json)?\s*```", "", propre)  # bloc enveloppé dans une clôture de code, désormais vide
    return propre.rstrip(), blocs


def _texte(valeur: Any, nom: str, maxi: int, mini: int = 1) -> str:
    if not isinstance(valeur, str):
        raise ErreurPilotage(f"« {nom} » : texte attendu")
    v = " ".join(valeur.split())
    if not mini <= len(v) <= maxi:
        raise ErreurPilotage(f"« {nom} » : entre {mini} et {maxi} caractères")
    return v


class ServicePilotage:
    def __init__(
        self,
        pool: Base,
        actions_declarees: Callable[[], dict[str, Any]],
        projets: Callable[[], dict[str, str]] = dict,
        garder: Callable[[str], bool] | None = None,
    ) -> None:
        """`actions_declarees()` : nom → Action du registre ; `projets()` : id → nom des projets d'ateliers ;
        `garder(texte)` : False si le texte nomme un sujet exclu (il n'est alors jamais montré au modèle)."""
        self.pool = pool
        self.actions_declarees = actions_declarees
        self.projets = projets
        self.garder = garder

    # --- Mode -----------------------------------------------------------------------------------------------

    async def mode(self) -> Mode:
        try:
            valeur = await self.pool.fetchval("SELECT valeur FROM etat_systeme WHERE cle = 'pilotage'")
        except Exception:  # base ancienne ou illisible : prudence
            return "demander"
        if isinstance(valeur, str):
            valeur = json.loads(valeur)
        mode = (valeur or {}).get("mode")
        return mode if mode in MODES else "demander"

    async def regler_mode(self, mode: str) -> Mode:
        if mode not in MODES:
            raise ErreurPilotage("Mode : oui, demander ou non")
        await self.pool.execute(
            # La clé est créée par la migration 014 ; le rôle de l'application n'a que SELECT / UPDATE sur cette table
            "UPDATE etat_systeme SET valeur = $1::text::jsonb, maj_le = now() WHERE cle = 'pilotage'",
            json.dumps({"mode": mode}),
        )
        return mode

    # --- Consignes ------------------------------------------------------------------------------------------

    async def consignes(self) -> str:
        """Section ajoutée aux consignes système : mode d'emploi du bloc (sauf mode « non ») et règles."""
        morceaux: list[str] = []
        if await self.mode() != "non":
            declarees = self.actions_declarees()
            projets = self.projets()
            morceaux.append(
                CONSIGNES.format(
                    vues="|".join(VUES),
                    projets="|".join(projets) or "aucun projet configuré",
                    actions=", ".join(
                        f"{nom} {'🔴' if getattr(a, 'niveau', '') == 'rouge' else '🟡'}"
                        for nom, a in declarees.items()
                        if not nom.startswith("regle.")
                    )
                    or "aucune",
                )
            )
        try:
            bloc = regles.bloc_consignes(await regles.lister(self.pool), self.garder)
        except Exception:
            bloc = ""
        if bloc:
            morceaux.append(bloc)
        return "\n\n".join(morceaux)

    # --- Extraction et validation ---------------------------------------------------------------------------

    async def extraire(self, texte: str) -> Extraction:
        propre, blocs = retirer_bloc(texte)
        if not blocs:
            return Extraction(texte, [], [], False)
        if await self.mode() == "non":
            return Extraction(propre, [], ["pilotage désactivé"], True)
        brut = blocs[-1].strip()
        brut = re.sub(r"^```(?:json)?|```$", "", brut).strip()
        if len(brut) > TAILLE_MAX_BLOC:
            return Extraction(propre, [], ["bloc trop long"], True)
        try:
            liste = json.loads(brut)
        except ValueError:
            return Extraction(propre, [], ["bloc illisible (JSON attendu)"], True)
        if isinstance(liste, dict):
            liste = [liste]
        if not isinstance(liste, list):
            return Extraction(propre, [], ["tableau d'actions attendu"], True)
        actions: list[dict[str, Any]] = []
        ecartees: list[str] = []
        regles_actives = await regles.lister(self.pool)
        for brute in liste:
            if len(actions) >= NB_MAX_ACTIONS:
                ecartees.append(f"plus de {NB_MAX_ACTIONS} actions")
                break
            try:
                action = await self.valider(brute)
            except ErreurPilotage as exc:
                ecartees.append(str(exc))
                continue
            texte_regle = regles.texte_action(action["type"], action["libelle"], action.get("parametres", {}))
            interdit = regles.premiere(regles_actives, texte_regle, "interdire")
            if interdit is not None and action["type"] != "ajouter_regle":
                ecartees.append(f"refusée par une règle de protection : « {interdit.libelle} »")
                continue
            actions.append(action)
        return Extraction(propre, actions, ecartees, True)

    async def valider(self, brute: Any, base: Executant | None = None) -> dict[str, Any]:
        """Action validée : {type, genre (immediate|proposition), niveau, libelle, parametres}."""
        if not isinstance(brute, dict):
            raise ErreurPilotage("action : objet JSON attendu")
        type_ = brute.get("type")
        if type_ not in IMMEDIATES + PROPOSITIONS:
            raise ErreurPilotage(f"type d'action inconnu : « {str(type_)[:40]} »")
        base = base or self.pool
        genre = "immediate" if type_ in IMMEDIATES else "proposition"
        niveau = "vert"
        if type_ == "naviguer":
            vue = brute.get("vue")
            if vue not in VUES:
                raise ErreurPilotage(f"vue inconnue : « {str(vue)[:40]} »")
            parametres: dict[str, Any] = {"vue": vue}
            ancre = brute.get("ancre")
            if ancre and vue == "reglages":
                if not isinstance(ancre, str) or not _ANCRE.match(ancre):
                    raise ErreurPilotage("ancre des réglages invalide")
                parametres["ancre"] = ancre
            libelle = f"Ouvrir {VUES[vue]}"
        elif type_ == "ouvrir":
            objet = brute.get("objet") or brute.get("type_objet")
            if objet not in OUVRABLES:
                raise ErreurPilotage("objet à ouvrir : conversation, mission, creation ou atelier")
            try:
                ident = UUID(str(brute.get("id")))
            except ValueError as exc:
                raise ErreurPilotage("identifiant invalide") from exc
            table, colonne, nom = OUVRABLES[objet]
            titre = await base.fetchval(f"SELECT {colonne} FROM {table} WHERE id = $1", ident)  # noqa: S608
            if titre is None:  # identifiant inventé ou effacé : jamais transmis à l'interface
                raise ErreurPilotage(f"{nom} demandée n'existe pas")
            court = " ".join(str(titre).split())
            court = court if len(court) <= 60 else f"{court[:59]}…"
            parametres = {"objet": objet, "id": str(ident), "titre": court}
            libelle = f"Ouvrir {nom} « {court} »"
        elif type_ == "rechercher_memoire":
            requete = _texte(brute.get("requete"), "requete", 200)
            parametres = {"requete": requete}
            libelle = f"Chercher « {requete} » dans la mémoire"
        elif type_ == "regler":
            cle, valeur = brute.get("cle"), brute.get("valeur")
            if cle not in REGLAGES_INTERFACE or valeur not in REGLAGES_INTERFACE[cle]:
                raise ErreurPilotage("réglage inconnu (theme ou animations)")
            parametres = {"cle": cle, "valeur": valeur}
            libelle = f"{'Thème' if cle == 'theme' else 'Animations'} : {valeur}"
        elif type_ == "proposer_mission":
            mission = brute.get("mission", "recherche")
            if mission not in TYPES_MISSION:
                raise ErreurPilotage("mission : recherche, brainstorm ou revue")
            objectif = _texte(brute.get("objectif"), "objectif", 1000, 3)
            parametres = {"mission": mission, "objectif": objectif}
            libelle = f"Lancer une mission ({mission}) : {objectif}"
        elif type_ == "proposer_atelier":
            projets = self.projets()
            projet = brute.get("projet")
            if projet not in projets:
                raise ErreurPilotage("projet d'atelier inconnu")
            nom_atelier = _texte(brute.get("nom"), "nom", 120)
            parametres = {"projet": projet, "nom": nom_atelier}
            libelle = f"Ouvrir un atelier sur {projets[projet]} : {nom_atelier}"
        elif type_ == "demander_action":
            declarees = self.actions_declarees()
            nom_action = brute.get("action")
            if not isinstance(nom_action, str) or nom_action not in declarees or nom_action.startswith("regle."):
                raise ErreurPilotage(f"action non déclarée : « {str(nom_action)[:40]} »")
            params = brute.get("parametres") or {}
            if not isinstance(params, dict) or len(json.dumps(params)) > 2000:
                raise ErreurPilotage("paramètres : objet JSON de 2 000 caractères au plus")
            declaree = declarees[nom_action]
            niveau = declaree.niveau
            parametres = {"action": nom_action, "parametres": params}
            try:
                libelle = declaree.resumer(params)
            except Exception:
                libelle = declaree.description
        else:  # ajouter_regle
            genre_regle = brute.get("genre")
            if genre_regle not in ("interdire", "demander"):
                raise ErreurPilotage("règle : interdire ou demander")
            motif = _texte(brute.get("motif"), "motif", 200, 2)
            try:
                compiler(motif)
            except ErreurMotif as exc:
                raise ErreurPilotage(str(exc)) from exc
            libelle_regle = _texte(brute.get("libelle") or motif, "libelle", 200)
            parametres = {"genre": genre_regle, "motif": motif, "libelle": libelle_regle}
            libelle = f"{'Interdire' if genre_regle == 'interdire' else 'Demander avant'} : {libelle_regle}"
        return {"type": type_, "genre": genre, "niveau": niveau, "libelle": libelle, "parametres": parametres}
