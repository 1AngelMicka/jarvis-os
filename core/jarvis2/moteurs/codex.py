"""Connecteur « codex » : OpenAI Codex CLI, avec le compte ChatGPT de l'utilisateur (jamais une clé d'API).

L'utilisateur installe Codex et s'y connecte lui-même (`codex login`). JARVIS ne lit jamais `~/.codex/auth.json`
ni aucun fichier d'identifiants, ne propose aucune connexion, et retire les clés OpenAI de l'environnement.

Commande : `codex exec --json --sandbox read-only --skip-git-repo-check --ephemeral [-m <modèle>] -` (prompt sur
l'entrée standard), dans un dossier temporaire vide. Sortie JSONL : `thread.started`, `turn.started`,
`item.started` / `item.updated` / `item.completed` (le texte de la réponse est dans les éléments
`agent_message`), `turn.completed` (avec `usage`), `turn.failed`, `error`. Le texte arrive élément par élément.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..registre import MoteurRegistry
from .base import Delta, ErreurMoteur, EtatSante, Evenement, Fin, InfoModele, Message, Moteur, Options, Reponse, Usage
from .claude_code import construire_prompt
from .sousprocessus import environnement, executer_court, lignes_json, trouver

# Variables qui feraient passer Codex par une clé d'API (facturation à l'appel) au lieu du compte ChatGPT
RETIREES = ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL", "AZURE_OPENAI_API_KEY")


class AnalyseurCodex:
    """Transforme les événements JSONL de `codex exec --json` en morceaux de texte et en réponse finale."""

    def __init__(self) -> None:
        self.textes: dict[str, str] = {}  # identifiant d'élément -> texte déjà émis
        self.ordre: list[str] = []
        self.usage = Usage()
        self.modele: str | None = None
        self.erreur: str | None = None
        self.fini = False

    def lire(self, ev: Mapping[str, Any]) -> str | None:
        """Morceau de texte nouveau apporté par l'événement (ou None)."""
        type_ = ev.get("type")
        if type_ in ("item.started", "item.updated", "item.completed"):
            item = ev.get("item")
            if not isinstance(item, dict) or item.get("type") != "agent_message":
                return None  # raisonnement, commandes, recherches : jamais affichés comme réponse
            ident, texte = str(item.get("id", len(self.ordre))), str(item.get("text") or "")
            deja = self.textes.get(ident, "")
            if ident not in self.textes:
                self.ordre.append(ident)
                separateur = "\n\n" if len(self.ordre) > 1 and texte else ""
            else:
                separateur = ""
            if not texte.startswith(deja):  # texte réécrit : on n'émet que le nouveau texte complet à la fin
                self.textes[ident] = texte
                return None
            self.textes[ident] = texte
            nouveau = texte[len(deja) :]
            return (separateur + nouveau) if nouveau else None
        if type_ == "turn.completed":
            u = ev.get("usage") if isinstance(ev.get("usage"), dict) else {}
            assert isinstance(u, dict)
            entree = int(u.get("input_tokens") or 0)
            self.usage = Usage(jetons_entree=entree or None, jetons_sortie=int(u.get("output_tokens") or 0) or None)
            self.fini = True
        elif type_ == "turn.failed":
            err = ev.get("error")
            self.erreur = str(err.get("message") if isinstance(err, dict) else err or "échec du tour")
        elif type_ == "error":
            self.erreur = str(ev.get("message") or "erreur de Codex")
        elif type_ == "thread.started" and isinstance(ev.get("model"), str):
            self.modele = ev["model"]
        return None

    @property
    def texte(self) -> str:
        return "\n\n".join(t for i in self.ordre if (t := self.textes[i].strip()))


@MoteurRegistry.register("codex")
class MoteurCodex(Moteur):
    id = "codex"
    nom = "ChatGPT (Codex CLI)"
    famille = "cli"
    externe = True
    installation_url = "https://developers.openai.com/codex/cli"
    conditions_url = "https://openai.com/policies/terms-of-use"

    def __init__(
        self,
        commande: Sequence[str] | str | None = None,
        modeles: Sequence[str] = (),
        dossier_travail: Path | None = None,
        delai: float = 300.0,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.commande = trouver(commande, "codex")
        self.modeles = tuple(modeles)
        self.dossier_travail = dossier_travail
        self.delai = delai
        self._env_source = env
        self._sante: tuple[float, EtatSante] | None = None

    def _env(self) -> dict[str, str]:
        return environnement(RETIREES, self._env_source)

    def arguments(self, modele: str | None) -> list[str]:
        if self.commande is None:
            raise ErreurMoteur("Codex CLI n'est pas installé")
        args = [*self.commande, "exec", "--json", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral"]
        if modele:
            args += ["-m", modele]
        return [*args, "-"]  # « - » : le prompt est lu sur l'entrée standard

    async def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        modele = (options.modele if options else None) or None
        analyseur = AnalyseurCodex()
        async for ev in lignes_json(
            self.arguments(modele), construire_prompt(messages), self._env(), self.delai, self.dossier_travail
        ):
            morceau = analyseur.lire(ev)
            if morceau:
                yield Delta(morceau)
        if analyseur.erreur:
            raise ErreurMoteur(f"Codex : {analyseur.erreur[:300]}")
        if not analyseur.texte:
            raise ErreurMoteur("Réponse vide de Codex")
        yield Fin(
            Reponse(
                analyseur.texte, modele or analyseur.modele or "codex", analyseur.usage, 0.0, {"source_auth": "compte"}
            )
        )

    async def list_models(self) -> list[InfoModele]:
        if not self.modeles:  # Codex n'expose pas de liste : le modèle par défaut du compte, ou la configuration
            return [InfoModele("", "Par défaut (compte ChatGPT)", True)]
        return [InfoModele(m, m, i == 0) for i, m in enumerate(self.modeles)]

    async def health(self) -> EtatSante:
        """Installé ? Connecté (`codex login status`) ? Sans jamais lire les identifiants. Cache de 60 s."""
        maintenant = time.monotonic()
        if self._sante and maintenant - self._sante[0] < 60:
            return self._sante[1]
        if self.commande is None:
            etat = EtatSante(False, "non installé", installe=False, connecte=False)
        else:
            code, sortie = await executer_court([*self.commande, "login", "status"], self._env())
            if code == 0:
                etat = EtatSante(
                    True, sortie.strip().splitlines()[0][:120] if sortie.strip() else "connecté", connecte=True
                )
            else:
                etat = EtatSante(False, "non connecté : lancez « codex login » vous-même", connecte=False)
        self._sante = (maintenant, etat)
        return etat
