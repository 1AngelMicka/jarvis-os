"""Connecteurs maison facultatifs : Philips Hue (API locale du pont), OBS Studio (WebSocket v5), Home Assistant.

Désactivés par défaut. Une fois activés par l'utilisateur, leurs commandes sont des actions du registre
(🟢 état, 🟡 lumières / scènes / enregistrement / prises / média, 🔴 démarrer un direct, serrures, alarme, portail ;
pour Home Assistant, le 🔴 exige en plus la voix du propriétaire), soumises à la file d'approbations, au
journal d'audit et à l'arrêt d'urgence. Un connecteur désactivé n'expose aucune action.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..db import Base, Executant, Ligne
from ..securite import audit
from ..securite.appareils import Appareil
from ..securite.coffre import Coffre
from ..securite.permissions import ErreurAction
from .home_assistant import ErreurHomeAssistant, ServiceHomeAssistant
from .hue import ErreurHue, PontHue, adresse_locale, decouvrir_en_ligne, decouvrir_mdns
from .obs import PORT_DEFAUT, ClientOBS, ErreurOBS

CLES = {"hue": "maison.hue", "obs": "maison.obs"}  # noms dans le coffre (clé du pont, mot de passe OBS)
NOMS = {"hue": "Philips Hue", "obs": "OBS Studio"}
DESCRIPTIONS = {
    "hue": "Lumières et scènes par le pont Hue, sur le réseau local (aucun passage par le cloud Hue).",
    "obs": "Scènes, enregistrement et direct d'OBS Studio par son serveur WebSocket (OBS 28 ou plus récent).",
}

Decouvreur = Callable[[], Awaitable[list[str]]]


def _erreur(exc: Exception) -> ErreurAction:
    return ErreurAction(str(exc))


@dataclass
class GestionnaireMaison:
    pool: Base
    coffre: Coffre
    transport_hue: httpx.AsyncBaseTransport | None = None  # tests : faux pont
    decouvreur_local: Decouvreur = decouvrir_mdns
    transport_en_ligne: httpx.AsyncBaseTransport | None = None
    transport_ha: httpx.AsyncBaseTransport | None = None  # tests : faux Home Assistant
    proprietaire: Any = None  # ServiceProprietaire, branché par le Contexte (garde des actions 🔴 de Home Assistant)
    ha: ServiceHomeAssistant = field(init=False)
    _reglages: dict[str, Ligne] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.ha = ServiceHomeAssistant(self.pool, self.coffre, self.transport_ha)

    async def charger(self, conn: Executant | None = None) -> None:
        lignes = await (conn or self.pool).fetch("SELECT id, actif, adresse FROM connecteurs_maison")
        self._reglages = {r["id"]: r for r in lignes}
        await self.ha.charger()

    # --- État --------------------------------------------------------------------------------------------

    def actif(self, ident: str) -> bool:
        if ident == "home_assistant":
            return self.ha.actif
        r = self._reglages.get(ident)
        return bool(r and r["actif"])

    def adresse(self, ident: str) -> str | None:
        r = self._reglages.get(ident)
        return str(r["adresse"]) if r and r["adresse"] else None

    def _verifier(self, ident: str) -> None:
        if ident not in NOMS:
            raise ErreurAction(f"Connecteur maison inconnu : « {ident} »")

    def decrire(self) -> list[dict[str, Any]]:
        """Cartes de l'interface : jamais la clé du pont ni le mot de passe, seulement « enregistré »."""
        return [
            {
                "id": i,
                "nom": NOMS[i],
                "description": DESCRIPTIONS[i],
                "actif": self.actif(i),
                "adresse": self.adresse(i),
                "secret_enregistre": bool(self.coffre.lire(CLES[i])),
                "outils": [o for o in OUTILS if o["connecteur"] == i],
            }
            for i in NOMS
        ]

    def decrire_ha(self) -> dict[str, Any]:
        return {**self.ha.decrire(), "outils": [o for o in OUTILS if o["connecteur"] == "home_assistant"]}

    async def garder_rouge(self, etape: str) -> None:
        """Action 🔴 de Home Assistant (serrure, alarme, portail) : en plus de la clé d'accès, la voix du propriétaire.
        Reconnaissance désactivée ou indisponible : refus. À la demande, une phrase du propriétaire reconnue dans les
        2 dernières minutes est exigée (la demande se dit à voix haute) ; à l'exécution, la reconnaissance doit
        toujours être disponible."""
        p = self.proprietaire
        etat = await p.etat() if p is not None else None
        raison: str | None = None
        if etat is None or not etat["actif"] or not etat["disponible"]:
            raison = (
                "la reconnaissance du propriétaire est indisponible (activez-la et enregistrez votre voix dans"
                " Voix & écoute)"
            )
        elif etape == "demande" and p.derniere_reconnue() is None:
            raison = "dites la demande à voix haute : la voix du propriétaire doit être reconnue (2 dernières minutes)"
        if raison is None:
            return
        await audit.journaliser(
            self.pool, acteur="maison", action="maison.rouge_refusee", niveau="rouge", details={"etape": etape}
        )
        raise ErreurAction(f"Action 🔴 refusée : {raison}")

    def outils_actifs(self) -> list[dict[str, Any]]:
        """Outils proposables au dialogue : seulement ceux des connecteurs activés (et configurés)."""
        return [o for o in OUTILS if self.actif(str(o["connecteur"]))]

    # --- Réglages (gestes de l'utilisateur dans l'interface, journalisés) ---------------------------------

    async def _ecrire(self, ident: str, **valeurs: Any) -> None:
        actuel = self._reglages.get(ident)
        actif = valeurs.get("actif", bool(actuel["actif"]) if actuel else False)
        adresse = valeurs["adresse"] if "adresse" in valeurs else (actuel["adresse"] if actuel else None)
        await self.pool.execute(
            "INSERT INTO connecteurs_maison (id, actif, adresse) VALUES ($1, $2, $3)"
            " ON CONFLICT (id) DO UPDATE SET actif = $2, adresse = $3, maj_le = now()",
            ident,
            actif,
            adresse,
        )
        await self.charger()

    async def activer(self, ident: str, actif: bool, appareil: Appareil) -> None:
        self._verifier(ident)
        if actif and not (self.adresse(ident) and (ident == "obs" or self.coffre.lire(CLES[ident]))):
            raise ErreurAction("Appairez d'abord le pont Hue" if ident == "hue" else "Indiquez d'abord l'adresse d'OBS")
        await self._ecrire(ident, actif=actif)
        await audit.journaliser(
            self.pool,
            acteur=appareil.acteur,
            action="maison.active" if actif else "maison.desactive",
            cible=ident,
            niveau="jaune" if actif else "vert",
        )

    async def decouvrir_hue(self, en_ligne: bool, appareil: Appareil) -> list[str]:
        """mDNS sur le réseau local ; le service en ligne de Signify seulement si `en_ligne` (accord coché)."""
        try:
            adresses = await self.decouvreur_local()
        except OSError:
            adresses = []
        if not adresses and en_ligne:
            await audit.journaliser(
                self.pool, acteur=appareil.acteur, action="maison.hue.decouverte_en_ligne", cible="hue", niveau="jaune"
            )
            try:
                adresses = await decouvrir_en_ligne(self.transport_en_ligne)
            except ErreurHue as exc:
                raise _erreur(exc) from exc
        return adresses

    async def appairer_hue(self, adresse: str, appareil: Appareil) -> None:
        try:
            propre = adresse_locale(adresse)
            cle = await PontHue(propre, transport=self.transport_hue).appairer()
        except ErreurHue as exc:
            raise _erreur(exc) from exc
        await asyncio.to_thread(self.coffre.definir, CLES["hue"], cle)
        await self._ecrire("hue", adresse=propre)
        await audit.journaliser(
            self.pool, acteur=appareil.acteur, action="maison.hue.appaire", cible="hue", niveau="jaune"
        )  # jamais la clé

    async def configurer_obs(self, adresse: str, mot_de_passe: str | None, appareil: Appareil) -> None:
        try:
            propre = adresse_locale(adresse, boucle=True)
        except ErreurHue as exc:
            raise _erreur(exc) from exc
        if mot_de_passe is not None:
            if mot_de_passe.strip():
                await asyncio.to_thread(self.coffre.definir, CLES["obs"], mot_de_passe)
            else:
                await asyncio.to_thread(self.coffre.supprimer, CLES["obs"])
        await self._ecrire("obs", adresse=propre)
        await audit.journaliser(
            self.pool,
            acteur=appareil.acteur,
            action="maison.obs.configure",
            cible="obs",
            niveau="jaune",
            details={"mot_de_passe": "enregistré" if self.coffre.lire(CLES["obs"]) else "aucun"},
        )

    async def oublier(self, ident: str, appareil: Appareil) -> None:
        """Retire la clé ou le mot de passe du coffre et désactive le connecteur."""
        self._verifier(ident)
        await asyncio.to_thread(self.coffre.supprimer, CLES[ident])
        await self._ecrire(ident, actif=False, adresse=None)
        await audit.journaliser(self.pool, acteur=appareil.acteur, action="maison.oublie", cible=ident)

    # --- Clients (utilisés par les actions) --------------------------------------------------------------

    def pont(self) -> PontHue:
        if not self.actif("hue"):
            raise ErreurAction("Connecteur Philips Hue désactivé : activez-le dans Connecteurs")
        adresse, cle = self.adresse("hue"), self.coffre.lire(CLES["hue"])
        if not adresse or not cle:
            raise ErreurAction("Pont Hue non appairé")
        return PontHue(adresse, cle, self.transport_hue)

    def obs(self) -> ClientOBS:
        if not self.actif("obs"):
            raise ErreurAction("Connecteur OBS désactivé : activez-le dans Connecteurs")
        adresse = self.adresse("obs")
        if not adresse:
            raise ErreurAction("Adresse d'OBS non renseignée")
        hote, _, port = adresse.rpartition(":") if adresse.count(":") == 1 else (adresse, "", "")
        return ClientOBS(hote, int(port) if port else PORT_DEFAUT, self.coffre.lire(CLES["obs"]))

    async def tester(self, ident: str) -> dict[str, Any]:
        """🟢 Lecture de l'état, sans rien changer."""
        self._verifier(ident)
        try:
            etat = await (self.pont().etat() if ident == "hue" else self.obs().etat())
        except (ErreurHue, ErreurOBS, ErreurHomeAssistant) as exc:
            return {"disponible": False, "detail": str(exc)}
        except ErreurAction as exc:
            return {"disponible": False, "detail": str(exc)}
        if ident == "hue":
            detail = f"{len(etat['lumieres'])} lampe(s), {len(etat['scenes'])} scène(s)"
        else:
            detail = f"scène « {etat['scene']} », {len(etat['scenes'])} scène(s)"
        return {"disponible": True, "detail": detail}


# Outils déclarés (nom d'action du registre, niveau, paramètres) : la même liste sert à l'interface, au registre et
# aux outils proposables au dialogue.
OUTILS: list[dict[str, Any]] = [
    {
        "nom": "hue.etat",
        "connecteur": "hue",
        "niveau": "vert",
        "description": "Lire l'état des lampes, pièces et scènes Hue",
        "parametres": {},
    },
    {
        "nom": "hue.allumer",
        "connecteur": "hue",
        "niveau": "jaune",
        "description": "Allumer une lampe ou un groupe Hue",
        "parametres": {"cible": "lumiere | groupe", "id": "identifiant (groupe 0 : toutes)"},
    },
    {
        "nom": "hue.eteindre",
        "connecteur": "hue",
        "niveau": "jaune",
        "description": "Éteindre une lampe ou un groupe Hue",
        "parametres": {"cible": "lumiere | groupe", "id": "identifiant (groupe 0 : toutes)"},
    },
    {
        "nom": "hue.luminosite",
        "connecteur": "hue",
        "niveau": "jaune",
        "description": "Régler la luminosité d'une lampe ou d'un groupe Hue (1 à 100 %)",
        "parametres": {"cible": "lumiere | groupe", "id": "identifiant", "pourcent": "1 à 100"},
    },
    {
        "nom": "hue.couleur",
        "connecteur": "hue",
        "niveau": "jaune",
        "description": "Changer la couleur d'une lampe ou d'un groupe Hue",
        "parametres": {"cible": "lumiere | groupe", "id": "identifiant", "couleur": "#RRGGBB"},
    },
    {
        "nom": "hue.scene",
        "connecteur": "hue",
        "niveau": "jaune",
        "description": "Activer une scène Hue",
        "parametres": {"scene": "identifiant de la scène"},
    },
    {
        "nom": "obs.etat",
        "connecteur": "obs",
        "niveau": "vert",
        "description": "Lire la scène, l'enregistrement et le direct d'OBS",
        "parametres": {},
    },
    {
        "nom": "obs.scene",
        "connecteur": "obs",
        "niveau": "jaune",
        "description": "Changer la scène affichée par OBS",
        "parametres": {"scene": "nom de la scène"},
    },
    {
        "nom": "obs.enregistrement",
        "connecteur": "obs",
        "niveau": "jaune",
        "description": "Démarrer ou arrêter l'enregistrement OBS",
        "parametres": {"demarrer": "true | false"},
    },
    {
        "nom": "obs.direct.arreter",
        "connecteur": "obs",
        "niveau": "jaune",
        "description": "Arrêter le direct OBS",
        "parametres": {},
    },
    {
        "nom": "obs.direct.demarrer",
        "connecteur": "obs",
        "niveau": "rouge",
        "description": "Démarrer un direct OBS (publication : confirmation par clé d'accès)",
        "parametres": {},
    },
    # --- Home Assistant : niveau décidé par le domaine (voir home_assistant.DOMAINES) ---------------------------
    {
        "nom": "ha.etat",
        "connecteur": "home_assistant",
        "niveau": "vert",
        "description": "Lire l'état de la maison (Home Assistant)",
        "parametres": {},
    },
    {
        "nom": "ha.lumiere",
        "connecteur": "home_assistant",
        "niveau": "jaune",
        "description": "Allumer, éteindre ou régler une lumière (Home Assistant)",
        "parametres": {"entite": "light.…", "allumer": "true | false", "luminosite": "1 à 100 (facultatif)"},
    },
    {
        "nom": "ha.prise",
        "connecteur": "home_assistant",
        "niveau": "jaune",
        "description": "Allumer ou éteindre une prise (Home Assistant)",
        "parametres": {"entite": "switch.…", "allumer": "true | false"},
    },
    {
        "nom": "ha.media",
        "connecteur": "home_assistant",
        "niveau": "jaune",
        "description": "Lecture, pause, piste suivante ou volume d'un lecteur (Home Assistant)",
        "parametres": {
            "entite": "media_player.…",
            "commande": "lecture | pause | suivant | volume",
            "volume": "0 à 100",
        },
    },
    {
        "nom": "ha.serrure",
        "connecteur": "home_assistant",
        "niveau": "rouge",
        "description": "Verrouiller ou ouvrir une serrure (clé d'accès + voix du propriétaire)",
        "parametres": {"entite": "lock.…", "operation": "verrouiller | ouvrir"},
    },
    {
        "nom": "ha.alarme",
        "connecteur": "home_assistant",
        "niveau": "rouge",
        "description": "Armer ou désarmer l'alarme (clé d'accès + voix du propriétaire)",
        "parametres": {"entite": "alarm_control_panel.…", "mode": "absent | present | nuit | desarmer"},
    },
    {
        "nom": "ha.portail",
        "connecteur": "home_assistant",
        "niveau": "rouge",
        "description": "Ouvrir ou fermer un portail ou une porte de garage (clé d'accès + voix du propriétaire)",
        "parametres": {"entite": "cover.…", "operation": "ouvrir | fermer"},
    },
]
