"""Client MCP (Model Context Protocol, transport stdio : JSON-RPC 2.0, un message JSON par ligne).

Les serveurs sont déclarés par l'utilisateur dans sa configuration locale :

    [[mcp.serveurs]]
    id = "fichiers"
    commande = "npx"
    args = ["-y", "@modelcontextprotocol/server-filesystem", "C:/Documents/partage"]

Garde-fous : chaque outil est INACTIF tant que l'utilisateur ne l'a pas activé (table `outils_mcp`) ; tout appel
passe par la file d'approbations (🟡, action `mcp.appeler`) ; le résultat est une donnée, jamais une instruction ;
le serveur tourne sans les clés d'API de l'environnement (seules ses variables `env` déclarées lui sont données).

Sessions (phase 14, point 12) : chaque serveur garde **une session persistante** (processus et liste d'outils gardés
entre les appels, liste rafraîchie sur `notifications/tools/list_changed`). Un serveur qui plante est **relancé une
fois** (réglage `relance_auto`) ; s'il replante, il est « en panne » jusqu'à une relance demandée par l'utilisateur.
Un appel d'outil interrompu par un plantage n'est **jamais rejoué** (il a pu agir) : seule la liste des outils l'est.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ..db import Executant
from ..moteurs.sousprocessus import environnement
from ..securite import barriere

journal = logging.getLogger("jarvis2.mcp")

VERSION_PROTOCOLE = "2025-06-18"
IDENT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
STABLE_APRES = 600.0  # un plantage 10 min après le dernier démarrage redonne droit à une relance automatique
OUTILS_PAR_TOUR_MAX = 11  # outil de recherche compris : toujours MOINS de 12 outils proposés au modèle
REGLAGES_DEFAUT: dict[str, Any] = {"max_outils": 8, "par_le_sens": True, "relance_auto": True}


class ErreurMCP(RuntimeError):
    pass


class ErreurArret(ErreurMCP):
    """Le processus du serveur s'est arrêté (plantage), par opposition à un délai dépassé."""


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
    """Une session persistante avec un serveur MCP : processus lancé à la demande, gardé, relancé une fois."""

    def __init__(self, serveur: ServeurMCP) -> None:
        self.serveur = serveur
        self._proc: asyncio.subprocess.Process | None = None
        self._lecteur: asyncio.Task[None] | None = None
        self._attentes: dict[int, asyncio.Future[Any]] = {}
        self._compteur = 0
        self._verrou = asyncio.Lock()
        self._outils: list[dict[str, Any]] | None = None  # liste gardée entre les appels
        self.relance_auto = True
        self.demarrages = 0
        self.plantages = 0
        self.relances = 0  # relances automatiques depuis le dernier démarrage stable ou manuel
        self.en_panne = False
        self.derniere_erreur: str | None = None
        self._demarre_a: float | None = None

    @property
    def vivant(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    def etat(self) -> dict[str, Any]:
        return {
            "serveur": self.serveur.id,
            "session": "en_panne" if self.en_panne else "ouverte" if self.vivant else "fermee",
            "demarrages": self.demarrages,
            "plantages": self.plantages,
            "relances_auto": self.relances,
            "outils_connus": len(self._outils) if self._outils is not None else None,
            "derniere_erreur": self.derniere_erreur,
            "depuis_s": round(time.monotonic() - self._demarre_a) if self.vivant and self._demarre_a else None,
        }

    def outils_connus(self) -> list[dict[str, Any]] | None:
        return self._outils

    async def _demarrer(self) -> None:
        if self.vivant:
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
        self.demarrages += 1
        self._demarre_a = time.monotonic()
        self._outils = None
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
            try:
                ligne = await self._proc.stdout.readline()
            except (ValueError, OSError):  # ligne démesurée ou flux cassé : session perdue
                break
            if not ligne:
                break
            try:
                message = json.loads(ligne)
            except json.JSONDecodeError:
                continue  # le serveur écrit autre chose sur stdout : ignoré
            if not isinstance(message, dict):
                continue
            if message.get("method") == "notifications/tools/list_changed":
                self._outils = None  # relue au prochain besoin
                continue
            ident = message.get("id")
            attente = self._attentes.pop(ident, None) if isinstance(ident, int) else None
            if attente is not None and not attente.done():
                if "error" in message:
                    erreur = message["error"]
                    attente.set_exception(ErreurMCP(str(erreur.get("message", erreur))))
                else:
                    attente.set_result(message.get("result"))
        for attente in self._attentes.values():
            if not attente.done():
                attente.set_exception(ErreurArret(f"Le serveur MCP « {self.serveur.id} » s'est arrêté"))
        self._attentes.clear()

    async def _envoyer(self, message: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        try:
            self._proc.stdin.write(json.dumps(message, ensure_ascii=False).encode() + b"\n")
            await self._proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, RuntimeError) as exc:
            raise ErreurArret(f"Le serveur MCP « {self.serveur.id} » s'est arrêté") from exc

    async def _requete(self, methode: str, params: dict[str, Any]) -> Any:
        self._compteur += 1
        ident = self._compteur
        attente: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._attentes[ident] = attente
        try:
            await self._envoyer({"jsonrpc": "2.0", "id": ident, "method": methode, "params": params})
            return await asyncio.wait_for(attente, timeout=self.serveur.delai)
        except TimeoutError as exc:
            raise ErreurMCP(f"Le serveur MCP « {self.serveur.id} » ne répond pas ({methode})") from exc
        finally:
            self._attentes.pop(ident, None)

    async def _apres_plantage(self) -> bool:
        """Plantage constaté : True si une relance automatique est permise (et lancée), sinon « en panne »."""
        self.plantages += 1
        stable = self._demarre_a is not None and time.monotonic() - self._demarre_a > STABLE_APRES
        if stable:
            self.relances = 0
        await self._nettoyer()
        if not self.relance_auto or self.relances >= 1:
            self.en_panne = True
            self.derniere_erreur = "Plantages répétés : relance manuelle nécessaire"
            journal.warning("Serveur MCP « %s » en panne (plantages répétés)", self.serveur.id)
            return False
        self.relances += 1
        journal.warning("Serveur MCP « %s » planté : relance automatique", self.serveur.id)
        return True

    async def _executer(self, methode: str, params: dict[str, Any], rejouable: bool) -> Any:
        async with self._verrou:
            if self.en_panne:
                raise ErreurMCP(
                    f"Serveur MCP « {self.serveur.id} » en panne après une relance : relancez-le depuis Agents"
                )
            # Processus mort depuis le dernier appel : rien n'a été envoyé, la requête peut partir après la relance
            if self._proc is not None and self._proc.returncode is not None and not await self._apres_plantage():
                raise ErreurMCP(f"Serveur MCP « {self.serveur.id} » en panne : relancez-le depuis Agents")
            try:
                await self._demarrer()
                resultat = await self._requete(methode, params)
            except ErreurArret as exc:
                self.derniere_erreur = str(exc)
                if not await self._apres_plantage():
                    raise ErreurMCP(f"{exc} (en panne : relancez-le depuis Agents)") from exc
                try:
                    await self._demarrer()
                except ErreurMCP as relance:
                    self.en_panne = True
                    self.derniere_erreur = str(relance)
                    raise
                if not rejouable:  # l'appel a pu agir avant le plantage : jamais rejoué
                    raise ErreurMCP(
                        f"{exc} pendant l'appel : session relancée, l'appel n'a pas été rejoué (relancez-le)"
                    ) from exc
                resultat = await self._requete(methode, params)
            self.derniere_erreur = None
            return resultat

    async def outils(self) -> list[dict[str, Any]]:
        if self._outils is not None and self.vivant:
            return self._outils
        resultat = await self._executer("tools/list", {}, rejouable=True)
        self._outils = list((resultat or {}).get("tools") or [])
        return self._outils

    async def appeler(self, outil: str, arguments: dict[str, Any]) -> dict[str, Any]:
        resultat = await self._executer("tools/call", {"name": outil, "arguments": arguments}, rejouable=False)
        return dict(resultat or {})

    async def relancer(self) -> None:
        """Relance demandée par l'utilisateur : la panne est levée et le compteur de relances remis à zéro."""
        async with self._verrou:
            await self._nettoyer()
            self.en_panne = False
            self.relances = 0
            self.derniere_erreur = None
            await self._demarrer()

    async def _nettoyer(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._proc.kill()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._proc.wait(), timeout=5)
        if self._lecteur is not None:
            self._lecteur.cancel()
            with contextlib.suppress(BaseException):
                await self._lecteur
        self._proc, self._lecteur, self._outils = None, None, None

    async def fermer(self) -> None:
        await self._nettoyer()


def texte_resultat(resultat: dict[str, Any], limite: int = 20_000) -> str:
    """Contenu texte d'un résultat d'outil (les autres types sont résumés)."""
    morceaux = []
    for c in resultat.get("content") or []:
        if isinstance(c, dict) and c.get("type") == "text":
            morceaux.append(str(c.get("text", "")))
        elif isinstance(c, dict):
            morceaux.append(f"[{c.get('type', 'contenu')} non textuel]")
    return "\n".join(morceaux)[:limite]


def reglages_valides(brut: Any) -> dict[str, Any]:
    valeur = json.loads(brut) if isinstance(brut, str) else brut
    sortie = dict(REGLAGES_DEFAUT)
    if isinstance(valeur, dict):
        with contextlib.suppress(TypeError, ValueError):
            sortie["max_outils"] = max(1, min(OUTILS_PAR_TOUR_MAX, int(valeur.get("max_outils", 8))))
        sortie["par_le_sens"] = bool(valeur.get("par_le_sens", True))
        sortie["relance_auto"] = bool(valeur.get("relance_auto", True))
    return sortie


class GestionnaireMCP:
    def __init__(self, serveurs: Sequence[ServeurMCP]) -> None:
        self.serveurs = {s.id: s for s in serveurs}
        self.clients: dict[str, ClientMCP] = {}
        self.relance_auto = True

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
        self.clients[serveur].relance_auto = self.relance_auto
        return self.clients[serveur]

    # Réglages (etat_systeme « mcp », créée par la migration 030, écrite par UPDATE seulement) ---------------

    async def reglages(self, base: Executant) -> dict[str, Any]:
        try:
            brut = await base.fetchval("SELECT valeur FROM etat_systeme WHERE cle = 'mcp'")
        except Exception:  # base ancienne : réglages par défaut
            brut = None
        reglages = reglages_valides(brut)
        self.relance_auto = reglages["relance_auto"]
        return reglages

    async def regler(self, base: Executant, changement: dict[str, Any]) -> dict[str, Any]:
        reglages = reglages_valides({**await self.reglages(base), **changement})
        await base.execute(
            "UPDATE etat_systeme SET valeur = $1::text::jsonb, maj_le = now() WHERE cle = 'mcp'", json.dumps(reglages)
        )
        self.relance_auto = reglages["relance_auto"]
        for c in self.clients.values():
            c.relance_auto = self.relance_auto
        return reglages

    def sessions(self) -> list[dict[str, Any]]:
        return [(self.clients[i] if i in self.clients else ClientMCP(self.serveurs[i])).etat() for i in self.serveurs]

    async def relancer(self, serveur: str) -> dict[str, Any]:
        client = self.client(serveur)
        await client.relancer()
        return client.etat()

    # Outils -------------------------------------------------------------------------------------------------

    async def actifs(self, base: Executant) -> set[tuple[str, str]]:
        return {
            (r["serveur"], r["outil"]) for r in await base.fetch("SELECT serveur, outil FROM outils_mcp WHERE actif")
        }

    async def lister(self, base: Executant) -> list[dict[str, Any]]:
        """Outils de chaque serveur (un serveur en panne est signalé, pas bloquant)."""
        await self.reglages(base)
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

    async def outils_actifs(self, base: Executant, delai: float = 5.0) -> list[dict[str, Any]]:
        """Outils activés, avec leur description (serveurs démarrés seulement s'ils ont un outil actif)."""
        actifs = await self.actifs(base)
        serveurs = sorted({s for s, _ in actifs if s in self.serveurs})
        sortie: list[dict[str, Any]] = []
        for ident in serveurs:
            client = self.client(ident)
            try:
                outils = client.outils_connus() if client.vivant else None
                if outils is None:
                    outils = await asyncio.wait_for(client.outils(), timeout=delai)
            except (ErreurMCP, TimeoutError):
                continue  # un serveur lent ou en panne n'empêche jamais de répondre
            for o in outils:
                nom = str(o.get("name"))
                if (ident, nom) in actifs:
                    sortie.append(
                        {"serveur": ident, "outil": nom, "description": str(o.get("description") or "")[:300]}
                    )
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
        await self.reglages(base)
        resultat = await self.client(serveur).appeler(outil, arguments)
        barriere.marquer("mcp", f"{serveur}/{outil}")  # résultat lu : le tour courant ne peut plus agir
        return {"texte": texte_resultat(resultat), "erreur_outil": bool(resultat.get("isError"))}

    async def fermer(self) -> None:
        for c in self.clients.values():
            await c.fermer()
