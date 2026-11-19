"""« Où partent mes données » : la carte des flux, générée depuis la configuration RÉELLE de cette installation.

Pour chaque fonction de JARVIS : le service contacté, ce qui part, si cela reste sur le PC, et où le désactiver.
Rien de secret ni de précis n'est renvoyé : ni clé, ni adresse de serveur (SearXNG, points d'accès, nom Tailscale),
ni lieu de la maison, ni chemin, ni commande d'un serveur MCP. Seulement une catégorie de destination :

- `pc`       : rien ne quitte l'ordinateur ;
- `reseau`   : réseau local ou réseau privé de l'utilisateur (Tailscale, serveur de la maison) ;
- `internet` : un service en ligne ;
- `variable` : dépend du programme lancé (serveurs MCP).
"""

from __future__ import annotations

import ipaddress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit

from . import matin

if TYPE_CHECKING:
    from .api import Contexte
    from .config import Parametres

Destination = Literal["pc", "reseau", "internet", "variable"]
Etat = Literal["actif", "sur_accord", "inactif"]

# Services des connecteurs connus (le nom affiché vient du moteur ; ici, qui reçoit vraiment les données)
SERVICES = {
    "claude_code": "Anthropic, par votre abonnement Claude (programme Claude Code)",
    "codex": "OpenAI, par votre compte (programme Codex)",
    "antigravity": "Google, par votre compte (programme Antigravity)",
    "anthropic_api": "Anthropic (API, facturée à l'usage)",
    "openai": "OpenAI (API, facturée à l'usage)",
    "gemini": "Google (API Gemini)",
    "openrouter": "OpenRouter, puis le fournisseur du modèle choisi",
}
JAMAIS_IA = ("Souvenirs privés et réponses bâties dessus", "Secrets et données personnelles, masqués avant l'envoi")


@dataclass
class Desactivation:
    texte: str
    reglage: str | None = None  # section de la vue Réglages (`#reglages/<section>`)
    vue: str | None = None  # autre vue de l'interface (« agents »)


@dataclass
class Flux:
    id: str
    categorie: str
    fonction: str
    service: str
    destination: Destination
    etat: Etat
    envoie: list[str]
    desactiver: Desactivation
    jamais: list[str] = field(default_factory=list)
    detail: str | None = None
    # Connecteur cloud qui lit les images : accord séparé (None : sans objet)
    images: dict[str, Any] | None = None

    @property
    def local(self) -> bool:
        return self.destination == "pc"

    def en_dict(self) -> dict[str, Any]:
        return {**asdict(self), "local": self.local}


def destination_url(url: str | None) -> Destination:
    """Catégorie d'une adresse, sans jamais la renvoyer : PC, réseau privé ou Internet."""
    hote = (urlsplit(url).hostname or "").lower() if url else ""
    if not hote:
        return "internet"
    if hote in ("localhost", "localhost.localdomain") or hote.endswith(".localhost"):
        return "pc"
    if hote.endswith((".local", ".lan", ".home.arpa", ".internal", ".ts.net")):
        return "reseau"
    try:
        ip = ipaddress.ip_address(hote)
    except ValueError:
        return "internet" if "." in hote else "reseau"  # nom sans domaine : machine du réseau local
    if ip.is_loopback:
        return "pc"
    if ip.is_private or ip.is_link_local or ip in ipaddress.ip_network("100.64.0.0/10"):
        return "reseau"  # 100.64/10 : adresses Tailscale (CGNAT)
    return "internet"


async def _connecteurs(c: Contexte) -> tuple[list[Flux], int]:
    """Connecteurs d'IA réellement utilisables : actifs, installés (programme ou serveur présent), et avec leur clé
    pour ceux qui en demandent une. Seuls les connecteurs actifs sont sondés (8 s au plus chacun, en parallèle)."""
    gestion = c.connecteurs
    if gestion is None:
        return [], 0
    installes = {e.id for e in await gestion.etats(tous=False) if e.sante.installe}
    flux: list[Flux] = []
    inactifs = 0
    for ident, d in gestion.definitions.items():
        m = d.moteur.interne
        cle_absente = d.cle is not None and not gestion.coffre.lire(d.cle)
        if ident not in installes or cle_absente:
            inactifs += 1
            continue
        url = getattr(m, "url", None)
        # Fournisseur connu : Internet. Point d'accès déclaré ou modèle local : selon son adresse (jamais renvoyée)
        destination: Destination = (
            "internet" if ident in SERVICES or (m.externe and not url) else destination_url(url) if url else "pc"
        )
        envoie = [
            "Vos messages et l'historique récent de la conversation",
            "Les consignes de JARVIS et la mémoire utile au message",
            "Titres, résumés, conseil et missions qui passent par cette IA",
        ]
        images: dict[str, Any] | None = None
        if m.vision:
            if gestion.accord_images_requis(ident):
                le = gestion.images_accordees_le(ident)
                images = {"accorde": le is not None, "accorde_le": le}
                envoie.append("Les images jointes, " + ("accord donné" if le else "seulement après votre accord"))
            else:
                envoie.append("Les images jointes")
        if ident == "claude_code" and c.ateliers is not None and c.ateliers.projets:
            envoie.append("Ateliers : le code des projets ouverts aux ateliers")
        service = SERVICES.get(ident) or (
            "Modèle sur ce PC"
            if destination == "pc"
            else "Serveur de votre réseau"
            if destination == "reseau"
            else "Point d'accès déclaré dans votre configuration"
        )
        flux.append(
            Flux(
                id=f"connecteur:{ident}",
                categorie="ia",
                fonction=f"Conversations avec « {m.nom} »",
                service=service,
                destination=destination,
                etat="actif",
                envoie=envoie,
                jamais=list(JAMAIS_IA) if m.externe else [],
                desactiver=Desactivation("Désactiver ce connecteur (ou retirer sa clé)", reglage="connecteurs"),
                images=images,
                detail="Rien ne part tant que vous n'écrivez pas à cette IA." if not m.externe else None,
            )
        )
    return flux, inactifs


async def _meteo(c: Contexte) -> list[Flux]:
    etat = await matin.lire_etat(c.pool)
    lieu = bool(
        matin.Lieu.depuis(etat.get("localisation"))
        or matin.Lieu.depuis(c.matin_locale, "configuration")
        or c.matin_locale.get("ville")
    )
    actif = lieu and etat.get("mode") != "desactive"
    return [
        Flux(
            id="meteo",
            categorie="accueil",
            fonction="Météo de l'accueil du matin",
            service="Open-Meteo (sans compte ni clé)",
            destination="internet",
            etat="actif" if actif else "inactif",
            envoie=[
                "Les coordonnées de la maison, arrondies à environ 1 km",
                "Le nom de la ville cherchée, une seule fois, pour trouver ses coordonnées",
            ],
            jamais=["Votre nom, vos messages, votre mémoire"],
            desactiver=Desactivation("Effacer le lieu ou désactiver l'accueil du matin", reglage="accueil-matin"),
            detail=None if lieu else "Aucun lieu choisi : rien ne part.",
        )
    ]


def _recherche(c: Contexte) -> list[Flux]:
    url = c.recherche.url
    instance = {"pc": "sur ce PC", "reseau": "sur votre réseau"}.get(destination_url(url) if url else "", "en ligne")
    flux = [
        Flux(
            id="searxng",
            categorie="recherche",
            fonction="Recherche web des missions",
            service="Votre instance SearXNG, puis les moteurs de recherche qu'elle interroge",
            # Les requêtes finissent chez les moteurs de recherche : Internet, quel que soit l'endroit de l'instance
            destination="internet",
            etat="actif" if url else "inactif",
            envoie=["Les requêtes de recherche des missions (jamais pour un sujet privé)"],
            jamais=["Votre mémoire, vos conversations, votre adresse IP (masquée par SearXNG)"],
            desactiver=Desactivation("Retirer « searxng » de la section [recherche] de la configuration locale"),
            detail=f"Instance {instance}." if url else "Aucune instance déclarée : aucune recherche web.",
        )
    ]
    sources = c.scientifique
    flux.append(
        Flux(
            id="scientifique",
            categorie="recherche",
            fonction="Sources scientifiques des missions",
            service=", ".join(sources.noms) if sources else "OpenAlex, arXiv, PubMed, Europe PMC",
            destination="internet",
            etat="actif" if sources and sources.disponible else "inactif",
            envoie=["Les requêtes de recherche des missions (jamais pour un sujet privé)"],
            jamais=["Votre mémoire, vos conversations"],
            desactiver=Desactivation("Mettre « scientifique = false » dans la section [recherche] de la configuration"),
        )
    )
    return flux


def _telechargements(c: Contexte, p: Parametres) -> list[Flux]:
    from .api_telechargements import etats

    prets = [e["titre"] for e in etats(c, p) if e["statut"] == "pret"]
    return [
        Flux(
            id="telechargements",
            categorie="installation",
            fonction="Téléchargement des modèles de mémoire et de voix",
            service="Hugging Face (fichiers publics, sans compte)",
            destination="internet",
            etat="sur_accord",
            envoie=["La demande des fichiers du modèle (votre adresse IP, comme pour tout téléchargement)"],
            jamais=["Vos données : on reçoit des fichiers, on n'envoie rien"],
            desactiver=Desactivation("Rien ne part sans votre clic sur « Télécharger »", reglage="installation"),
            detail=("Déjà sur le PC : " + ", ".join(prets) + ".") if prets else None,
        )
    ]


def _locaux(c: Contexte) -> list[Flux]:
    flux = [
        Flux(
            id="memoire",
            categorie="memoire",
            fonction="Mémoire : souvenirs et recherche",
            service="Base et modèle d'embeddings sur ce PC",
            destination="pc",
            etat="actif" if c.memoire is not None else "inactif",
            envoie=[],
            desactiver=Desactivation("Rien à désactiver : tout reste sur le PC", reglage="blocs-memoire"),
        ),
        Flux(
            id="dictee",
            categorie="voix",
            fonction="Dictée et mains libres",
            service="Transcription Whisper sur ce PC",
            destination="pc",
            etat="actif" if c.transcripteur is not None else "inactif",
            envoie=[],
            desactiver=Desactivation("Couper l'écoute dans Voix & écoute", reglage="ecoute"),
        ),
        Flux(
            id="lecture",
            categorie="voix",
            fonction="Lecture à voix haute",
            service="Voix de l'appareil ou Piper (voix neuronale sur ce PC)",
            destination="pc",
            etat="actif",
            envoie=[],
            desactiver=Desactivation("Couper la voix dans Voix & écoute", reglage="lecture"),
        ),
        Flux(
            id="interface",
            categorie="interface",
            fonction="Interface",
            service="Servie par le Core, sans police, script ni image externes",
            destination="pc",
            etat="actif",
            envoie=[],
            desactiver=Desactivation("Rien à désactiver : aucune ressource externe n'est chargée"),
        ),
    ]
    if c.modele_vision and not c.sans_ecran:
        flux.append(
            Flux(
                id="ecran",
                categorie="voix",
                fonction="Écran décrit sur demande",
                service="Modèle de vision Ollama",
                destination=destination_url(c.url_ollama),
                etat="sur_accord",
                envoie=["Une capture de l'écran, à chaque demande"],
                desactiver=Desactivation("Ne pas utiliser le bouton « Écran »", reglage="ecoute"),
            )
        )
    return flux


def _telephone(c: Contexte, p: Parametres) -> list[Flux]:
    ts = c.tailscale
    flux = [
        Flux(
            id="telephone",
            categorie="appareils",
            fonction="JARVIS sur le téléphone, hors de chez vous",
            service="Tailscale : réseau privé chiffré entre vos appareils",
            destination="reseau",
            etat="actif" if ts is not None and ts.connecte and ts.serve_actif else "inactif",
            envoie=[
                "Tout l'échange entre le téléphone et le PC, chiffré de bout en bout",
                "Tailscale ne voit que la liste de vos appareils, jamais le contenu",
            ],
            desactiver=Desactivation("Arrêter « tailscale serve » ou révoquer le téléphone", reglage="telephone"),
        )
    ]
    if p.ouverture_reseau:
        flux.append(
            Flux(
                id="reseau_local",
                categorie="appareils",
                fonction="Core ouvert au réseau local",
                service="Appareils de votre réseau, jumelés par QR",
                destination="reseau",
                etat="actif",
                envoie=["Les échanges des appareils jumelés (chaque appareil a son jeton)"],
                desactiver=Desactivation("Retirer JARVIS2_OUVERTURE_RESEAU de la configuration", reglage="appareils"),
            )
        )
    return flux


async def _mcp(c: Contexte) -> list[Flux]:
    if c.mcp is None or not c.mcp.serveurs:
        return []
    actifs = {s for s, _ in await c.mcp.actifs(c.pool)}
    return [
        Flux(
            id=f"mcp:{ident}",
            categorie="outils",
            fonction=f"Outils MCP « {ident} »",
            service="Programme lancé sur le PC ; il peut lui-même contacter Internet",
            destination="variable",
            etat="actif" if ident in actifs else "inactif",
            envoie=["Les paramètres de chaque appel d'outil, après votre accord (🟡)"],
            desactiver=Desactivation("Désactiver ses outils dans la vue Agents", vue="agents"),
        )
        for ident in c.mcp.serveurs
    ]


async def _elevenlabs(c: Contexte) -> list[Flux]:
    """Voix en ligne ElevenLabs : seulement si l'utilisateur a rangé sa clé ; active quand c'est la voix choisie."""
    if c.synthese is None:
        return []
    from . import synthese

    cle = c.synthese.cle_elevenlabs()
    choisie = (await synthese.lire_reglages(c.pool))["moteur"] == "elevenlabs"
    return [
        Flux(
            id="elevenlabs",
            categorie="voix",
            fonction="Lecture à voix haute par ElevenLabs",
            service="ElevenLabs (voix en ligne, avec votre clé)",
            destination="internet",
            etat="actif" if cle and choisie else "inactif",
            envoie=["Le texte de chaque phrase lue à voix haute, secrets et données personnelles masqués"],
            jamais=[
                "Les phrases sur un sujet ou des souvenirs privés : lues par une voix locale",
                "Votre mémoire, vos conversations entières",
            ],
            desactiver=Desactivation("Choisir une voix locale dans Voix & écoute", reglage="lecture"),
            detail=None if cle else "Aucune clé enregistrée : rien ne part.",
        )
    ]


async def decrire(c: Contexte, p: Parametres) -> dict[str, Any]:
    connecteurs, inactifs = await _connecteurs(c)
    flux = [
        *connecteurs,
        *_recherche(c),
        *await _meteo(c),
        *_telechargements(c, p),
        *_telephone(c, p),
        *await _mcp(c),
        *await _elevenlabs(c),
        *_locaux(c),
    ]
    sortants = [f for f in flux if not f.local and f.etat == "actif"]
    return {
        "genere_le": datetime.now(UTC).isoformat(timespec="seconds"),
        "resume": {
            "flux": len(flux),
            "locaux": sum(f.local for f in flux),
            "sortants_actifs": len(sortants),
            "internet_actifs": sum(f.destination == "internet" for f in sortants),
            "connecteurs_inactifs": inactifs,
        },
        "flux": [f.en_dict() for f in flux],
    }
