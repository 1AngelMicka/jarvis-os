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
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, memoire
from .api_connecteurs import routeur as routeur_connecteurs
from .api_securite import routeur as routeur_securite
from .config import Parametres
from .config_locale import charger as charger_config_locale
from .config_locale import chemin_config
from .connecteurs import Connecteurs, construire_catalogue
from .conseil import ServiceConseil
from .conversations import DepotConversations
from .db import creer_pool, version_schema
from .dialogue import ServiceDialogue, SourceMemoire
from .embeddings import EncodeurFastEmbed
from .memoire import Expurgateur, ReglagesRecherche
from .moteurs.base import ErreurMoteur, Options
from .moteurs.telemetrie import EnregistreurPostgres, MoteurInstrumente
from .securite import appareils
from .securite.actions import creer_registre
from .securite.coffre import Coffre
from .securite.permissions import Approbations
from .securite.urgence import ArretUrgence

journal = logging.getLogger("jarvis2.api")

# Interface compilée : aucun script en ligne, aucune ressource externe.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


@dataclass
class Contexte:
    pool: asyncpg.Pool
    depot: DepotConversations
    moteurs: dict[str, MoteurInstrumente]
    service: ServiceDialogue
    moteur_defaut: str
    memoire: SourceMemoire | None = None
    urgence: ArretUrgence = field(default_factory=ArretUrgence)
    connecteurs: Connecteurs | None = None
    approbations: Approbations = field(init=False)
    conseil: ServiceConseil = field(init=False)

    def __post_init__(self) -> None:
        self.approbations = Approbations(self.pool, creer_registre(self.urgence))
        self.conseil = ServiceConseil(self.service)


class DemandeDialogue(BaseModel):
    message: str = Field(min_length=1, max_length=100_000)
    conversation_id: UUID | None = None
    moteur: str | None = None
    modele: str | None = Field(default=None, max_length=200)
    effort: str | None = Field(default=None, max_length=20)


# Sans jeton : santé, état du jumelage, premier appareil (PC seulement), échange d'un code de jumelage
CHEMINS_PUBLICS = frozenset({"/v1/sante", "/v1/auth/etat", "/v1/appareils/premier", "/v1/jumelage/echanger"})
# Écritures permises pendant l'arrêt d'urgence : ce qui sert à le lever ou à retirer un accès
ECRITURES_EN_URGENCE = ("/v1/urgence/", "/v1/demandes/", "/v1/cles/", "/v1/appareils/")


def origines_autorisees(p: Parametres) -> set[str]:
    hotes = {"127.0.0.1", "localhost"}
    ports = {p.port, 5174, 4174}
    return {f"http://{h}:{port}" for h in hotes for port in ports} | set(p.origines_supplementaires)


def sse(evenement: str, donnees: dict[str, Any]) -> bytes:
    return f"event: {evenement}\ndata: {json.dumps(donnees, ensure_ascii=False)}\n\n".encode()


async def construire_contexte(p: Parametres) -> Contexte:
    pool = await creer_pool(p.url_base("app"))
    depot = DepotConversations(pool)
    locale = charger_config_locale()
    coffre = Coffre(chemin_config().parent / "coffre.json")
    connecteurs = Connecteurs(
        pool, construire_catalogue(p, locale, coffre, EnregistreurPostgres(pool)), coffre, prefere=p.moteur_defaut
    )
    moteurs = connecteurs.moteurs
    reglages = ReglagesRecherche(expurgateur=Expurgateur(locale.sujets_exclus))
    memoire = SourceMemoire(pool, EncodeurFastEmbed(p.dossier_modeles, p.modele_embeddings), reglages)
    service = ServiceDialogue(depot, moteurs, p.moteur_defaut, memoire, connecteurs)
    return Contexte(pool, depot, moteurs, service, p.moteur_defaut, memoire, connecteurs=connecteurs)


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
        prechargement = None
        if ctx.memoire is not None:  # modèle d'embeddings chargé en tâche de fond : le 1er message n'attend pas
            prechargement = asyncio.create_task(ctx.memoire.encodeur.encoder("préchargement"))
        journal.info("JARVIS 2 prêt — moteurs : %s", ", ".join(ctx.moteurs))
        try:
            yield
        finally:
            if prechargement is not None and not prechargement.done():
                prechargement.cancel()
            if contexte is None:
                for m in ctx.moteurs.values():
                    await m.fermer()
                await ctx.pool.close()

    app = FastAPI(title="JARVIS 2", version=__version__, lifespan=cycle_de_vie, docs_url=None, redoc_url=None)
    autorisees = origines_autorisees(parametres)

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
        if not request.url.path.startswith("/v1/"):
            reponse.headers["Content-Security-Policy"] = CSP
            reponse.headers["X-Content-Type-Options"] = "nosniff"
            reponse.headers["Referrer-Policy"] = "no-referrer"
        return reponse

    def ctx(request: Request) -> Contexte:
        c: Contexte = request.app.state.ctx
        return c

    @app.get("/v1/sante")
    async def sante(request: Request) -> dict[str, Any]:
        try:
            schema = await version_schema(ctx(request).pool)
            base = True
        except (asyncpg.PostgresError, OSError):
            schema, base = None, False
        return {"ok": base, "version": __version__, "base": base, "schema": schema}

    @app.get("/v1/etat")
    async def etat(request: Request) -> dict[str, Any]:
        c = ctx(request)

        async def connecteurs_actifs() -> list[dict[str, Any]]:
            if c.connecteurs is None:
                return list(await asyncio.gather(*(decrire_moteur(m) for m in c.moteurs.values())))
            return [carte for carte in await c.connecteurs.decrire() if carte["actif"] and carte["installe"]]

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
    async def conversations(request: Request, limite: int = 50, archivees: bool = False) -> dict[str, Any]:
        liste = await ctx(request).depot.lister(limite=max(1, min(limite, 200)), archivees=archivees)
        return {"conversations": [c.en_dict() for c in liste]}

    @app.get("/v1/conversations/{conversation_id}")
    async def conversation(request: Request, conversation_id: UUID) -> dict[str, Any]:
        depot = ctx(request).depot
        conv = await depot.obtenir(conversation_id)
        if conv is None:
            raise HTTPException(404, "Conversation introuvable")
        messages = await depot.messages(conversation_id)
        return {"conversation": conv.en_dict(), "messages": [m.en_dict() for m in messages]}

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

    dossier = parametres.dossier_interface
    if dossier.is_dir():
        app.mount("/", StaticFiles(directory=dossier, html=True), name="interface")
    return app
