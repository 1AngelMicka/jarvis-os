"""API HTTP du Core (FastAPI).

- `GET  /v1/sante`                    : vivant + base joignable
- `GET  /v1/etat`                     : amorçage de l'interface en UN appel (moteurs, modèles, conversations)
- `GET  /v1/conversations`            : liste
- `GET  /v1/conversations/{id}`       : conversation + messages
- `POST /v1/dialogue`                 : message -> réponse en flux SSE (`debut`, `delta`, `fin`, `erreur`)
- sécurité (appareils, jumelage, clés d'accès, demandes, arrêt d'urgence, audit) : voir api_securite.py

Chaque requête `/v1/` exige le jeton d'un appareil autorisé (`Authorization: Bearer`), sauf la santé et le
jumelage. Une origine inconnue est refusée (page web malveillante qui viserait le Core). Pendant l'arrêt
d'urgence, toute écriture est refusée (HTTP 423) sauf ce qui sert à le lever. Le Core écoute sur 127.0.0.1 par
défaut ; l'ouvrir au réseau est un choix explicite (JARVIS2_OUVERTURE_RESEAU).
"""

from __future__ import annotations

import asyncio
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
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, memoire
from .agents.mcp import GestionnaireMCP
from .agents.missions import ServiceMissions
from .agents.recettes import Planificateur
from .agents.recherche_web import RechercheWeb
from .api_accueil import routeur as routeur_accueil
from .api_agents import routeur as routeur_agents
from .api_ateliers import routeur as routeur_ateliers
from .api_chantiers import routeur as routeur_chantiers
from .api_connecteurs import routeur as routeur_connecteurs
from .api_medias import routeur as routeur_medias
from .api_medias import routeur_pages as routeur_creations
from .api_memoire import routeur as routeur_memoire
from .api_profil import routeur as routeur_profil
from .api_securite import routeur as routeur_securite
from .ateliers.gestionnaire import GestionnaireAteliers, Projet
from .config import Parametres
from .config_locale import charger as charger_config_locale
from .config_locale import chemin_config
from .connecteurs import Connecteurs, construire_catalogue
from .conseil import ServiceConseil
from .conversations import DepotConversations
from .db import Base, ErreurBaseOuReseau, ouvrir_base, version_schema
from .dialogue import ServiceDialogue, SourceMemoire
from .embeddings import EncodeurFastEmbed
from .memoire import Expurgateur, ReglagesRecherche
from .memoire_v2 import EtatBascule, basculer, modele_actif, modele_majoritaire
from .moteurs.base import ErreurMoteur, Options
from .moteurs.telemetrie import EnregistreurBase, MoteurInstrumente
from .nuit import taches_memoire
from .securite import appareils
from .securite.actions import creer_registre
from .securite.coffre import Coffre
from .securite.permissions import Approbations
from .securite.urgence import ArretUrgence
from .tailscale import EtatTailscale
from .tailscale import lire_etat as lire_tailscale
from .voix import Transcripteur, TranscripteurWhisper

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
    connecteurs: Connecteurs | None = None
    tailscale: EtatTailscale | None = None
    chargement_modele: str | None = None  # None, « en_cours », « termine », « erreur »
    mcp: GestionnaireMCP | None = None
    recherche: RechercheWeb = field(default_factory=lambda: RechercheWeb(None))
    dossier_recettes: Path | None = None
    dossier_donnees: Path | None = None  # tâches de nuit de la mémoire (export Markdown dans memoire-md/)
    etat_bascule: EtatBascule | None = None
    ateliers: GestionnaireAteliers | None = None
    transcripteur: Transcripteur | None = None
    url_ollama: str = "http://127.0.0.1:11434"
    modele_vision: str | None = None
    approbations: Approbations = field(init=False)
    conseil: ServiceConseil = field(init=False)
    missions: ServiceMissions = field(init=False)
    planificateur: Planificateur | None = field(init=False)

    def __post_init__(self) -> None:
        self.approbations = Approbations(self.pool, creer_registre(self.urgence, self.mcp, self.ateliers))
        self.conseil = ServiceConseil(self.service)
        self.missions = ServiceMissions(self.pool, self.service, self.recherche, self.urgence)
        taches = (
            taches_memoire(self.pool, self.service, self.dossier_donnees / "memoire-md")
            if self.dossier_donnees is not None and self.memoire is not None
            else []
        )
        self.planificateur = (
            Planificateur(self.pool, self.service, self.dossier_recettes, self.urgence, taches=taches)
            if self.dossier_recettes is not None
            else None
        )


class ModificationConversation(BaseModel):
    titre: str | None = Field(None, max_length=120)
    epinglee: bool | None = None
    archivee: bool | None = None


class DemandeDialogue(BaseModel):
    message: str = Field(min_length=1, max_length=100_000)
    conversation_id: UUID | None = None
    moteur: str | None = None
    modele: str | None = Field(default=None, max_length=200)
    effort: str | None = Field(default=None, max_length=20)


# Sans jeton : santé, état du jumelage, premier appareil (PC seulement), échange d'un code de jumelage
CHEMINS_PUBLICS = frozenset(
    {"/v1/sante", "/v1/auth/etat", "/v1/appareils/premier", "/v1/jumelage/echanger", "/v1/ateliers-autorisation"}
)  # autorisation des ateliers : jeton propre à chaque exécution, PC seulement
# Écritures permises pendant l'arrêt d'urgence : ce qui sert à le lever ou à retirer un accès
ECRITURES_EN_URGENCE = ("/v1/urgence/", "/v1/demandes/", "/v1/cles/", "/v1/appareils/")


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
    return Contexte(
        pool,
        depot,
        moteurs,
        service,
        p.moteur_defaut,
        memoire,
        connecteurs=connecteurs,
        mcp=GestionnaireMCP.depuis_config(locale.serveurs_mcp),
        recherche=RechercheWeb(locale.searxng),
        dossier_recettes=chemin_config().parent / "recettes",
        dossier_donnees=p.dossier_donnees,
        ateliers=GestionnaireAteliers(
            pool,
            [Projet.depuis_config(b) for b in locale.projets_ateliers],
            p.dossier_donnees / "ateliers",
            f"http://127.0.0.1:{p.port}",
            urgence,
            [p.claude_commande] if p.claude_commande else None,
        ),
        urgence=urgence,
        transcripteur=TranscripteurWhisper(p.dossier_modeles, p.modele_voix),
        url_ollama=p.ollama_url,
        modele_vision=locale.connecteur("ollama").get("modele_vision"),
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
        "effort_defaut": getattr(moteur.interne, "effort", None),
    }


async def precharger_modele(ctx: Contexte) -> None:
    """Télécharge (première fois) puis charge le modèle d'embeddings ; l'état est montré par le diagnostic."""
    if ctx.memoire is None:
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
        if ctx.urgence.actif:
            journal.warning("Arrêt d'urgence ACTIF (depuis %s) : écritures refusées", ctx.urgence.depuis)
        app.state.parametres = parametres
        taches: list[asyncio.Task[Any]] = []
        if ctx.memoire is not None:  # modèle d'embeddings chargé en tâche de fond : le 1er message n'attend pas
            taches.append(asyncio.create_task(precharger_modele(ctx)))
        taches.append(asyncio.create_task(detecter_tailscale(ctx, parametres.port, autorisees)))
        if ctx.planificateur is not None:  # recettes planifiées et tâches de nuit de la mémoire
            taches.append(asyncio.create_task(ctx.planificateur.boucle()))
        if contexte is None:
            bascule = await preparer_bascule(ctx, parametres)
            if bascule is not None:
                taches.append(bascule)
        journal.info("JARVIS 2 prêt — moteurs : %s", ", ".join(ctx.moteurs))
        if parametres.ouvrir_navigateur:
            adresse = f"http://localhost:{parametres.port}/"
            journal.info("Ouverture de %s dans le navigateur", adresse)
            asyncio.get_running_loop().run_in_executor(None, webbrowser.open, adresse)
        try:
            yield
        finally:
            for tache in taches:
                if not tache.done():
                    tache.cancel()
            if contexte is None:
                for m in ctx.moteurs.values():
                    await m.fermer()
                if ctx.mcp is not None:
                    await ctx.mcp.fermer()
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
        return {"ok": base, "version": __version__, "base": base, "schema": schema}

    @app.get("/v1/etat")
    async def etat(request: Request) -> dict[str, Any]:
        c = ctx(request)

        async def connecteurs_actifs() -> list[dict[str, Any]]:
            if c.connecteurs is None:
                return list(await asyncio.gather(*(decrire_moteur(m) for m in c.moteurs.values())))
            return [carte for carte in await c.connecteurs.decrire(tous=False) if carte["disponible"]]

        moteurs, conversations, comptes, demandes, nb_cles = await asyncio.gather(
            connecteurs_actifs(),
            c.depot.lister(limite=50),
            memoire.compter(c.pool),
            c.approbations.lister("en_attente"),
            c.pool.fetchval("SELECT count(*) FROM cles_acces"),
        )
        return {
            "appareil": request.state.appareil.en_dict(),
            "urgence": c.urgence.en_dict(),
            "demandes": [d.en_dict() for d in demandes],
            "cles_acces": nb_cles,
            "version": __version__,
            "moteur_defaut": c.moteur_defaut,
            "moteurs": moteurs,
            "conversations": [conv.en_dict() for conv in conversations],
            "memoire": comptes,
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

        async def flux() -> AsyncIterator[bytes]:
            with c.urgence.suivre():  # l'arrêt d'urgence annule cette réponse (et tue la CLI) immédiatement
                try:
                    async for ev in c.service.repondre(
                        demande.message, demande.conversation_id, demande.moteur, options
                    ):
                        yield sse(ev.type, ev.donnees)
                except (ErreurMoteur, ValueError, LookupError) as exc:
                    yield sse("erreur", {"message": str(exc)})

        return StreamingResponse(
            flux(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    app.include_router(routeur_securite)
    app.include_router(routeur_connecteurs)
    app.include_router(routeur_accueil)
    app.include_router(routeur_agents)
    app.include_router(routeur_ateliers)
    app.include_router(routeur_medias)
    app.include_router(routeur_creations)
    app.include_router(routeur_memoire)
    app.include_router(routeur_chantiers)
    app.include_router(routeur_profil)

    dossier = parametres.dossier_interface
    if dossier.is_dir():
        app.mount("/", StaticFiles(directory=dossier, html=True), name="interface")
    return app
