"""Connecteur « antigravity » : Google Antigravity CLI (`agy`), avec le compte Google de l'utilisateur.

⚠️ Connecteur à RISQUE, désactivé par défaut. Les conditions d'Antigravity (section 6) interdisent « using third
party software, tools, or services to access the Service » et des comptes ont été suspendus (403 « ToS ») pour
cet usage. Il ne s'active qu'après un avertissement que l'utilisateur coche lui-même (voir connecteurs.py), le
routeur ne le choisit jamais, et la clé d'API Gemini est l'alternative recommandée.

L'utilisateur se connecte une fois lui-même (`agy`, interactif). JARVIS ne lit, ne copie ni ne stocke jamais les
identifiants en cache. Commande : `agy -p <consigne> --output-format stream-json --sandbox [--model <slug>]`, le
prompt sur l'entrée standard, dans un dossier temporaire vide. Jamais `--dangerously-skip-permissions`, aucune règle
`permissions.allow`.

Format du flux (celui de Gemini CLI, dont Antigravity CLI prend la suite ; à confirmer sur une sortie réelle) :
`init` (session, modèle), `message` (role `assistant`, `content`, `delta: true` pour les morceaux), `tool_use`,
`tool_result`, `error`, puis `result` (`status`, `stats` avec les jetons).
"""

from __future__ import annotations

import re
import time
from collections.abc import AsyncGenerator, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..registre import MoteurRegistry
from .base import Delta, ErreurMoteur, EtatSante, Evenement, Fin, InfoModele, Message, Moteur, Options, Reponse, Usage
from .claude_code import construire_prompt
from .sousprocessus import environnement, executer_court, lignes_json, trouver

RETIREES = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_GENAI_USE_VERTEXAI")
CONSIGNE = "Réponds au message de l'utilisateur fourni sur l'entrée standard. N'utilise aucun outil."
VERSION_CONDITIONS = "antigravity-2026-11"  # version de l'avertissement à accepter (connecteurs.py)
INTERDITS = ("--dangerously-skip-permissions", "--yolo")


class AnalyseurAntigravity:
    def __init__(self) -> None:
        self.morceaux: list[str] = []
        self.complet: str | None = None
        self.modele: str | None = None
        self.usage = Usage()
        self.erreur: str | None = None
        self.outils = 0

    def lire(self, ev: Mapping[str, Any]) -> str | None:
        type_ = ev.get("type")
        if type_ == "init":
            self.modele = str(ev.get("model") or "") or None
        elif type_ == "message" and ev.get("role") == "assistant":
            contenu = ev.get("content")
            if isinstance(contenu, str) and contenu:
                if ev.get("delta"):
                    self.morceaux.append(contenu)
                    return contenu
                self.complet = contenu  # message entier (sans morceaux)
        elif type_ == "tool_use":
            self.outils += 1  # bac à sable : l'outil est refusé ou sans effet ; jamais affiché comme réponse
        elif type_ == "error" and ev.get("severity", "error") == "error":
            self.erreur = str(ev.get("message") or "erreur d'Antigravity")
        elif type_ == "result":
            stats = ev.get("stats") if isinstance(ev.get("stats"), dict) else {}
            assert isinstance(stats, dict)
            self.usage = Usage(
                int(stats.get("input_tokens") or 0) or None, int(stats.get("output_tokens") or 0) or None
            )
            if ev.get("status") not in (None, "success"):
                erreur = ev.get("error")
                self.erreur = str(erreur.get("message") if isinstance(erreur, dict) else erreur or ev.get("status"))
        return None

    @property
    def texte(self) -> str:
        return ("".join(self.morceaux) or self.complet or "").strip()


def lire_modeles(sortie: str) -> list[str]:
    """Slugs de `agy models` : premier mot de chaque ligne qui ressemble à un identifiant de modèle."""
    slugs = []
    for ligne in sortie.splitlines():
        mot = ligne.strip().split(" ")[0].strip("*-•")
        if re.fullmatch(r"[a-z0-9][a-z0-9._/-]{2,80}", mot) and mot not in slugs:
            slugs.append(mot)
    return slugs


@MoteurRegistry.register("antigravity")
class MoteurAntigravity(Moteur):
    id = "antigravity"
    nom = "Google (compte, Antigravity CLI)"
    famille = "cli"
    externe = True
    risque = True
    actif_par_defaut = False
    installation_url = "https://antigravity.google/"
    conditions_url = "https://antigravity.google/terms"

    def __init__(
        self,
        commande: Sequence[str] | str | None = None,
        dossier_travail: Path | None = None,
        delai: float = 300.0,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.commande = trouver(commande, "agy")
        self.dossier_travail = dossier_travail
        self.delai = delai
        self._env_source = env
        self._sante: tuple[float, EtatSante] | None = None
        self._modeles: tuple[float, list[InfoModele]] | None = None

    def _env(self) -> dict[str, str]:
        return environnement(RETIREES, self._env_source)

    def arguments(self, modele: str | None) -> list[str]:
        if self.commande is None:
            raise ErreurMoteur("Antigravity CLI n'est pas installé")
        args = [*self.commande, "-p", CONSIGNE, "--output-format", "stream-json", "--sandbox"]
        if modele:
            args += ["--model", modele]
        assert not any(a in INTERDITS for a in args)  # garde-fou : jamais d'autorisations élargies
        return args

    async def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        modele = (options.modele if options else None) or None
        analyseur = AnalyseurAntigravity()
        async for ev in lignes_json(
            self.arguments(modele), construire_prompt(messages), self._env(), self.delai, self.dossier_travail
        ):
            morceau = analyseur.lire(ev)
            if morceau:
                yield Delta(morceau)
        if analyseur.erreur:
            raise ErreurMoteur(f"Antigravity : {analyseur.erreur[:300]}")
        if not analyseur.texte:
            raise ErreurMoteur("Réponse vide d'Antigravity")
        if analyseur.complet and not analyseur.morceaux:
            yield Delta(analyseur.texte)
        yield Fin(
            Reponse(
                analyseur.texte,
                modele or analyseur.modele or "antigravity",
                analyseur.usage,
                0.0,
                {"source_auth": "compte", "outils_refuses": analyseur.outils},
            )
        )

    async def list_models(self) -> list[InfoModele]:
        if self.commande is None:
            return []
        maintenant = time.monotonic()
        if self._modeles and maintenant - self._modeles[0] < 600:
            return self._modeles[1]
        code, sortie = await executer_court([*self.commande, "models"], self._env())
        slugs = lire_modeles(sortie) if code == 0 else []
        modeles = [InfoModele(s, s, i == 0) for i, s in enumerate(slugs)] or [InfoModele("", "Par défaut", True)]
        self._modeles = (maintenant, modeles)
        return modeles

    async def health(self) -> EtatSante:
        maintenant = time.monotonic()
        if self._sante and maintenant - self._sante[0] < 60:
            return self._sante[1]
        if self.commande is None:
            etat = EtatSante(False, "non installé", installe=False, connecte=False)
        else:
            code, sortie = await executer_court([*self.commande, "--version"], self._env())
            etat = (
                EtatSante(True, sortie.strip()[:80] or "installé", connecte=None)
                if code == 0
                else EtatSante(False, "installé mais ne répond pas", connecte=False)
            )
        self._sante = (maintenant, etat)
        return etat
