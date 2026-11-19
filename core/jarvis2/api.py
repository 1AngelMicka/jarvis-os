"""API HTTP du Core (FastAPI).

- `GET  /v1/sante`                    : vivant + base joignable
- `GET  /v1/etat`                     : amorçage de l'interface en UN appel (moteurs, modèles, conversations)
- `GET  /v1/conversations`            : liste
- `GET  /v1/conversations/{id}`       : conversation + messages
- `POST /v1/dialogue`                 : message -> réponse en flux SSE (`debut`, `delta`, `fin`, `erreur`)
- `GET  /v1/donnees/flux`             : où partent mes données (voir api_donnees.py)
- sécurité (appareils, jumelage, clés d'accès, demandes, arrêt d'urgence, audit) : voir api_securite.py

Chaque requête `/v1/` exige le jeton d'un appareil autorisé (`Authorization: Bearer`), sauf la santé et le
jumelage. Une origine inconnue est refusée (page web malveillante qui viserait le Core). Pendant l'arrêt
d'urgence, toute écriture est refusée (HTTP 423) sauf ce qui sert à le lever. Le Core écoute sur 127.0.0.1 par
défaut ; l'ouvrir au réseau est un choix explicite (JARVIS2_OUVERTURE_RESEAU).
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import mimetypes
import webbrowser
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, memoire, vision, widgets
from .agents.mcp import GestionnaireMCP
from .agents.missions import ServiceMissions
from .agents.outils_tour import ServiceOutilsTour
from .agents.recettes import Planificateur
from .agents.recherche_web import RechercheWeb
from .agents.skills import ServiceSkills
from .agents.sources_scientifiques import SourcesScientifiques
from .ameliorations import ServiceAmeliorations
from .api_accueil import routeur as routeur_accueil
from .api_agents import routeur as routeur_agents
from .api_ameliorations import routeur as routeur_ameliorations
from .api_ateliers import routeur as routeur_ateliers
from .api_bureau import routeur as routeur_bureau
from .api_bureau import routeur_public as routeur_fichiers_uniques
from .api_chantiers import routeur as routeur_chantiers
from .api_connaissances import routeur as routeur_connaissances
from .api_connecteurs import routeur as routeur_connecteurs
from .api_donnees import routeur as routeur_donnees
from .api_eveil import routeur as routeur_eveil
from .api_maison import routeur as routeur_maison
from .api_matin import routeur as routeur_matin
from .api_medias import routeur as routeur_medias
from .api_medias import routeur_pages as routeur_creations
from .api_memoire import routeur as routeur_memoire
from .api_pc import routeur as routeur_pc
from .api_pilotage import routeur as routeur_pilotage
from .api_profil import routeur as routeur_profil
from .api_routage import routeur as routeur_routage
from .api_securite import routeur as routeur_securite
from .api_skills import routeur as routeur_skills
from .api_synthese import routeur as routeur_synthese
from .api_telechargements import routeur as routeur_telechargements
from .api_transcription import routeur as routeur_transcription
from .api_widgets import routeur as routeur_widgets
from .ateliers.gestionnaire import GestionnaireAteliers, Projet
from .ateliers.veille import SourceFichiersEtat, VeilleClaudeCode, dossier_par_defaut
from .commandes_rapides import ServiceCommandes
from .config import Parametres
from .config_locale import charger as charger_config_locale
from .config_locale import chemin_config
from .connaissances import ServiceConnaissances
from .connecteurs import Connecteurs, construire_catalogue
from .conseil import ServiceConseil
from .conversations import DepotConversations
from .db import Base, ErreurBaseOuReseau, ouvrir_base, version_schema
from .dialogue import AccordImagesRequis, ServiceDialogue, SourceMemoire
from .dictee import ServiceDictee
from .embeddings import EncodeurFastEmbed
from .eveil import ServiceEveil
from .fin_tour import JugeFinDeTour
from .maison import GestionnaireMaison
from .maison.satellites import ServiceSatellites
from .maison.wyoming import ServeurWyoming
from .matin import ServiceMeteo
from .memoire import Expurgateur, ReglagesRecherche
from .memoire_v2 import EtatBascule, basculer, modele_actif, modele_majoritaire
from .moteurs.base import ErreurMoteur, Options
from .moteurs.telemetrie import EnregistreurBase, MoteurInstrumente
from .nuit import taches_memoire
from .ocr import LecteurOCR
from .ocr import choisir as choisir_ocr
from .pc import ServicePC
from .pc import construire as construire_pc
from .pilotage import ServicePilotage
from .proprietaire import ServiceProprietaire
from .push import ServicePush
from .securite import appareils
from .securite.actions import creer_registre
from .securite.coffre import Coffre
from .securite.permissions import Approbations
from .securite.urgence import ArretUrgence
from .synthese import ServiceSynthese
from .tailscale import EtatTailscale
from .tailscale import lire_etat as lire_tailscale
from .telechargements import Telechargeur
from .transcription import TranscripteurRobuste
from .voix import Transcripteur

journal = logging.getLogger("jarvis2.api")

mimetypes.add_type("application/manifest+json", ".webmanifest")  # PWA : inconnu de certains systèmes

# Interface compilée : aucun script en ligne, aucune ressource externe.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


@dataclass
class Contexte:
    pool: Base
    depot: DepotConversations
    moteurs: dict[str, MoteurInstrumente]
    service: ServiceDialogue
    moteur_defaut: str
    memoire: SourceMemoire | None = None
    urgence: ArretUrgence = field(default_factory=ArretUrgence)
    telechargeur: Telechargeur = field(default_factory=Telechargeur)  # gros téléchargements, sur accord
    connecteurs: Connecteurs | None = None
    tailscale: EtatTailscale | None = None
    chargement_modele: str | None = None  # None, « absent », « en_cours », « termine », « erreur »
    mcp: GestionnaireMCP | None = None
    skills: ServiceSkills | None = None  # skills SKILL.md importés, revus et approuvés (phase 14, point 12)
    maison: GestionnaireMaison | None = None  # Hue, OBS : connecteurs facultatifs, désactivés par défaut
    pc: ServicePC | None = None  # ressources et contrôle du PC, Ollama à la demande, mode jeu (lot J)
    recherche: RechercheWeb = field(default_factory=lambda: RechercheWeb(None))
    scientifique: SourcesScientifiques | None = None  # bases scientifiques publiques des missions de recherche
    dossier_recettes: Path | None = None
    dossier_donnees: Path | None = None  # tâches de nuit de la mémoire (export Markdown dans memoire-md/)
    etat_bascule: EtatBascule | None = None
    ateliers: GestionnaireAteliers | None = None
    veille: VeilleClaudeCode | None = None  # sessions Claude Code de l'utilisateur (lecture seule, inactive par défaut)
    transcripteur: Transcripteur | None = None
    synthese: ServiceSynthese | None = None  # voix au choix : Piper (local) ou ElevenLabs (clé de l'utilisateur)
    dossier_modeles: Path | None = None  # modèle de reconnaissance du propriétaire (lot K3)
    modele_fin_tour: str = ""  # petit modèle local de fin de tour (vide : la règle seule)
    url_ollama: str = "http://127.0.0.1:11434"
    modele_vision: str | None = None
    ocr: LecteurOCR | None = None  # lecture du texte des images avant le modèle de vision (None : directement)
    sans_ecran: bool = False  # serveur sans écran : capture, clics et contrôle de l'écran refusés (voir ecran.py)
    meteo: ServiceMeteo = field(default_factory=ServiceMeteo)
    matin_locale: dict[str, Any] = field(default_factory=dict)  # [matin] de la configuration locale (privé)
    ameliorations: ServiceAmeliorations = field(init=False)
    approbations: Approbations = field(init=False)
    _taches_push: set[asyncio.Task[int]] = field(default_factory=set, init=False, repr=False)
    conseil: ServiceConseil = field(init=False)
    connaissances: ServiceConnaissances = field(init=False)
    missions: ServiceMissions = field(init=False)
    planificateur: Planificateur | None = field(init=False)
    pilotage: ServicePilotage = field(init=False)
    outils_tour: ServiceOutilsTour = field(init=False)  # outils proposés au modèle par tour (moins de 12)
    commandes: ServiceCommandes = field(init=False)
    push: ServicePush = field(init=False)  # notifications Web Push (clés VAPID dans le dossier des données)
    eveil: ServiceEveil = field(init=False)  # « Dis Jarvis » et conversation vocale de chaque appareil
    proprietaire: ServiceProprietaire = field(init=False)  # reconnaissance du propriétaire à la voix (lot K3)
    dictee: ServiceDictee = field(init=False)
    satellites: ServiceSatellites = field(init=False)  # satellites vocaux, pièces, profils par personne (14-D18)
    wyoming: ServeurWyoming = field(init=False)  # transcription et synthèse en Wyoming (désactivé par défaut)
    juge_fin_tour: JugeFinDeTour = field(init=False)

    def __post_init__(self) -> None:
        self.ameliorations = ServiceAmeliorations(self.pool, self.ateliers, self.urgence)
        if self.pc is not None:
            self.pc.sans_ecran = lambda: self.sans_ecran  # le mode peut être fixé au lancement (cycle de vie)
        self.approbations = Approbations(
            self.pool,
            creer_registre(self.urgence, self.mcp, self.ateliers, self.maison, self.ameliorations, self.pc),
        )
        self.conseil = ServiceConseil(self.service)
        expurgateur = self.memoire.reglages.expurgateur if self.memoire is not None else None
        ateliers = self.ateliers
        self.pilotage = ServicePilotage(
            self.pool,
            lambda: {a.nom: a for a in self.approbations.registre.disponibles()},
            (lambda: {i: p.nom for i, p in ateliers.projets.items()}) if ateliers is not None else dict,
            (lambda t: not expurgateur.mentionne(t)) if expurgateur is not None else None,
        )
        self.service.pilotage = self.pilotage  # bloc d'actions des réponses, validé par le Core
        self.outils_tour = ServiceOutilsTour(
            self.pool,
            self.mcp,
            self.skills,
            self.memoire.encodeur if self.memoire is not None else None,
            (lambda t: not expurgateur.mentionne(t)) if expurgateur is not None else None,
        )
        self.outils_tour.declarer(self.approbations.registre)
        if self.skills is not None:
            self.skills.declarer(self.approbations.registre)
        self.service.outils_tour = self.outils_tour.section
        self.commandes = ServiceCommandes(self.pool, self.approbations.registre, self.pilotage)
        self.eveil = ServiceEveil(self.pool, self.service, exclu=expurgateur.mentionne if expurgateur else None)
        self.connaissances = ServiceConnaissances(self.pool, self.service)
        self.missions = ServiceMissions(
            self.pool, self.service, self.recherche, self.urgence, self.scientifique, self.connaissances
        )
        taches = (
            taches_memoire(self.pool, self.service, self.dossier_donnees / "memoire-md", self.connaissances)
            if self.dossier_donnees is not None and self.memoire is not None
            else []
        )
        self.planificateur = (
            Planificateur(self.pool, self.service, self.dossier_recettes, self.urgence, taches=taches)
            if self.dossier_recettes is not None
            else None
        )
        if self.planificateur is not None and self.pc is not None:
            jeu = self.pc.jeu
            self.planificateur.en_pause = lambda: jeu.en_veille
        self.service.ce_qui_tourne = self.ce_qui_tourne
        self.push = ServicePush(self.pool, self.dossier_donnees)
        self.approbations.apres_demande = self.notifier_demande
        self.proprietaire = ServiceProprietaire(self.pool, self.dossier_donnees, self.dossier_modeles)
        if self.maison is not None:  # actions 🔴 de Home Assistant : voix du propriétaire exigée
            self.maison.proprietaire = self.proprietaire
        self.dictee = ServiceDictee(self.pool)
        self.juge_fin_tour = JugeFinDeTour(self.url_ollama, self.modele_fin_tour)
        if isinstance(self.transcripteur, TranscripteurRobuste):  # chaque phrase : verdict du propriétaire
            self.transcripteur.observateur = self.proprietaire.observer
        self.satellites = ServiceSatellites(self.pool)
        self.wyoming = ServeurWyoming(
            self.pool,
            self.satellites,
            self.transcripteur,
            self.synthese,
            proprietaire=self.proprietaire,
            repondre=self.repondre_satellite,
        )

    async def repondre_satellite(self, texte: str, satellite: dict[str, Any], personne: str | None) -> str:
        """Phrase entendue par un satellite : réponse de JARVIS (texte), comme une conversation tapée. Les actions
        🟡🔴 éventuelles restent des demandes à approuver ; la voix du propriétaire est vérifiée comme ailleurs."""
        morceaux: list[str] = []
        async for evenement in self.service.repondre(texte):
            if evenement.type == "delta":
                morceaux.append(str(evenement.donnees.get("texte", "")))
            elif evenement.type == "erreur":
                return "Désolé, je n'ai pas pu répondre."
        return "".join(morceaux).strip()[:2000]

    async def notifier_demande(self, demande: Any) -> None:
        """Nouvelle demande 🟡🔴 : appel de décision poussé aux téléphones abonnés (en tâche de fond)."""
        action = self.approbations.registre.actions.get(demande.action)
        description = action.description if action else demande.action
        tache = asyncio.create_task(self.push.notifier_demande(demande, description))
        self._taches_push.add(tache)
        tache.add_done_callback(self._taches_push.discard)

    async def ce_qui_tourne(self) -> str:
        """Résumé compact, à chaque échange : ateliers, sessions Claude Code veillées, missions en cours."""
        parties: list[str] = []
        if self.ateliers is not None:
            parties.append(await self.ateliers.resume())
        if self.veille is not None:
            parties.append(self.veille.resume())
        missions = [m for m in await self.missions.lister(10) if m["statut"] in ("en_file", "en_cours")]
        if missions:
            parties.append(
                "Missions en cours : "
                + " ; ".join(f"{m['type']} « {str(m['objectif'])[:80]} » ({m['statut']})" for m in missions[:5])
                + "."
            )
        texte = "\n".join(p for p in parties if p)
        return f"Ce qui tourne en ce moment :\n{texte}" if texte else ""


class ModificationConversation(BaseModel):
    titre: str | None = Field(None, max_length=120)
    epinglee: bool | None = None
    archivee: bool | None = None


class DemandeDialogue(BaseModel):
    message: str = Field(max_length=100_000)  # peut être vide s'il y a des images
    # Images jointes en data URL (5 au plus, 3 Mo chacune une fois décodées) : jamais gardées en base
    images: list[str] = Field(default_factory=list, max_length=5)
    conversation_id: UUID | None = None
    moteur: str | None = None
    modele: str | None = Field(default=None, max_length=200)
    effort: str | None = Field(default=None, max_length=20)


# Sans jeton : santé, état du jumelage, premier appareil (PC seulement), échange d'un code de jumelage
CHEMINS_PUBLICS = frozenset(
    {
        "/v1/sante",
        "/v1/auth/etat",
        "/v1/appareils/premier",
        "/v1/jumelage/echanger",
        "/v1/ateliers-autorisation",
        "/v1/maison/home-assistant/oauth/retour",
    }
)  # autorisation des ateliers : jeton propre à chaque exécution, PC seulement ; retour OAuth de Home Assistant :
# navigation du navigateur (sans jeton), validé par le `state` à usage unique et le vérifieur PKCE
# Écritures permises pendant l'arrêt d'urgence : ce qui sert à le lever ou à retirer un accès
ECRITURES_EN_URGENCE = (
    "/v1/urgence/",
    "/v1/demandes/",
    "/v1/cles/",
    "/v1/appareils/",
    "/v1/autorisations/",
    "/v1/regles",
    "/v1/protocole",  # vérifier un lien n'écrit rien (ouvre une vue au plus)
)


def origines_autorisees(p: Parametres) -> set[str]:
    hotes = {"127.0.0.1", "localhost"}
    ports = {p.port, 5174, 4174}
    return {f"http://{h}:{port}" for h in hotes for port in ports} | set(p.origines_supplementaires)


def sse(evenement: str, donnees: dict[str, Any]) -> bytes:
    return f"event: {evenement}\ndata: {json.dumps(donnees, ensure_ascii=False)}\n\n".encode()


async def construire_contexte(p: Parametres) -> Contexte:
    pool = await ouvrir_base(p)
    depot = DepotConversations(pool)
    locale = charger_config_locale()
    coffre = Coffre(chemin_config().parent / "coffre.json")
    connecteurs = Connecteurs(
        pool, construire_catalogue(p, locale, coffre, EnregistreurBase(pool)), coffre, prefere=p.moteur_defaut
    )
    moteurs = connecteurs.moteurs
    reglages = ReglagesRecherche(expurgateur=Expurgateur(locale.sujets_exclus))
    memoire = SourceMemoire(pool, EncodeurFastEmbed(p.dossier_modeles, p.modele_embeddings), reglages)
    service = ServiceDialogue(depot, moteurs, p.moteur_defaut, memoire, connecteurs, locale.sujets_prives)
    urgence = ArretUrgence()
    pc = construire_pc(pool, urgence, p.ollama_url, locale.pc, p.dossier_donnees)
    synthese = ServiceSynthese(pool, coffre, p.dossier_modeles, p.piper_commande, est_prive=service.est_prive)
    return Contexte(
        pool,
        depot,
        moteurs,
        service,
        p.moteur_defaut,
        memoire,
        connecteurs=connecteurs,
        mcp=GestionnaireMCP.depuis_config(locale.serveurs_mcp),
        skills=ServiceSkills(pool, p.dossier_donnees / "skills"),
        maison=GestionnaireMaison(pool, coffre),
        pc=pc,
        recherche=RechercheWeb(locale.searxng),
        scientifique=SourcesScientifiques() if locale.scientifique else None,
        dossier_recettes=chemin_config().parent / "recettes",
        dossier_donnees=p.dossier_donnees,
        ateliers=GestionnaireAteliers(
            pool,
            [Projet.depuis_config(b) for b in locale.projets_ateliers],
            p.dossier_donnees / "ateliers",
            f"http://127.0.0.1:{p.port}",
            urgence,
            [p.claude_commande] if p.claude_commande else None,
            image_bac=locale.image_bac_a_sable,
        ),
        veille=VeilleClaudeCode(
            pool,
            SourceFichiersEtat(locale.dossier_veille_claude or dossier_par_defaut()),
            reglages.expurgateur.mentionne,
            [p.dossier_donnees / "ateliers"],
        ),
        urgence=urgence,
        synthese=synthese,
        transcripteur=TranscripteurRobuste(p.dossier_modeles, p.modele_voix, p.voix_appareil),
        dossier_modeles=p.dossier_modeles,
        modele_fin_tour=p.modele_fin_tour,
        url_ollama=p.ollama_url,
        modele_vision=locale.connecteur("ollama").get("modele_vision"),
        ocr=choisir_ocr(),
        sans_ecran=p.sans_ecran,
        matin_locale=locale.matin,
    )


async def preparer_bascule(ctx: Contexte, p: Parametres) -> asyncio.Task[None] | None:
    """Modèle d'embeddings changé (JARVIS2_MODELE_EMBEDDINGS) : la recherche garde l'ancien modèle tant que tous
    les souvenirs n'ont pas leur vecteur du nouveau, calculés en tâche de fond ; puis elle bascule seule."""
    if ctx.memoire is None:
        return None
    voulu = ctx.memoire.encodeur
    existant = await modele_majoritaire(ctx.pool)
    actif = await modele_actif(ctx.pool, existant or voulu.nom_modele)
    ctx.etat_bascule = EtatBascule(actif)
    if actif == voulu.nom_modele:
        return None
    memoire_source = ctx.memoire
    memoire_source.encodeur = EncodeurFastEmbed(p.dossier_modeles, actif)
    journal.info("Mémoire : bascule %s → %s en tâche de fond", actif, voulu.nom_modele)

    async def bascule() -> None:
        assert ctx.etat_bascule is not None
        await basculer(ctx.pool, voulu, ctx.etat_bascule)
        if ctx.etat_bascule.actif == voulu.nom_modele:
            memoire_source.encodeur = voulu

    return asyncio.create_task(bascule())


async def decrire_moteur(moteur: MoteurInstrumente) -> dict[str, Any]:
    sante, modeles = await asyncio.gather(moteur.health(), moteur.list_models())
    return {
        "id": moteur.interne.id,
        "nom": moteur.interne.nom,
        "externe": moteur.interne.externe,
        "disponible": sante.disponible,
        "detail": sante.detail,
        "modeles": [{"id": m.id, "nom": m.nom, "defaut": m.defaut} for m in modeles],
        "efforts": list(moteur.interne.efforts),
        "vision": moteur.interne.vision,
        "effort_defaut": getattr(moteur.interne, "effort", None),
    }


async def precharger_modele(ctx: Contexte) -> None:
    """Charge le modèle d'embeddings s'il est sur le disque ; ne le télécharge jamais (accord de l'utilisateur)."""
    if ctx.memoire is None:
        return
    encodeur = ctx.memoire.encodeur
    if isinstance(encodeur, EncodeurFastEmbed) and not await asyncio.to_thread(encodeur.present):
        ctx.chargement_modele = "absent"
        journal.info("Modèle d'embeddings %s non téléchargé : à accepter dans le diagnostic", encodeur.nom_modele)
        return
    ctx.chargement_modele = "en_cours"
    try:
        await ctx.memoire.encodeur.encoder("préchargement")
    except Exception:  # réseau absent, disque plein… : la mémoire le signalera, le Core reste utilisable
        journal.exception("Modèle d'embeddings indisponible")
        ctx.chargement_modele = "erreur"
    else:
        ctx.chargement_modele = "termine"


async def detecter_tailscale(ctx: Contexte, port: int, autorisees: set[str]) -> None:
    """Adresse Tailscale du PC : origine autorisée (le téléphone y ouvre l'interface) et adresse du QR."""
    ctx.tailscale = await lire_tailscale(port)
    if ctx.tailscale.adresse:
        autorisees.add(ctx.tailscale.adresse)
        journal.info(
            "Tailscale : %s%s",
            ctx.tailscale.adresse,
            "" if ctx.tailscale.serve_actif else f" (Core non publié : {ctx.tailscale.commande_serve(port)})",
        )


def creer_app(parametres: Parametres, contexte: Contexte | None = None) -> FastAPI:
    @asynccontextmanager
    async def cycle_de_vie(app: FastAPI) -> AsyncIterator[None]:
        ctx = contexte or await construire_contexte(parametres)
        app.state.ctx = ctx
        await ctx.urgence.charger(ctx.pool)
        if ctx.connecteurs is not None:
            await ctx.connecteurs.charger()
        if ctx.maison is not None:
            await ctx.maison.charger()
        if ctx.pc is not None:
            await ctx.pc.charger()
        await ctx.wyoming.charger()
        if ctx.wyoming.reglages["actif"]:  # serveur Wyoming : seulement s'il a été activé par l'utilisateur
            try:
                await ctx.wyoming.appliquer()
            except Exception as exc:
                journal.warning("Wyoming : %s", exc)
        if ctx.urgence.actif:
            journal.warning("Arrêt d'urgence ACTIF (depuis %s) : écritures refusées", ctx.urgence.depuis)
        app.state.parametres = parametres
        taches: list[asyncio.Task[Any]] = []
        if ctx.memoire is not None:  # modèle d'embeddings chargé en tâche de fond : le 1er message n'attend pas
            taches.append(asyncio.create_task(precharger_modele(ctx)))
        taches.append(asyncio.create_task(detecter_tailscale(ctx, parametres.port, autorisees)))
        if ctx.veille is not None:  # veille des sessions Claude Code : ne lit rien tant qu'elle est désactivée
            taches.append(asyncio.create_task(ctx.veille.boucle()))
        if ctx.push.disponible:  # rappels des demandes reportées (« plus tard »)
            taches.append(asyncio.create_task(ctx.push.boucle(ctx.approbations)))
        if ctx.planificateur is not None:  # recettes planifiées et tâches de nuit de la mémoire
            taches.append(asyncio.create_task(ctx.planificateur.boucle()))
        if ctx.pc is not None:  # mesures (seulement si la vue est ouverte), Ollama inactif, détection des jeux
            taches.extend(asyncio.create_task(b) for b in ctx.pc.boucles())
        if contexte is None:
            bascule = await preparer_bascule(ctx, parametres)
            if bascule is not None:
                taches.append(bascule)
        journal.info("JARVIS 2 prêt — moteurs : %s", ", ".join(ctx.moteurs))
        if parametres.sans_ecran:
            ctx.sans_ecran = True
            journal.info("Mode sans écran : capture, clics et contrôle de l'écran désactivés")
        if parametres.ouvrir_navigateur and not ctx.sans_ecran:
            adresse = f"http://localhost:{parametres.port}/"
            journal.info("Ouverture de %s dans le navigateur", adresse)
            asyncio.get_running_loop().run_in_executor(None, webbrowser.open, adresse)
        try:
            yield
        finally:
            ctx.telechargeur.arreter()  # fichiers partiels gardés : reprise au prochain accord
            if ctx.pc is not None and contexte is None:  # l'Ollama démarré par JARVIS s'arrête avec lui
                await ctx.pc.ollama.fermer()
            await ctx.eveil.fermer()
            await ctx.wyoming.arreter()
            for tache in taches:
                if not tache.done():
                    tache.cancel()
            if contexte is None:
                for m in ctx.moteurs.values():
                    await m.fermer()
                if ctx.mcp is not None:
                    await ctx.mcp.fermer()
                await ctx.ameliorations.fermer()
                if ctx.ateliers is not None:
                    await ctx.ateliers.fermer()
                await ctx.pool.close()

    app = FastAPI(title="JARVIS 2", version=__version__, lifespan=cycle_de_vie, docs_url=None, redoc_url=None)
    autorisees = origines_autorisees(parametres)
    app.state.origines = autorisees  # complété par l'adresse Tailscale une fois détectée
    app.state.parametres = parametres

    @app.middleware("http")
    async def garde(request: Request, suite: Callable[[Request], Awaitable[Response]]) -> Response:
        origine = request.headers.get("origin")
        if origine and origine not in autorisees:
            journal.warning("Origine refusée : %s", origine[:100])
            return JSONResponse({"detail": "Origine non autorisée"}, status_code=403)
        chemin = request.url.path
        if chemin.startswith("/v1/") and chemin not in CHEMINS_PUBLICS:
            c: Contexte = request.app.state.ctx
            entete = request.headers.get("authorization", "")
            jeton = entete[7:].strip() if entete.lower().startswith("bearer ") else ""
            appareil = await appareils.authentifier(c.pool, jeton) if jeton else None
            if appareil is None:
                return JSONResponse(
                    {"detail": "Appareil non autorisé : jumelez cet appareil"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
            request.state.appareil = appareil
            ecriture = request.method not in ("GET", "HEAD", "OPTIONS")
            if c.urgence.actif and ecriture and not chemin.startswith(ECRITURES_EN_URGENCE):
                return JSONResponse(
                    {
                        "detail": "Arrêt d'urgence actif : aucune écriture n'est acceptée",
                        "urgence": c.urgence.en_dict(),
                    },
                    status_code=423,
                )
        reponse = await suite(request)
        if not request.url.path.startswith(("/v1/", "/creations/")):  # une création porte sa propre CSP (bac à sable)
            reponse.headers["Content-Security-Policy"] = CSP
            reponse.headers["X-Content-Type-Options"] = "nosniff"
            reponse.headers["Referrer-Policy"] = "no-referrer"
            # Fichiers compilés à empreinte : immuables. Le reste (index.html, sw.js, manifeste) : revalidé à
            # chaque fois, sinon le navigateur garde l'ancienne interface après une mise à jour de JARVIS.
            if chemin.startswith("/assets/"):
                reponse.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                reponse.headers.setdefault("Cache-Control", "no-cache")
        return reponse

    def ctx(request: Request) -> Contexte:
        c: Contexte = request.app.state.ctx
        return c

    @app.get("/v1/sante")
    async def sante(request: Request) -> dict[str, Any]:
        try:
            schema = await version_schema(ctx(request).pool)
            base = True
        except ErreurBaseOuReseau:
            schema, base = None, False
        # `sans_ecran` : lu par `jarvis2 docteur` (le mode peut venir de l'option de lancement, pas de .env)
        return {
            "ok": base,
            "version": __version__,
            "base": base,
            "schema": schema,
            "sans_ecran": ctx(request).sans_ecran,
        }

    @app.get("/v1/etat")
    async def etat(request: Request) -> dict[str, Any]:
        c = ctx(request)

        async def connecteurs_actifs() -> list[dict[str, Any]]:
            if c.connecteurs is None:
                return list(await asyncio.gather(*(decrire_moteur(m) for m in c.moteurs.values())))
            return [carte for carte in await c.connecteurs.decrire(tous=False) if carte["disponible"]]

        async def widgets_epingles() -> list[dict[str, Any]]:
            try:
                return await widgets.lister(c.pool)
            except Exception:  # base pas encore migrée : le HUD démarre sans widget
                return []

        moteurs, conversations, comptes, demandes, nb_cles, epingles = await asyncio.gather(
            connecteurs_actifs(),
            c.depot.lister(limite=50),
            memoire.compter(c.pool),
            c.approbations.lister("en_attente"),
            c.pool.fetchval("SELECT count(*) FROM cles_acces"),
            widgets_epingles(),
        )
        return {
            "appareil": request.state.appareil.en_dict(),
            "urgence": c.urgence.en_dict(),
            "demandes": [d.en_dict() for d in demandes],
            "cles_acces": nb_cles,
            "version": __version__,
            "sans_ecran": c.sans_ecran,
            "moteur_defaut": c.moteur_defaut,
            "moteurs": moteurs,
            "conversations": [conv.en_dict() for conv in conversations],
            "memoire": comptes,
            "widgets": epingles,  # phase 14, D 16 : épinglés dans le HUD (un seul appel au démarrage)
        }

    @app.get("/v1/memoire/recherche")
    async def recherche_memoire(request: Request, q: str, limite: int = 10, local: bool = False) -> dict[str, Any]:
        """Recherche hybride telle que le dialogue la fait. `local=true` inclut les souvenirs privés."""
        c = ctx(request)
        if c.memoire is None:
            raise HTTPException(503, "Mémoire indisponible")
        if not q.strip():
            raise HTTPException(422, "Requête vide")
        reglages = replace(c.memoire.reglages, limite=max(1, min(limite, 50)))
        resultats = await memoire.rechercher_multi(
            c.pool, c.memoire.encodeur, q, exclure_local=not local, reglages=reglages
        )
        return {"resultats": [{"score": r.score, **r.souvenir.en_dict()} for r in resultats]}

    @app.get("/v1/conversations")
    async def conversations(request: Request, limite: int = 50, archivees: bool = False, q: str = "") -> dict[str, Any]:
        depot = ctx(request).depot
        limite = max(1, min(limite, 200))
        texte = q.strip()[:200]
        liste = (
            await depot.chercher(texte, archivees=archivees, limite=limite)
            if texte
            else await depot.lister(limite=limite, archivees=archivees)
        )
        return {"conversations": [c.en_dict() for c in liste]}

    @app.patch("/v1/conversations/{conversation_id}")
    async def modifier_conversation(
        request: Request, conversation_id: UUID, corps: ModificationConversation
    ) -> dict[str, Any]:
        """Renommer, épingler, restaurer (🟢 : rien ne se perd). Archiver passe par une demande (🟡)."""
        if corps.archivee:
            raise HTTPException(422, "Archiver passe par une demande (action conversation.archiver)")
        titre = " ".join(corps.titre.split()) if corps.titre is not None else None
        if titre == "":
            raise HTTPException(422, "Titre vide")
        conv = await ctx(request).depot.modifier(
            conversation_id, titre=titre, epinglee=corps.epinglee, archivee=corps.archivee
        )
        if conv is None:
            raise HTTPException(404, "Conversation introuvable")
        return {"conversation": conv.en_dict()}

    @app.get("/v1/conversations/{conversation_id}")
    async def conversation(request: Request, conversation_id: UUID) -> dict[str, Any]:
        depot = ctx(request).depot
        conv = await depot.obtenir(conversation_id)
        if conv is None:
            raise HTTPException(404, "Conversation introuvable")
        messages = await depot.messages(conversation_id)
        return {"conversation": conv.en_dict(), "messages": [m.en_dict() for m in messages]}

    @app.post("/v1/conversations/{conversation_id}/resumer")
    async def resumer(request: Request, conversation_id: UUID) -> dict[str, Any]:
        """Résumé daté de la conversation en mémoire, tout de suite (sinon chaque nuit à 3 h 15)."""
        from .titrage import resumer_conversation

        c = ctx(request)
        try:
            return await resumer_conversation(c.pool, c.service, conversation_id)
        except LookupError as exc:
            raise HTTPException(404 if "introuvable" in str(exc) else 409, str(exc)) from exc
        except ErreurMoteur as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.post("/v1/dialogue")
    async def dialogue(request: Request, demande: DemandeDialogue) -> StreamingResponse:
        c = ctx(request)
        if demande.moteur not in (None, "auto") and demande.moteur not in c.moteurs:
            raise HTTPException(422, f"Connecteur inconnu : « {demande.moteur} »")
        if demande.conversation_id and await c.depot.obtenir(demande.conversation_id) is None:
            raise HTTPException(404, "Conversation introuvable")
        options = Options(modele=demande.modele or None, effort=demande.effort or None)
        try:
            images = [vision.decoder_jointe(i) for i in demande.images]
        except vision.ErreurVision as exc:
            raise HTTPException(422, str(exc)) from exc
        if not demande.message.strip() and not images:
            raise HTTPException(422, "Message vide")

        async def flux() -> AsyncIterator[bytes]:
            with c.urgence.suivre():  # l'arrêt d'urgence annule cette réponse (et tue la CLI) immédiatement
                try:
                    async for ev in c.service.repondre(
                        demande.message, demande.conversation_id, demande.moteur, options, images
                    ):
                        yield sse(ev.type, ev.donnees)
                except AccordImagesRequis as exc:  # rien n'est parti : l'interface demande l'accord puis renvoie
                    yield sse("accord_images", exc.en_dict())
                except (ErreurMoteur, ValueError, LookupError) as exc:
                    yield sse("erreur", {"message": str(exc)})

        return StreamingResponse(
            flux(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    app.include_router(routeur_bureau)  # avant la sécurité : /v1/demandes/{id} (GET) et …/reporter
    app.include_router(routeur_securite)
    app.include_router(routeur_fichiers_uniques)  # /f/{code} : avant l'interface montée sur « / »
    app.include_router(routeur_connecteurs)
    app.include_router(routeur_maison)
    app.include_router(routeur_accueil)
    app.include_router(routeur_agents)
    app.include_router(routeur_ateliers)
    app.include_router(routeur_ameliorations)
    app.include_router(routeur_medias)
    app.include_router(routeur_creations)
    app.include_router(routeur_memoire)
    app.include_router(routeur_chantiers)
    app.include_router(routeur_profil)
    app.include_router(routeur_connaissances)
    app.include_router(routeur_matin)
    app.include_router(routeur_telechargements)
    app.include_router(routeur_synthese)
    app.include_router(routeur_transcription)
    app.include_router(routeur_donnees)
    app.include_router(routeur_pilotage)
    app.include_router(routeur_widgets)
    app.include_router(routeur_pc)
    app.include_router(routeur_eveil)
    app.include_router(routeur_routage)
    app.include_router(routeur_skills)

    dossier = parametres.dossier_interface
    if (dossier / "index.html").is_file():
        app.mount("/", StaticFiles(directory=dossier, html=True), name="interface")
    else:  # paquet construit sans interface (ou dépôt non compilé) : l'expliquer plutôt qu'un 404 muet

        @app.get("/", include_in_schema=False)
        async def interface_absente() -> HTMLResponse:
            return HTMLResponse(PAGE_INTERFACE_ABSENTE.format(dossier=html.escape(str(dossier))), status_code=503)

    return app


PAGE_INTERFACE_ABSENTE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>JARVIS 2 — interface absente</title></head>
<body><h1>JARVIS 2 fonctionne, mais son interface n'est pas installée</h1>
<p>Interface compilée introuvable : <code>{dossier}</code></p>
<ul>
<li>Installez la roue jointe à une version publiée (elle contient l'interface) :
<code>pipx install --python 3.13 jarvis2-x.y.z-py3-none-any.whl</code></li>
<li>Depuis le dépôt : <code>cd interface ; npm install ; npm run build</code>, puis réinstallez
(<code>pipx install --force --python 3.13 ./core</code>) ou relancez le Core.</li>
</ul>
<p>Diagnostic complet : <code>jarvis2 docteur</code>.</p>
</body></html>
"""
