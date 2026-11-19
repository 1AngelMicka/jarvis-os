"""Moteur `claude_code` : la CLI `claude -p` de l'abonnement Claude de l'utilisateur. **Jamais de clé API.**

Repris de `FournisseurClaudeCode` (JARVIS v1, `llm.py`) et amélioré :
- le prompt passe par l'entrée standard (Windows limite la ligne de commande à 32 767 caractères) ;
- la sortie est toujours lue en `stream-json` : l'événement `system/init` donne la source d'authentification,
  et toute réponse qui ne vient pas de l'abonnement (`apiKeySource` ≠ « none ») est refusée ;
- sous Windows, un délai dépassé ou une annulation tue tout l'arbre de processus (`taskkill /T`).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import AsyncGenerator, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..registre import MoteurRegistry
from .base import Delta, ErreurMoteur, EtatSante, Evenement, Fin, InfoModele, Message, Moteur, Options, Reponse, Usage

journal = logging.getLogger("jarvis2.moteurs.claude_code")

# Alias -> identifiant complet actuel
MODELES: dict[str, tuple[str, str]] = {
    "opus": ("claude-opus-5-5", "Opus 5.5"),
    "sonnet": ("claude-sonnet-5-5", "Sonnet 5.5"),
    "haiku": ("claude-haiku-5-5", "Haiku 5.5"),
    "fable": ("claude-fable-5-2", "Fable 5.2"),
}
IDS_MODELES = tuple(m[0] for m in MODELES.values())
EFFORTS = ("low", "medium", "high", "xhigh", "max")
EFFORTS_LONGS = ("xhigh", "max")
DELAI_NORMAL = 120.0
DELAI_LONG = 600.0
LIMITE_PROMPT = 100_000  # caractères ; l'historique le plus ancien est coupé au-delà
TAMPON = 8 * 1024 * 1024  # une ligne stream-json peut contenir toute la réponse

# Retirées de l'environnement du sous-processus : la CLI ne doit voir ni clé API (elle basculerait sur la
# facturation à l'appel), ni accès à la base, ni secret d'un autre fournisseur.
VARIABLES_RETIREES = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "OPENROUTER_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "DATABASE_URL",
    }
)
PREFIXES_RETIRES = ("POSTGRES_", "PG", "JARVIS2_")


def resoudre_modele(valeur: str | None) -> str | None:
    """« sonnet » -> « claude-sonnet-5-5 » ; identifiant complet rendu tel quel ; vide -> None."""
    valeur = (valeur or "").strip()
    if not valeur:
        return None
    alias = MODELES.get(valeur.lower())
    return alias[0] if alias else valeur


def environnement_propre(source: Mapping[str, str]) -> dict[str, str]:
    return {
        k: v
        for k, v in source.items()
        if k.upper() not in VARIABLES_RETIREES and not k.upper().startswith(PREFIXES_RETIRES)
    }


def construire_prompt(messages: Sequence[Message], limite: int = LIMITE_PROMPT) -> str:
    """Prompt unique : `<consignes_systeme>` + `<historique>` + nouveau message.

    Le dernier message de l'utilisateur est le « nouveau message » ; les plus anciens messages de
    l'historique sont retirés tant que le total dépasse `limite`.
    """
    systeme = "\n\n".join(m.contenu for m in messages if m.role == "systeme")
    echanges = [m for m in messages if m.role != "systeme"]
    if not echanges or echanges[-1].role != "utilisateur":
        raise ErreurMoteur("Le dernier message doit venir de l'utilisateur")
    dernier, historique = echanges[-1], echanges[:-1]
    entete = f"<consignes_systeme>\n{systeme}\n</consignes_systeme>\n\n" if systeme else ""
    fin = f"Nouveau message de l'utilisateur :\n{dernier.contenu}\n"
    lignes = [f"{'Utilisateur' if m.role == 'utilisateur' else 'JARVIS'} : {m.contenu}" for m in historique]
    while lignes:
        hist = "<historique>\n" + "\n\n".join(lignes) + "\n</historique>\n\n"
        if len(entete) + len(hist) + len(fin) <= limite:
            return entete + hist + fin
        lignes.pop(0)
    return (entete + fin)[-limite:]


def morceau_texte(evenement: Mapping[str, Any]) -> str | None:
    """Texte d'un `stream_event` / `content_block_delta` / `text_delta`, sinon None."""
    if evenement.get("type") != "stream_event":
        return None
    ev = evenement.get("event")
    if not isinstance(ev, dict) or ev.get("type") != "content_block_delta":
        return None
    delta = ev.get("delta")
    if isinstance(delta, dict) and delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
        texte: str = delta["text"]
        return texte
    return None


def _entier(valeur: Any) -> int:
    return int(valeur) if isinstance(valeur, int | float) and not isinstance(valeur, bool) else 0


def analyser_resultat(donnees: Mapping[str, Any], demande: str | None) -> Reponse:
    """Ligne `type=result` -> `Reponse` (texte, modèle réel lu dans `modelUsage`, jetons)."""
    if donnees.get("is_error"):
        raise ErreurMoteur(f"La CLI claude a signalé une erreur : {str(donnees.get('result'))[:300]}")
    texte = donnees.get("result")
    if not isinstance(texte, str) or not texte.strip():
        raise ErreurMoteur("Réponse vide de la CLI claude")
    usages = donnees.get("modelUsage")
    modele = demande
    if isinstance(usages, dict) and usages:

        def sortie(cle: str) -> int:
            u = usages.get(cle)
            return _entier(u.get("outputTokens")) if isinstance(u, dict) else 0

        exacts = [k for k in usages if k == demande]
        modele = str(max(exacts or list(usages), key=sortie))
    usage = donnees.get("usage") if isinstance(donnees.get("usage"), dict) else {}
    assert isinstance(usage, dict)
    entree = (
        _entier(usage.get("input_tokens"))
        + _entier(usage.get("cache_creation_input_tokens"))
        + _entier(usage.get("cache_read_input_tokens"))
    )
    meta: dict[str, Any] = {"duree_cli_ms": _entier(donnees.get("duration_ms"))}
    if isinstance(donnees.get("total_cost_usd"), int | float):
        # Prix équivalent API, pour information : rien n'est facturé avec l'abonnement.
        meta["cout_equivalent_api_usd"] = float(donnees["total_cost_usd"])
    return Reponse(
        texte=texte.strip(),
        modele=modele,
        usage=Usage(jetons_entree=entree or None, jetons_sortie=_entier(usage.get("output_tokens")) or None),
        cout_usd=0.0,  # inclus dans l'abonnement Claude
        meta=meta,
    )


def tuer_arbre(proc: asyncio.subprocess.Process) -> None:
    """Tue la CLI et tous ses sous-processus ; ne lève jamais."""
    if proc.returncode is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=10, check=False
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    with contextlib.suppress(ProcessLookupError):
        proc.kill()


@MoteurRegistry.register("claude_code")
class MoteurClaudeCode(Moteur):
    id = "claude_code"
    nom = "Claude (abonnement)"
    externe = True
    famille = "cli"
    installation_url = "https://code.claude.com/docs/fr/setup"
    conditions_url = "https://www.anthropic.com/legal/consumer-terms"
    efforts = EFFORTS

    def __init__(
        self,
        commande: Sequence[str] | str | None = None,
        modele: str | None = "claude-sonnet-5-5",
        effort: str | None = "medium",
        dossier_travail: Path | None = None,
        delai: float = DELAI_NORMAL,
        delai_long: float = DELAI_LONG,
        env: Mapping[str, str] | None = None,
    ) -> None:
        if isinstance(commande, str) and commande.strip():
            self.commande = [commande.strip()]
        elif commande and not isinstance(commande, str):
            self.commande = list(commande)
        else:
            trouve = shutil.which("claude")
            self.commande = [trouve] if trouve else ["claude"]
        self.modele = resoudre_modele(modele)
        self.effort = effort if effort in EFFORTS else None
        self.dossier_travail = dossier_travail
        self.delai = delai
        self.delai_long = delai_long
        self._env_source = env
        self._sante: tuple[float, EtatSante] | None = None

    def arguments(self, modele: str | None, effort: str | None) -> list[str]:
        args = list(self.commande)
        if modele:
            args += ["--model", modele]
        if effort:
            args += ["--effort", effort]
        # Aucun outil ni serveur MCP : en conversation, Claude répond, il n'agit pas.
        args += [
            "--tools",
            "",
            "--strict-mcp-config",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--no-session-persistence",
            "-p",
        ]
        return args

    def _delai_pour(self, effort: str | None) -> float:
        return max(self.delai, self.delai_long) if effort in EFFORTS_LONGS else self.delai

    async def stream(self, messages: Sequence[Message], options: Options | None = None) -> AsyncGenerator[Evenement]:
        options = options or Options()
        modele = resoudre_modele(options.modele) or self.modele
        effort = options.effort if options.effort in EFFORTS else ("low" if options.rapide else self.effort)
        prompt = construire_prompt(messages)
        env = environnement_propre(self._env_source if self._env_source is not None else os.environ)
        cwd: Path | None = None
        if self.dossier_travail is not None:
            self.dossier_travail.mkdir(parents=True, exist_ok=True)
            cwd = self.dossier_travail
        groupe: dict[str, Any] = {"start_new_session": True}
        if sys.platform == "win32":
            groupe = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.arguments(modele, effort),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                limit=TAMPON,
                **groupe,
            )
        except FileNotFoundError as exc:
            raise ErreurMoteur("CLI claude introuvable : installer Claude Code puis « claude /login »") from exc
        assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
        erreurs = asyncio.create_task(proc.stderr.read())
        delai = self._delai_pour(effort)
        echeance = time.monotonic() + delai
        resultat: dict[str, Any] | None = None
        source_auth: str | None = None
        termine = False
        try:
            proc.stdin.write(prompt.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
            while True:
                reste = echeance - time.monotonic()
                if reste <= 0:
                    raise TimeoutError
                ligne = await asyncio.wait_for(proc.stdout.readline(), timeout=reste)
                if not ligne:
                    break
                try:
                    evenement = json.loads(ligne)
                except ValueError:
                    continue
                if not isinstance(evenement, dict):
                    continue
                if evenement.get("type") == "system" and evenement.get("subtype") == "init":
                    source_auth = str(evenement.get("apiKeySource", ""))
                    if source_auth != "none":
                        raise ErreurMoteur(
                            f"La CLI claude s'authentifie par une clé API (source : {source_auth}) : refusé, "
                            "JARVIS n'utilise que l'abonnement Claude"
                        )
                    continue
                texte = morceau_texte(evenement)
                if texte:
                    if source_auth is None:
                        raise ErreurMoteur("Source d'authentification de la CLI claude inconnue : réponse refusée")
                    yield Delta(texte)
                elif evenement.get("type") == "result":
                    resultat = evenement
            await asyncio.wait_for(proc.wait(), timeout=max(1.0, echeance - time.monotonic()))
            termine = True
        except TimeoutError as exc:
            raise ErreurMoteur(f"La CLI claude n'a pas répondu en {delai:.0f} s") from exc
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise ErreurMoteur("La CLI claude s'est arrêtée avant de lire la demande") from exc
        finally:
            if not termine:  # délai, erreur, annulation ou client parti : la CLI ne continue pas seule
                tuer_arbre(proc)
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(proc.wait(), timeout=10)
            if not erreurs.done():
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(asyncio.shield(erreurs), timeout=2)
            if not erreurs.done():
                erreurs.cancel()
        if source_auth is None:
            brut = erreurs.result() if erreurs.done() and not erreurs.cancelled() else b""
            detail = brut.decode("utf-8", "replace")
            if "login" in detail.lower() or "auth" in detail.lower():
                raise ErreurMoteur("Claude Code n'est pas connecté : lancer « claude » puis /login")
            raise ErreurMoteur(f"La CLI claude a échoué (code {proc.returncode}) : {detail.strip()[:300]}")
        if resultat is None:
            raise ErreurMoteur(f"La CLI claude s'est arrêtée sans résultat (code {proc.returncode})")
        reponse = analyser_resultat(resultat, modele)
        reponse.meta["source_auth"] = source_auth
        if effort:
            reponse.meta["effort"] = effort
        yield Fin(reponse)

    async def list_models(self) -> list[InfoModele]:
        return [InfoModele(id=i, nom=n, defaut=i == self.modele) for i, n in MODELES.values()]

    async def health(self) -> EtatSante:
        """Vérifie que la CLI répond (`--version`), sans appeler de modèle. Mis en cache 60 s."""
        maintenant = time.monotonic()
        if self._sante and maintenant - self._sante[0] < 60:
            return self._sante[1]
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.commande,
                "--version",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=environnement_propre(self._env_source if self._env_source is not None else os.environ),
            )
            sortie, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            etat = (
                EtatSante(True, sortie.decode("utf-8", "replace").strip())
                if proc.returncode == 0
                else EtatSante(False, f"CLI claude en erreur (code {proc.returncode})")
            )
        except FileNotFoundError:
            etat = EtatSante(False, "CLI claude introuvable", installe=False)
        except TimeoutError:
            etat = EtatSante(False, "CLI claude sans réponse")
        self._sante = (maintenant, etat)
        return etat
