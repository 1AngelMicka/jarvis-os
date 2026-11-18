"""Client MCP (Model Context Protocol, transport stdio : JSON-RPC 2.0, un message JSON par ligne).

Les serveurs sont déclarés par l'utilisateur dans sa configuration locale :

    [[mcp.serveurs]]
    id = "fichiers"
    commande = "npx"
    args = ["-y", "@modelcontextprotocol/server-filesystem", "C:/Documents/partage"]

Garde-fous : chaque outil est INACTIF tant que l'utilisateur ne l'a pas activé (table `outils_mcp`) ; tout appel
passe par la file d'approbations (🟡, action `mcp.appeler`) ; le résultat est une donnée, jamais une instruction ;
le serveur tourne sans les clés d'API de l'environnement (seules ses variables `env` déclarées lui sont données).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ..db import Executant
from ..moteurs.sousprocessus import environnement

journal = logging.getLogger("jarvis2.mcp")

VERSION_PROTOCOLE = "2025-06-18"
IDENT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


class ErreurMCP(RuntimeError):
    pass


@dataclass
class ServeurMCP:
    id: str
    commande: list[str]
    env: dict[str, str] = field(default_factory=dict)
    delai: float = 30.0

    @classmethod
    def depuis_config(cls, bloc: dict[str, Any]) -> ServeurMCP:
        ident = str(bloc["id"])
        if not IDENT.match(ident):
            raise ValueError(f"mcp.serveurs : identifiant invalide « {ident} »")
        commande = bloc["commande"]
        args = bloc.get("args") or []
        liste = [commande] if isinstance(commande, str) else list(commande)
        return cls(
            ident, [str(x) for x in [*liste, *args]], {str(k): str(v) for k, v in (bloc.get("env") or {}).items()}
        )


class ClientMCP:
    """Une session avec un serveur MCP : processus lancé à la demande, requêtes numérotées."""

    def __init__(self, serveur: ServeurMCP) -> None:
        self.serveur = serveur
        self._proc: asyncio.subprocess.Process | None = None
        self._lecteur: asyncio.Task[None] | None = None
        self._attentes: dict[int, asyncio.Future[Any]] = {}
        self._compteur = 0
        self._verrou = asyncio.Lock()

    async def _demarrer(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            return
        env = {**environnement(), **self.serveur.env}
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self.serveur.commande,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=env,
                limit=8 * 1024 * 1024,
            )
        except OSError as exc:
            raise ErreurMCP(f"Serveur MCP « {self.serveur.id} » impossible à lancer : {exc}") from exc
        self._lecteur = asyncio.get_running_loop().create_task(self._lire())
        await self._requete(
            "initialize",
            {
                "protocolVersion": VERSION_PROTOCOLE,
                "capabilities": {},
                "clientInfo": {"name": "jarvis2", "version": "0.4"},
            },
        )
        await self._envoyer({"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def _lire(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            ligne = await self._proc.stdout.readline()
            if not ligne:
                break
            try:
                message = json.loads(ligne)
            except json.JSONDecodeError:
                continue  # le serveur écrit autre chose sur stdout : ignoré
            ident = message.get("id") if isinstance(message, dict) else None
            attente = self._attentes.pop(ident, None) if isinstance(ident, int) else None
            if attente is not None and not attente.done():
                if "error" in message:
                    erreur = message["error"]
                    attente.set_exception(ErreurMCP(str(erreur.get("message", erreur))))
                else:
                    attente.set_result(message.get("result"))
        for attente in self._attentes.values():
            if not attente.done():
                attente.set_exception(ErreurMCP(f"Le serveur MCP « {self.serveur.id} » s'est arrêté"))
        self._attentes.clear()

    async def _envoyer(self, message: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(message, ensure_ascii=False).encode() + b"\n")
        await self._proc.stdin.drain()

    async def _requete(self, methode: str, params: dict[str, Any]) -> Any:
        self._compteur += 1
        ident = self._compteur
        attente: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._attentes[ident] = attente
        await self._envoyer({"jsonrpc": "2.0", "id": ident, "method": methode, "params": params})
        try:
            return await asyncio.wait_for(attente, timeout=self.serveur.delai)
        except TimeoutError as exc:
            self._attentes.pop(ident, None)
            raise ErreurMCP(f"Le serveur MCP « {self.serveur.id} » ne répond pas ({methode})") from exc

    async def outils(self) -> list[dict[str, Any]]:
        async with self._verrou:
            await self._demarrer()
            resultat = await self._requete("tools/list", {})
        return list((resultat or {}).get("tools") or [])

    async def appeler(self, outil: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with self._verrou:
            await self._demarrer()
            resultat = await self._requete("tools/call", {"name": outil, "arguments": arguments})
        return dict(resultat or {})

    async def fermer(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._proc.kill()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._proc.wait(), timeout=5)
        if self._lecteur is not None:
            self._lecteur.cancel()


def texte_resultat(resultat: dict[str, Any], limite: int = 20_000) -> str:
    """Contenu texte d'un résultat d'outil (les autres types sont résumés)."""
    morceaux = []
    for c in resultat.get("content") or []:
        if isinstance(c, dict) and c.get("type") == "text":
            morceaux.append(str(c.get("text", "")))
        elif isinstance(c, dict):
            morceaux.append(f"[{c.get('type', 'contenu')} non textuel]")
    return "\n".join(morceaux)[:limite]


class GestionnaireMCP:
    def __init__(self, serveurs: Sequence[ServeurMCP]) -> None:
        self.serveurs = {s.id: s for s in serveurs}
        self.clients: dict[str, ClientMCP] = {}

    @classmethod
    def depuis_config(cls, blocs: Sequence[dict[str, Any]]) -> GestionnaireMCP:
        serveurs = []
        for b in blocs:
            try:
                serveurs.append(ServeurMCP.depuis_config(b))
            except (KeyError, ValueError) as exc:
                journal.warning("Serveur MCP ignoré : %s", exc)
        return cls(serveurs)

    def client(self, serveur: str) -> ClientMCP:
        if serveur not in self.serveurs:
            raise ErreurMCP(f"Serveur MCP inconnu : « {serveur} »")
        if serveur not in self.clients:
            self.clients[serveur] = ClientMCP(self.serveurs[serveur])
        return self.clients[serveur]

    async def actifs(self, base: Executant) -> set[tuple[str, str]]:
        return {
            (r["serveur"], r["outil"]) for r in await base.fetch("SELECT serveur, outil FROM outils_mcp WHERE actif")
        }

    async def lister(self, base: Executant) -> list[dict[str, Any]]:
        """Outils de chaque serveur (un serveur en panne est signalé, pas bloquant)."""
        actifs = await self.actifs(base)
        sortie = []
        for ident in self.serveurs:
            try:
                outils = await self.client(ident).outils()
                sortie.append(
                    {
                        "serveur": ident,
                        "disponible": True,
                        "outils": [
                            {
                                "nom": str(o.get("name")),
                                "description": str(o.get("description") or "")[:500],
                                "schema": o.get("inputSchema") or {},
                                "actif": (ident, str(o.get("name"))) in actifs,
                            }
                            for o in outils
                        ],
                    }
                )
            except ErreurMCP as exc:
                sortie.append({"serveur": ident, "disponible": False, "erreur": str(exc), "outils": []})
        return sortie

    async def activer(self, base: Executant, serveur: str, outil: str, actif: bool) -> None:
        if serveur not in self.serveurs:
            raise ErreurMCP(f"Serveur MCP inconnu : « {serveur} »")
        await base.execute(
            "INSERT INTO outils_mcp (serveur, outil, actif) VALUES ($1, $2, $3)"
            " ON CONFLICT (serveur, outil) DO UPDATE SET actif = $3, maj_le = now()",
            serveur,
            outil,
            actif,
        )

    async def appeler(self, base: Executant, serveur: str, outil: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if (serveur, outil) not in await self.actifs(base):
            raise ErreurMCP(f"Outil MCP « {serveur}/{outil} » inactif : activez-le d'abord")
        resultat = await self.client(serveur).appeler(outil, arguments)
        return {"texte": texte_resultat(resultat), "erreur_outil": bool(resultat.get("isError"))}

    async def fermer(self) -> None:
        for c in self.clients.values():
            await c.fermer()
