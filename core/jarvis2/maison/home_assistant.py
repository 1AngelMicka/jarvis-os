"""Home Assistant, le PC restant le cerveau : JARVIS décide, Home Assistant exécute.

- **Désactivé par défaut** : réglages dans `etat_systeme` (clé `home_assistant`, ligne créée par la migration 026),
  activé par l'utilisateur dans Connecteurs › Maison.
- **Transport principal : le serveur MCP de Home Assistant** (intégration « Model Context Protocol Server »,
  `/api/mcp`, transport MCP HTTP « streamable »), avec un jeton OAuth obtenu par le flux d'autorisation de Home
  Assistant avec PKCE (S256). Le jeton de rafraîchissement va dans le coffre local, jamais en base ni au journal.
- **Repli : API REST** (`/api/states`, `/api/services/…`) avec un jeton d'accès longue durée rangé dans le coffre.
- **Adresse locale seulement** : réseau local, Tailscale ou ce PC ; une adresse Internet est refusée (le jeton ne part
  jamais vers un service en ligne).
- **Niveaux par domaine** (décidés ici, jamais par Home Assistant ni par le modèle) : 🟢 lecture de l'état ;
  🟡 lumières, prises, média ; 🔴 serrures, alarme, portail (clé d'accès + voix du propriétaire, voir `actions.py`).
  Une entité d'un autre domaine que celui de l'action est refusée : « allumer une prise » ne peut pas ouvrir un portail.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode, urlsplit

import httpx

from .. import __version__
from ..flux_donnees import destination_url

if TYPE_CHECKING:
    from ..db import Base
    from ..securite.coffre import Coffre

CLE_ETAT = "home_assistant"
REGLAGES_DEFAUT: dict[str, Any] = {"actif": False, "adresse": None, "mode": "mcp"}
COFFRE_JETON = "maison.home_assistant.jeton"  # jeton d'accès longue durée (repli REST)
COFFRE_OAUTH = "maison.home_assistant.oauth"  # jeton de rafraîchissement OAuth (MCP)
COFFRE_CODE_ALARME = "maison.home_assistant.code_alarme"  # facultatif : jamais dans les paramètres d'une demande
DELAI = 8.0
DUREE_ETAT_OAUTH = 600.0  # une autorisation commencée vaut 10 minutes
VERSION_MCP = "2025-03-26"
CHEMIN_RETOUR = "/v1/maison/home-assistant/oauth/retour"

# Domaine Home Assistant → niveau. Couvertures : seulement portails et portes de garage (🔴).
DOMAINES: dict[str, str] = {
    "light": "jaune",
    "switch": "jaune",
    "media_player": "jaune",
    "lock": "rouge",
    "alarm_control_panel": "rouge",
    "cover": "rouge",
}
COUVERTURES_PORTAIL = ("gate", "garage")
DOMAINES_LUS = (*DOMAINES, "sensor", "binary_sensor", "climate", "person", "weather")


class ErreurHomeAssistant(RuntimeError):
    """Message en français, affichable tel quel."""


def adresse_home_assistant(adresse: str) -> str:
    """URL de Home Assistant sur le réseau local (ou ce PC, ou Tailscale) ; sinon refus. Sans chemin final."""
    texte = adresse.strip().rstrip("/")
    if "://" not in texte:
        texte = f"http://{texte}"
    morceaux = urlsplit(texte)
    if morceaux.scheme not in ("http", "https") or not morceaux.hostname:
        raise ErreurHomeAssistant("Adresse invalide : par exemple http://homeassistant.local:8123")
    if morceaux.username or morceaux.password or morceaux.query or morceaux.fragment or morceaux.path not in ("", "/"):
        raise ErreurHomeAssistant("Adresse invalide : seulement l'hôte et le port (sans chemin ni identifiants)")
    if destination_url(texte) == "internet":
        raise ErreurHomeAssistant("Adresse refusée : Home Assistant doit être sur le réseau local, Tailscale ou ce PC")
    try:
        port = morceaux.port
    except ValueError as exc:
        raise ErreurHomeAssistant("Port invalide") from exc
    hote = f"[{morceaux.hostname}]" if ":" in morceaux.hostname else morceaux.hostname
    return f"{morceaux.scheme}://{hote}{f':{port}' if port else ''}"


# --- PKCE (RFC 7636) ----------------------------------------------------------------------------------------------


def verifieur_pkce() -> str:
    return secrets.token_urlsafe(48)  # 64 caractères, dans l'alphabet permis


def defi_pkce(verifieur: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifieur.encode("ascii")).digest()).rstrip(b"=").decode()


# --- Entités ------------------------------------------------------------------------------------------------------


def domaine_de(entite: str) -> str:
    return entite.partition(".")[0]


def niveau_entite(entite: str, attributs: dict[str, Any] | None = None) -> str | None:
    """Niveau d'une entité pilotable, ou None si JARVIS ne la pilote pas (couverture autre qu'un portail…)."""
    domaine = domaine_de(entite)
    if domaine == "cover" and (attributs or {}).get("device_class") not in COUVERTURES_PORTAIL:
        return None
    return DOMAINES.get(domaine)


def resumer_etats(etats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """États REST → liste courte : entité, nom, état, niveau de pilotage. Une donnée, jamais une instruction."""
    sortie = []
    for e in etats:
        entite = str(e.get("entity_id", ""))
        if domaine_de(entite) not in DOMAINES_LUS:
            continue
        attributs = e.get("attributes") or {}
        sortie.append(
            {
                "entite": entite,
                "nom": str(attributs.get("friendly_name") or entite)[:80],
                "etat": str(e.get("state", ""))[:40],
                "niveau": niveau_entite(entite, attributs),
            }
        )
    return sorted(sortie, key=lambda x: x["entite"])[:300]


# --- Client MCP HTTP (« streamable HTTP ») --------------------------------------------------------------------------


def _lire_reponse_mcp(rep: httpx.Response, ident: int) -> Any:
    """Réponse JSON directe ou flux SSE (`text/event-stream`) : le message JSON-RPC qui porte notre identifiant."""
    sorte = rep.headers.get("content-type", "")
    messages: list[Any] = []
    if sorte.startswith("text/event-stream"):
        for bloc in rep.text.split("\n\n"):
            donnees = "\n".join(ligne[5:].lstrip() for ligne in bloc.splitlines() if ligne.startswith("data:"))
            if donnees:
                messages.append(json.loads(donnees))
    else:
        contenu = rep.json()
        messages.extend(contenu if isinstance(contenu, list) else [contenu])
    for m in messages:
        if isinstance(m, dict) and m.get("id") == ident:
            if "error" in m:
                raise ErreurHomeAssistant(f"Home Assistant (MCP) a refusé : {str(m['error'].get('message'))[:200]}")
            return m.get("result")
    raise ErreurHomeAssistant("Réponse MCP sans résultat")


@dataclass
class ClientMCPHttp:
    url: str
    jeton: str
    transport: httpx.AsyncBaseTransport | None = None
    session: str | None = None
    _ident: int = 0

    def _entetes(self) -> dict[str, str]:
        entetes = {
            "Authorization": f"Bearer {self.jeton}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": VERSION_MCP,
        }
        if self.session:
            entetes["Mcp-Session-Id"] = self.session
        return entetes

    async def _poster(self, client: httpx.AsyncClient, message: dict[str, Any]) -> httpx.Response:
        try:
            rep = await client.post(self.url, json=message, headers=self._entetes())
        except httpx.HTTPError as exc:
            raise ErreurHomeAssistant("Serveur MCP de Home Assistant injoignable") from exc
        if rep.status_code in (401, 403):
            raise ErreurHomeAssistant("Jeton refusé par Home Assistant : reconnectez JARVIS")
        if rep.status_code == 404:
            raise ErreurHomeAssistant("Serveur MCP absent : ajoutez l'intégration « Model Context Protocol Server »")
        if rep.status_code >= 400:
            raise ErreurHomeAssistant(f"Home Assistant (MCP) a répondu {rep.status_code}")
        return rep

    async def _requete(self, client: httpx.AsyncClient, methode: str, params: dict[str, Any]) -> Any:
        self._ident += 1
        ident = self._ident
        rep = await self._poster(client, {"jsonrpc": "2.0", "id": ident, "method": methode, "params": params})
        if methode == "initialize" and rep.headers.get("mcp-session-id"):
            self.session = rep.headers["mcp-session-id"][:200]
        try:
            return _lire_reponse_mcp(rep, ident)
        except ValueError as exc:
            raise ErreurHomeAssistant("Réponse MCP illisible") from exc

    async def _ouvrir(self, client: httpx.AsyncClient) -> None:
        await self._requete(
            client,
            "initialize",
            {
                "protocolVersion": VERSION_MCP,
                "capabilities": {},
                "clientInfo": {"name": "jarvis2", "version": __version__},
            },
        )
        await self._poster(client, {"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def outils(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=DELAI, transport=self.transport) as client:
            await self._ouvrir(client)
            resultat = await self._requete(client, "tools/list", {})
        return [o for o in (resultat or {}).get("tools", []) if isinstance(o, dict)]

    async def appeler(self, outil: str, arguments: dict[str, Any]) -> str:
        async with httpx.AsyncClient(timeout=DELAI, transport=self.transport) as client:
            await self._ouvrir(client)
            resultat = await self._requete(client, "tools/call", {"name": outil, "arguments": arguments})
        resultat = resultat or {}
        texte = "\n".join(
            str(c.get("text", ""))
            for c in resultat.get("content", [])
            if isinstance(c, dict) and c.get("type") == "text"
        )
        if resultat.get("isError"):
            raise ErreurHomeAssistant(f"Home Assistant n'a pas pu le faire : {texte[:200] or 'erreur'}")
        return texte[:20_000]


# --- Client REST (repli) ------------------------------------------------------------------------------------------


@dataclass
class ClientREST:
    adresse: str
    jeton: str
    transport: httpx.AsyncBaseTransport | None = None

    async def _appel(self, methode: str, chemin: str, corps: Any = None) -> Any:
        try:
            async with httpx.AsyncClient(base_url=self.adresse, timeout=DELAI, transport=self.transport) as client:
                rep = await client.request(
                    methode, chemin, json=corps, headers={"Authorization": f"Bearer {self.jeton}"}
                )
        except httpx.HTTPError as exc:
            raise ErreurHomeAssistant("Home Assistant injoignable") from exc
        if rep.status_code in (401, 403):
            raise ErreurHomeAssistant("Jeton refusé par Home Assistant : créez-en un nouveau dans votre profil")
        if rep.status_code == 404:
            raise ErreurHomeAssistant("Entité ou service inconnu de Home Assistant")
        if rep.status_code >= 400:
            raise ErreurHomeAssistant(f"Home Assistant a répondu {rep.status_code}")
        try:
            return rep.json()
        except ValueError as exc:
            raise ErreurHomeAssistant("Réponse illisible : est-ce bien Home Assistant ?") from exc

    async def etats(self) -> list[dict[str, Any]]:
        donnees = await self._appel("GET", "/api/states")
        return [e for e in donnees if isinstance(e, dict)] if isinstance(donnees, list) else []

    async def etat(self, entite: str) -> dict[str, Any]:
        donnees = await self._appel("GET", f"/api/states/{entite}")
        return donnees if isinstance(donnees, dict) else {}

    async def service(self, domaine: str, service: str, donnees: dict[str, Any]) -> None:
        await self._appel("POST", f"/api/services/{domaine}/{service}", donnees)


# --- Service -------------------------------------------------------------------------------------------------------


ENTITE = r"^[a-z_]+\.[a-z0-9_]{1,120}$"


@dataclass
class _AutorisationEnCours:
    verifieur: str
    client_id: str
    retour: str
    instant: float


@dataclass
class ServiceHomeAssistant:
    pool: Base
    coffre: Coffre
    transport: httpx.AsyncBaseTransport | None = None  # tests : faux Home Assistant
    horloge: Any = time.monotonic
    reglages: dict[str, Any] = field(default_factory=lambda: dict(REGLAGES_DEFAUT))
    _autorisations: dict[str, _AutorisationEnCours] = field(default_factory=dict)
    _acces: tuple[str, float] | None = None  # jeton d'accès OAuth en mémoire vive (30 min chez Home Assistant)

    async def charger(self) -> dict[str, Any]:
        brut = await self.pool.fetchval("SELECT valeur FROM etat_systeme WHERE cle = $1", CLE_ETAT)
        valeur = json.loads(brut) if isinstance(brut, str) else (brut or {})
        self.reglages = {**REGLAGES_DEFAUT, **{k: v for k, v in dict(valeur).items() if k in REGLAGES_DEFAUT}}
        return self.reglages

    async def _ecrire(self, **valeurs: Any) -> None:
        reglages = {**self.reglages, **valeurs}
        # La ligne est créée par la migration 026 : le rôle applicatif n'écrit que par UPDATE
        await self.pool.execute(
            "UPDATE etat_systeme SET valeur = $2::text::jsonb, maj_le = now() WHERE cle = $1",
            CLE_ETAT,
            json.dumps(reglages),
        )
        self.reglages = reglages

    @property
    def actif(self) -> bool:
        return bool(self.reglages.get("actif"))

    @property
    def adresse(self) -> str | None:
        valeur = self.reglages.get("adresse")
        return str(valeur) if valeur else None

    def jeton_rest(self) -> str | None:
        return self.coffre.lire(COFFRE_JETON)

    def oauth_connecte(self) -> bool:
        return self.coffre.lire(COFFRE_OAUTH) is not None

    def pret(self) -> bool:
        if not self.adresse:
            return False
        return self.oauth_connecte() or self.jeton_rest() is not None

    def decrire(self) -> dict[str, Any]:
        """Carte de l'interface : jamais un jeton, seulement « enregistré »."""
        return {
            "id": "home_assistant",
            "nom": "Home Assistant",
            "description": "Lumières, prises, média, serrures, alarme et portail par votre Home Assistant local.",
            "actif": self.actif,
            "adresse": self.adresse,
            "mode": self.reglages.get("mode", "mcp"),
            "oauth": self.oauth_connecte(),
            "jeton_rest": self.jeton_rest() is not None,
            "code_alarme": self.coffre.lire(COFFRE_CODE_ALARME) is not None,
            "pret": self.pret(),
        }

    # -- réglages ---------------------------------------------------------------------------------------------------

    async def configurer(
        self, adresse: str | None, mode: str | None, jeton: str | None, code_alarme: str | None
    ) -> None:
        valeurs: dict[str, Any] = {}
        if adresse is not None:
            propre = adresse_home_assistant(adresse)
            if propre != self.adresse:  # autre Home Assistant : l'ancienne autorisation ne vaut plus
                self.coffre.supprimer(COFFRE_OAUTH)
                self._acces = None
            valeurs["adresse"] = propre
        if mode is not None:
            if mode not in ("mcp", "rest"):
                raise ErreurHomeAssistant("Mode : « mcp » ou « rest »")
            valeurs["mode"] = mode
        if jeton is not None:
            if jeton.strip():
                self.coffre.definir(COFFRE_JETON, jeton)
            else:
                self.coffre.supprimer(COFFRE_JETON)
        if code_alarme is not None:
            if code_alarme.strip():
                self.coffre.definir(COFFRE_CODE_ALARME, code_alarme)
            else:
                self.coffre.supprimer(COFFRE_CODE_ALARME)
        if valeurs:
            await self._ecrire(**valeurs)

    async def activer(self, actif: bool) -> None:
        if actif and not self.pret():
            raise ErreurHomeAssistant("Indiquez d'abord l'adresse, puis connectez JARVIS (OAuth) ou un jeton")
        await self._ecrire(actif=actif)

    async def oublier(self) -> None:
        for nom in (COFFRE_JETON, COFFRE_OAUTH, COFFRE_CODE_ALARME):
            self.coffre.supprimer(nom)
        self._acces = None
        self._autorisations.clear()
        await self._ecrire(actif=False, adresse=None, mode="mcp")

    # -- OAuth + PKCE ----------------------------------------------------------------------------------------------

    def commencer_oauth(self, base_core: str) -> str:
        """URL d'autorisation de Home Assistant (à ouvrir dans le navigateur de l'utilisateur)."""
        if not self.adresse:
            raise ErreurHomeAssistant("Indiquez d'abord l'adresse de Home Assistant")
        maintenant = self.horloge()
        self._autorisations = {
            k: a for k, a in self._autorisations.items() if maintenant - a.instant < DUREE_ETAT_OAUTH
        }
        if len(self._autorisations) >= 5:
            raise ErreurHomeAssistant("Trop d'autorisations en cours : terminez ou attendez 10 minutes")
        etat, verifieur = secrets.token_urlsafe(24), verifieur_pkce()
        client_id = base_core.rstrip("/") + "/"
        retour = base_core.rstrip("/") + CHEMIN_RETOUR
        self._autorisations[etat] = _AutorisationEnCours(verifieur, client_id, retour, maintenant)
        requete = urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": retour,
                "state": etat,
                "code_challenge": defi_pkce(verifieur),
                "code_challenge_method": "S256",
            }
        )
        return f"{self.adresse}/auth/authorize?{requete}"

    async def _jetons(self, donnees: dict[str, str]) -> dict[str, Any]:
        if not self.adresse:
            raise ErreurHomeAssistant("Adresse de Home Assistant absente")
        try:
            async with httpx.AsyncClient(base_url=self.adresse, timeout=DELAI, transport=self.transport) as client:
                rep = await client.post("/auth/token", data=donnees)
        except httpx.HTTPError as exc:
            raise ErreurHomeAssistant("Home Assistant injoignable") from exc
        if rep.status_code >= 400:
            raise ErreurHomeAssistant("Autorisation refusée par Home Assistant : recommencez la connexion")
        try:
            corps = rep.json()
        except ValueError as exc:
            raise ErreurHomeAssistant("Réponse d'autorisation illisible") from exc
        if not isinstance(corps, dict) or not corps.get("access_token"):
            raise ErreurHomeAssistant("Réponse d'autorisation sans jeton")
        return corps

    async def terminer_oauth(self, code: str, etat: str) -> None:
        """Retour de Home Assistant : `state` vérifié (une seule fois), code échangé avec le vérifieur PKCE."""
        attente = self._autorisations.pop(etat, None)
        if attente is None or self.horloge() - attente.instant >= DUREE_ETAT_OAUTH:
            raise ErreurHomeAssistant("Autorisation inconnue ou expirée : recommencez depuis JARVIS")
        corps = await self._jetons(
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": attente.client_id,
                "code_verifier": attente.verifieur,
            }
        )
        rafraichir = corps.get("refresh_token")
        if not rafraichir:
            raise ErreurHomeAssistant("Home Assistant n'a pas donné de jeton de rafraîchissement")
        self.coffre.definir(COFFRE_OAUTH, json.dumps({"refresh_token": rafraichir, "client_id": attente.client_id}))
        self._acces = (str(corps["access_token"]), self.horloge() + float(corps.get("expires_in", 1800)) - 60)

    async def _jeton_oauth(self) -> str | None:
        if self._acces is not None and self.horloge() < self._acces[1]:
            return self._acces[0]
        brut = self.coffre.lire(COFFRE_OAUTH)
        if brut is None:
            return None
        try:
            garde = json.loads(brut)
        except ValueError:
            return None
        corps = await self._jetons(
            {"grant_type": "refresh_token", "refresh_token": garde["refresh_token"], "client_id": garde["client_id"]}
        )
        self._acces = (str(corps["access_token"]), self.horloge() + float(corps.get("expires_in", 1800)) - 60)
        return self._acces[0]

    # -- clients -----------------------------------------------------------------------------------------------------

    def _verifier_actif(self) -> str:
        if not self.actif:
            raise ErreurHomeAssistant("Connecteur Home Assistant désactivé : activez-le dans Connecteurs")
        if not self.adresse:
            raise ErreurHomeAssistant("Adresse de Home Assistant absente")
        return self.adresse

    async def mcp(self) -> ClientMCPHttp | None:
        """Client MCP si le mode MCP est choisi et qu'un jeton existe (OAuth d'abord, sinon le jeton longue durée)."""
        adresse = self._verifier_actif()
        if self.reglages.get("mode") != "mcp":
            return None
        jeton = await self._jeton_oauth() or self.jeton_rest()
        return ClientMCPHttp(f"{adresse}/api/mcp", jeton, self.transport) if jeton else None

    def rest(self) -> ClientREST | None:
        adresse = self._verifier_actif()
        jeton = self.jeton_rest()
        return ClientREST(adresse, jeton, self.transport) if jeton else None

    # -- lecture et commandes ------------------------------------------------------------------------------------------

    async def etat(self) -> dict[str, Any]:
        """🟢 État : par MCP (contexte vivant, texte de Home Assistant) ou par REST (liste des entités)."""
        mcp = await self.mcp()
        if mcp is not None:
            try:
                return {"source": "mcp", "texte": await mcp.appeler("GetLiveContext", {})}
            except ErreurHomeAssistant:
                if self.rest() is None:
                    raise
        rest = self.rest()
        if rest is None:
            raise ErreurHomeAssistant("Aucun jeton : connectez JARVIS à Home Assistant")
        return {"source": "rest", "entites": resumer_etats(await rest.etats())}

    async def tester(self) -> dict[str, Any]:
        try:
            etat = await self.etat()
        except ErreurHomeAssistant as exc:
            return {"disponible": False, "detail": str(exc)}
        if etat["source"] == "mcp":
            return {"disponible": True, "detail": "serveur MCP joignable"}
        pilotables = sum(1 for e in etat["entites"] if e["niveau"])
        return {"disponible": True, "detail": f"API REST : {len(etat['entites'])} entité(s), {pilotables} pilotable(s)"}

    async def commander(
        self,
        domaine: str,
        service: str,
        entite: str,
        donnees: dict[str, Any] | None = None,
        *,
        outil_mcp: str | None = None,
        arguments_mcp: dict[str, Any] | None = None,
        nom: str | None = None,
    ) -> dict[str, Any]:
        """Appel d'un service sur UNE entité du domaine attendu. REST si un jeton longue durée existe (l'entité y est
        vérifiée : domaine, type de couverture), sinon l'outil MCP équivalent de Home Assistant (par son nom)."""
        if not re.fullmatch(ENTITE, entite) or domaine_de(entite) != domaine:
            raise ErreurHomeAssistant(f"Entité refusée : une entité « {domaine}.… » est attendue")
        rest = self.rest()
        if rest is not None:
            attributs = (await rest.etat(entite)).get("attributes") or {}
            if niveau_entite(entite, attributs) is None:
                raise ErreurHomeAssistant("Entité refusée : JARVIS ne pilote que les portails parmi les couvertures")
            await rest.service(domaine, service, {"entity_id": entite, **(donnees or {})})
            return {"entite": entite, "service": f"{domaine}.{service}", "par": "rest"}
        mcp = await self.mcp()
        if mcp is None or outil_mcp is None:
            raise ErreurHomeAssistant(
                "Commande impossible par MCP : ajoutez un jeton d'accès longue durée (repli REST)"
                if outil_mcp is None
                else "Aucun jeton : connectez JARVIS à Home Assistant"
            )
        # Les outils de Home Assistant visent une entité par son nom (ou alias) exposé à Assist
        nom = (nom or entite.partition(".")[2].replace("_", " "))[:80]
        arguments = {"name": nom, "domain": [domaine], **(arguments_mcp or {})}
        if domaine == "cover":
            arguments["device_class"] = list(COUVERTURES_PORTAIL)
        texte = await mcp.appeler(outil_mcp, arguments)
        return {"entite": entite, "service": f"{domaine}.{service}", "par": "mcp", "reponse": texte[:500]}

    def code_alarme(self) -> str | None:
        return self.coffre.lire(COFFRE_CODE_ALARME)
