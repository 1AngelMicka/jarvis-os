"""API HTTP du Core (FastAPI).

- `GET  /v1/sante`                    : vivant + base joignable
- `GET  /v1/etat`                     : amorçage de l'interface en UN appel (moteurs, modèles, conversations)
- `GET  /v1/conversations`            : liste
- `GET  /v1/conversations/{id}`       : conversation + messages
- `POST /v1/dialogue`                 : message -> réponse en flux SSE (`debut`, `delta`, `fin`, `erreur`)

Le Core n'écoute que sur 127.0.0.1 tant que l'authentification n'existe pas (phase 4). Les requêtes d'une
origine inconnue sont refusées (protection contre une page web malveillante qui viserait 127.0.0.1).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, memoire
from .config import Parametres
from .conversations import DepotConversations
from .db import creer_pool, version_schema
from .dialogue import ServiceDialogue, SourceMemoire
from .embeddings import EncodeurFastEmbed
from .moteurs import construire_moteurs
from .moteurs.base import ErreurMoteur, Options
from .moteurs.telemetrie import EnregistreurPostgres, MoteurInstrumente

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


class DemandeDialogue(BaseModel):
    message: str = Field(min_length=1, max_length=100_000)
    conversation_id: UUID | None = None
    moteur: str | None = None
    modele: str | None = Field(default=None, max_length=200)
    effort: str | None = Field(default=None, max_length=20)


def origines_autorisees(p: Parametres) -> set[str]:
    hotes = {"127.0.0.1", "localhost"}
    ports = {p.port, 5174, 4174}
    return {f"http://{h}:{port}" for h in hotes for port in ports}


def sse(evenement: str, donnees: dict[str, Any]) -> bytes:
    return f"event: {evenement}\ndata: {json.dumps(donnees, ensure_ascii=False)}\n\n".encode()


async def construire_contexte(p: Parametres) -> Contexte:
    pool = await creer_pool(p.url_base("app"))
    depot = DepotConversations(pool)
    moteurs = construire_moteurs(p, EnregistreurPostgres(pool))
    memoire = SourceMemoire(pool, EncodeurFastEmbed(p.dossier_modeles))
    service = ServiceDialogue(depot, moteurs, p.moteur_defaut, memoire)
    return Contexte(pool, depot, moteurs, service, p.moteur_defaut, memoire)


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
    async def verifier_origine(request: Request, suite: Callable[[Request], Awaitable[Response]]) -> Response:
        origine = request.headers.get("origin")
        if origine and origine not in autorisees:
            journal.warning("Origine refusée : %s", origine[:100])
            return JSONResponse({"detail": "Origine non autorisée"}, status_code=403)
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
        moteurs, conversations, comptes = await asyncio.gather(
            asyncio.gather(*(decrire_moteur(m) for m in c.moteurs.values())),
            c.depot.lister(limite=50),
            memoire.compter(c.pool),
        )
        return {
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
        if (demande.moteur or c.moteur_defaut) not in c.moteurs:
            raise HTTPException(422, f"Moteur inconnu : « {demande.moteur} »")
        if demande.conversation_id and await c.depot.obtenir(demande.conversation_id) is None:
            raise HTTPException(404, "Conversation introuvable")
        options = Options(modele=demande.modele or None, effort=demande.effort or None)

        async def flux() -> AsyncIterator[bytes]:
            try:
                async for ev in c.service.repondre(demande.message, demande.conversation_id, demande.moteur, options):
                    yield sse(ev.type, ev.donnees)
            except (ErreurMoteur, ValueError, LookupError) as exc:
                yield sse("erreur", {"message": str(exc)})

        return StreamingResponse(
            flux(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    dossier = parametres.dossier_interface
    if dossier.is_dir():
        app.mount("/", StaticFiles(directory=dossier, html=True), name="interface")
    return app
