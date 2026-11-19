"""Connecteurs d'IA : catalogue, état choisi par l'utilisateur, clés, routeur.

Trois familles (voir docs/PLAN.md, « Connecteurs d'IA ») :
- `cli`   : comptes par CLI officielle installée et connectée par l'utilisateur (Claude Code, Codex, Antigravity) ;
- `api`   : clés d'API dans le coffre local (Anthropic, OpenAI, Gemini, OpenRouter, points d'accès déclarés) ;
- `local` : modèles sur le PC (Ollama, LM Studio, llama.cpp, vLLM).

Le routeur choisit parmi les connecteurs actifs et disponibles, jamais un connecteur « à risque ». L'utilisateur peut
toujours imposer son choix (par message ou par conversation).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from .config import Parametres
from .config_locale import ConfigLocale
from .db import Base, Ligne
from .moteurs import anthropic_api, antigravity, claude_code, codex, compatible_openai, ollama
from .moteurs.base import EtatSante, InfoModele
from .moteurs.telemetrie import Enregistreur, MoteurInstrumente
from .securite import audit
from .securite.appareils import Appareil
from .securite.coffre import Coffre
from .securite.permissions import ErreurAction

journal = logging.getLogger("jarvis2.connecteurs")

ORDRE_FAMILLES = {"cli": 0, "api": 1, "local": 2}
CONDITIONS: dict[str, dict[str, str]] = {
    "antigravity": {
        "version": antigravity.VERSION_CONDITIONS,
        "texte": (
            "Les conditions d'utilisation d'Antigravity (section 6) interdisent « using third party software, tools, "
            "or services to access the Service ». Des comptes ont été suspendus (erreur 403 « ToS ») pour cet usage. "
            "En activant ce connecteur, vous en acceptez le risque pour votre compte Google. Google peut utiliser vos "
            "échanges pour améliorer ses produits (désactivable dans les réglages de votre compte). Alternative sûre "
            "recommandée : le connecteur « Google Gemini (clé d'API) »."
        ),
        "url": "https://antigravity.google/terms",
    },
    # Accueil du moteur Claude Code : avertissement honnête, case cochée par l'utilisateur, alternatives
    "claude_code": {
        "version": "claude-code-2026-11",
        "texte": (
            "JARVIS appelle le programme officiel Claude Code, installé et connecté par vous (« claude /login »), sans "
            "le modifier : vos échanges passent par votre abonnement Claude et comptent dans ses limites. Cet "
            "abonnement relève des conditions d'Anthropic pour les particuliers : usage personnel, pas d'usage "
            "commercial ni pour d'autres personnes. JARVIS ne lit, ne stocke ni ne transmet jamais vos identifiants. "
            "Alternatives : une clé d'API Anthropic (facturée à l'usage), Ollama (modèles locaux), ou un fournisseur "
            "compatible OpenAI."
        ),
        "url": "https://www.anthropic.com/legal/consumer-terms",
    },
}


@dataclass
class Definition:
    moteur: MoteurInstrumente
    cle: str | None = None  # nom de la clé dans le coffre (connecteurs « api »)
    cle_url: str | None = None  # où créer la clé


def construire_catalogue(
    p: Parametres, locale: ConfigLocale, coffre: Coffre, enregistreur: Enregistreur
) -> dict[str, Definition]:
    """Tous les connecteurs connus de cette installation (actifs ou non, installés ou non)."""
    vide = p.dossier_donnees / "connecteurs-vide"
    tarifs = locale.tarifs
    defs: dict[str, Definition] = {}

    def ajouter(moteur: Any, cle: str | None = None, cle_url: str | None = None) -> None:
        defs[moteur.id] = Definition(MoteurInstrumente(moteur, enregistreur), cle, cle_url)

    # Comptes par CLI officielle
    ajouter(
        claude_code.MoteurClaudeCode(
            commande=p.claude_commande or None,
            modele=p.claude_modele,
            effort=p.claude_effort,
            dossier_travail=p.dossier_claude_vide,
        )
    )
    reg = locale.connecteur("codex")
    ajouter(codex.MoteurCodex(commande=reg.get("commande"), modeles=reg.get("modeles", ()), dossier_travail=vide))
    reg = locale.connecteur("antigravity")
    ajouter(antigravity.MoteurAntigravity(commande=reg.get("commande"), dossier_travail=vide))
    # Clés d'API
    ajouter(
        anthropic_api.MoteurAnthropic(
            cle=coffre.fournisseur("anthropic"),
            tarifs=tarifs,
            modele=locale.connecteur("anthropic_api").get("modele", "claude-sonnet-5-5"),
        ),
        "anthropic",
        "https://console.anthropic.com/settings/keys",
    )
    api = {
        "openai": ("OpenAI (clé d'API)", "https://api.openai.com/v1", "https://platform.openai.com/api-keys", False),
        "gemini": (
            "Google Gemini (clé d'API)",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            "https://aistudio.google.com/apikey",
            False,
        ),
        "openrouter": (
            "OpenRouter (clé d'API)",
            "https://openrouter.ai/api/v1",
            "https://openrouter.ai/settings/keys",
            True,
        ),
    }
    for ident, (nom, url, cle_url, cout_fourni) in api.items():
        reg = locale.connecteur(ident)
        ajouter(
            compatible_openai.MoteurCompatibleOpenAI(
                ident,
                nom,
                reg.get("url", url),
                "api",
                coffre.fournisseur(ident),
                modele=reg.get("modele"),
                modeles=reg.get("modeles", ()),
                tarifs=tarifs,
                installation_url=cle_url,
                cout_fourni=cout_fourni,
                vision=bool(reg.get("vision", True)),
            ),
            ident,
            cle_url,
        )
    # Modèles locaux
    ajouter(
        ollama.MoteurOllama(
            url=p.ollama_url,
            modele=locale.connecteur("ollama").get("modele"),
            modele_vision=locale.connecteur("ollama").get("modele_vision"),
        )
    )
    locaux = {
        "lmstudio": ("LM Studio (local)", "http://127.0.0.1:1234/v1", "https://lmstudio.ai/download"),
        "llamacpp": ("llama.cpp (local)", "http://127.0.0.1:8080/v1", "https://github.com/ggml-org/llama.cpp"),
        "vllm": ("vLLM (local)", "http://127.0.0.1:8000/v1", "https://docs.vllm.ai/en/latest/getting_started/"),
    }
    for ident, (nom, url, installation) in locaux.items():
        reg = locale.connecteur(ident)
        ajouter(
            compatible_openai.MoteurCompatibleOpenAI(
                ident,
                nom,
                reg.get("url", url),
                "local",
                None,
                modele=reg.get("modele"),
                installation_url=installation,
                vision=bool(reg.get("vision", True)),
                # Détecté sur un port connu, mais n'importe quel programme peut l'occuper : l'utilisateur l'active
                actif_par_defaut=False,
            )
        )
    # Points d'accès déclarés dans la configuration locale
    for c in locale.compatibles:
        local = bool(c.get("local"))
        nom_cle = None if local else str(c.get("cle") or c["id"])
        ajouter(
            compatible_openai.MoteurCompatibleOpenAI(
                str(c["id"]),
                str(c["nom"]),
                str(c["url"]),
                "local" if local else "api",
                coffre.fournisseur(nom_cle) if nom_cle else None,
                modele=c.get("modele"),
                tarifs=tarifs,
                vision=bool(c.get("vision", True)),
            ),
            nom_cle,
        )
    return defs


@dataclass
class EtatConnecteur:
    id: str
    famille: str
    actif: bool
    risque: bool
    sante: EtatSante
    dans_conseil: bool = False
    conditions_version: str | None = None

    @property
    def utilisable(self) -> bool:
        return self.actif and self.sante.disponible


def choisir(etats: list[EtatConnecteur], prefere: str | None = None, local: bool = False) -> str | None:
    """Routeur : le connecteur préféré s'il est utilisable, sinon le premier utilisable par famille
    (compte > clé d'API > local). Jamais un connecteur à risque : celui-là se choisit à la main.
    `local` : sujet privé, seules les IA du PC sont candidates."""
    candidats = [e for e in etats if e.utilisable and not e.risque and (not local or e.famille == "local")]
    for e in candidats:
        if e.id == prefere:
            return e.id
    candidats.sort(key=lambda e: ORDRE_FAMILLES.get(e.famille, 9))
    return candidats[0].id if candidats else None


@dataclass
class Connecteurs:
    pool: Base
    definitions: dict[str, Definition]
    coffre: Coffre
    prefere: str | None = None
    _reglages: dict[str, Ligne] = field(default_factory=dict)

    @property
    def moteurs(self) -> dict[str, MoteurInstrumente]:
        return {i: d.moteur for i, d in self.definitions.items()}

    async def charger(self) -> None:
        self._reglages = {r["id"]: r for r in await self.pool.fetch("SELECT * FROM connecteurs")}

    def actif(self, ident: str) -> bool:
        d = self.definitions.get(ident)
        if d is None:
            return False
        r = self._reglages.get(ident)
        if ident in CONDITIONS or d.moteur.interne.risque:
            # Avertissement à accepter (à risque, ou accueil de Claude Code) : seulement après la case cochée par
            # l'utilisateur, dans la version actuelle de l'avertissement
            attendue = CONDITIONS.get(ident, {}).get("version")
            return bool(r and r["actif"] and r["conditions_version"] == attendue)
        return bool(r["actif"]) if r else d.moteur.interne.actif_par_defaut

    def conditions_a_accepter(self, ident: str) -> bool:
        """Connecteur installé dont l'avertissement n'a pas été accepté dans sa version actuelle."""
        return ident in CONDITIONS and self._version_acceptee(ident) != CONDITIONS[ident]["version"]

    def _version_acceptee(self, ident: str) -> str | None:
        r = self._reglages.get(ident)
        return str(r["conditions_version"]) if r and r["conditions_version"] else None

    def dans_conseil(self, ident: str) -> bool:
        r = self._reglages.get(ident)
        return bool(r and r["dans_conseil"])

    async def sante(self, ident: str) -> EtatSante:
        try:
            return await asyncio.wait_for(self.definitions[ident].moteur.health(), timeout=8)
        except TimeoutError:
            return EtatSante(False, "ne répond pas")

    async def etats(self, tous: bool = True) -> list[EtatConnecteur]:
        """État de chaque connecteur. `tous=False` : seulement les connecteurs actifs (démarrage, routeur) — un
        connecteur désactivé n'est jamais sondé, il ne ralentit donc rien."""
        idents = [i for i in self.definitions if tous or self.actif(i)]
        sorties = await asyncio.gather(*(self.sante(i) for i in idents))
        definitions = [(i, self.definitions[i]) for i in idents]
        return [
            EtatConnecteur(
                i,
                d.moteur.interne.famille,
                self.actif(i),
                d.moteur.interne.risque,
                s,
                self.dans_conseil(i),
                self._version_acceptee(i),
            )
            for (i, d), s in zip(definitions, sorties, strict=True)
        ]

    async def router(self, local: bool = False, images: bool = False) -> str | None:
        """`images` : seuls les connecteurs qui savent lire les images jointes sont candidats."""
        etats = await self.etats(tous=False)
        if images:
            etats = [e for e in etats if self.definitions[e.id].moteur.interne.vision]
        return choisir(etats, self.prefere, local=local)

    async def decrire(self, tous: bool = True) -> list[dict[str, Any]]:
        """Cartes de la page Connecteurs (aucune clé : seulement « enregistrée » et un aperçu)."""
        etats = await self.etats(tous)
        modeles = await asyncio.gather(*(self._modeles(e) for e in etats))
        cartes = []
        for e, liste in zip(etats, modeles, strict=True):
            d = self.definitions[e.id]
            m = d.moteur.interne
            statut = (
                "non_installe"
                if not e.sante.installe
                else "desactive"
                if not e.actif
                else "disponible"
                if e.sante.disponible
                else "non_connecte"
            )
            cartes.append(
                {
                    "id": e.id,
                    "nom": m.nom,
                    "famille": e.famille,
                    "statut": statut,
                    "actif": e.actif,
                    "risque": e.risque,
                    "externe": m.externe,
                    "detail": e.sante.detail,
                    "installe": e.sante.installe,
                    "connecte": e.sante.connecte,
                    "disponible": e.utilisable,
                    "dans_conseil": e.dans_conseil,
                    "installation_url": m.installation_url,
                    "conditions_url": m.conditions_url,
                    "cle": {
                        "requise": True,
                        "enregistree": bool(self.coffre.lire(d.cle)),
                        "apercu": self.coffre.apercu(d.cle),
                        "url": d.cle_url,
                    }
                    if d.cle
                    else None,
                    "conditions": CONDITIONS.get(e.id),
                    "conditions_acceptees": e.conditions_version is not None
                    and e.conditions_version == CONDITIONS.get(e.id, {}).get("version"),
                    "modeles": [{"id": x.id, "nom": x.nom, "defaut": x.defaut} for x in liste],
                    "efforts": list(m.efforts),
                    "effort_defaut": getattr(m, "effort", None),
                    "vision": m.vision,
                }
            )
        return cartes

    async def _modeles(self, e: EtatConnecteur) -> list[InfoModele]:
        if not e.utilisable:
            return []
        try:
            return await asyncio.wait_for(self.definitions[e.id].moteur.list_models(), timeout=8)
        except TimeoutError:
            return []

    def _verifier(self, ident: str) -> Definition:
        if ident not in self.definitions:
            raise ErreurAction(f"Connecteur inconnu : « {ident} »")
        return self.definitions[ident]

    async def _ecrire(self, ident: str, **valeurs: Any) -> None:
        actuel = self._reglages.get(ident)
        actif = valeurs.get(
            "actif", actuel["actif"] if actuel else self.definitions[ident].moteur.interne.actif_par_defaut
        )
        await self.pool.execute(
            "INSERT INTO connecteurs (id, actif, dans_conseil, conditions_version, conditions_acceptees_le)"
            " VALUES ($1, $2, $3, $4, CASE WHEN $4::text IS NULL THEN NULL ELSE now() END)"
            " ON CONFLICT (id) DO UPDATE SET actif = $2, dans_conseil = $3,"
            " conditions_version = coalesce($4, connecteurs.conditions_version),"
            " conditions_acceptees_le = CASE WHEN $4::text IS NULL THEN connecteurs.conditions_acceptees_le"
            " ELSE now() END,"
            " maj_le = now()",
            ident,
            actif,
            valeurs.get("dans_conseil", actuel["dans_conseil"] if actuel else False),
            valeurs.get("conditions_version"),
        )
        await self.charger()

    async def activer(self, ident: str, appareil: Appareil, accepte: bool = False, version: str | None = None) -> None:
        d = self._verifier(ident)
        details: dict[str, Any] = {}
        if ident in CONDITIONS or d.moteur.interne.risque:
            attendue = CONDITIONS[ident]["version"]
            if not accepte or version != attendue:
                raise ErreurAction("Cochez vous-même l'avertissement de ce connecteur pour l'activer")
            details = {"conditions_version": attendue, "conditions_url": CONDITIONS[ident]["url"]}
            await self._ecrire(ident, actif=True, conditions_version=attendue)
        else:
            await self._ecrire(ident, actif=True)
        await audit.journaliser(
            self.pool,
            acteur=appareil.acteur,
            action="connecteur.active",
            cible=ident,
            niveau="jaune" if d.moteur.interne.risque else "vert",
            details=details,
        )

    async def desactiver(self, ident: str, appareil: Appareil) -> None:
        self._verifier(ident)
        await self._ecrire(ident, actif=False)
        await audit.journaliser(self.pool, acteur=appareil.acteur, action="connecteur.desactive", cible=ident)

    async def conseil(self, ident: str, inclus: bool, appareil: Appareil) -> None:
        self._verifier(ident)
        await self._ecrire(ident, dans_conseil=inclus)
        await audit.journaliser(
            self.pool, acteur=appareil.acteur, action="connecteur.conseil", cible=ident, details={"inclus": inclus}
        )

    async def definir_cle(self, ident: str, valeur: str, appareil: Appareil) -> None:
        d = self._verifier(ident)
        if not d.cle:
            raise ErreurAction("Ce connecteur n'utilise pas de clé d'API")
        if len(valeur.strip()) < 8:
            raise ErreurAction("Clé trop courte")
        await asyncio.to_thread(self.coffre.definir, d.cle, valeur)
        await audit.journaliser(
            self.pool, acteur=appareil.acteur, action="connecteur.cle_definie", cible=ident, niveau="jaune"
        )  # jamais la valeur, ni un aperçu

    async def supprimer_cle(self, ident: str, appareil: Appareil) -> None:
        d = self._verifier(ident)
        if not d.cle:
            return
        supprimee: bool = await asyncio.to_thread(self.coffre.supprimer, d.cle)
        if supprimee:
            await audit.journaliser(self.pool, acteur=appareil.acteur, action="connecteur.cle_supprimee", cible=ident)

    async def tester(self, ident: str) -> dict[str, Any]:
        """Vérifie le connecteur sans rien générer (aucun coût) : état, compte ou clé, modèles."""
        d = self._verifier(ident)
        sante = await self.sante(ident)
        modeles = await d.moteur.list_models() if sante.disponible else []
        return {
            "disponible": sante.disponible,
            "detail": sante.detail,
            "connecte": sante.connecte,
            "installe": sante.installe,
            "modeles": len(modeles),
        }
