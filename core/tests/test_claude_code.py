"""Moteur claude_code, avec une fausse CLI (aucun appel réel à Claude)."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from jarvis2.moteurs.base import Delta, ErreurMoteur, Fin, Message, Options
from jarvis2.moteurs.claude_code import (
    MoteurClaudeCode,
    construire_prompt,
    environnement_propre,
    morceau_texte,
    resoudre_modele,
)

FAUX = Path(__file__).with_name("faux_claude.py")


def moteur(scenario: str = "ok", tmp: Path | None = None, **kwargs: object) -> MoteurClaudeCode:
    env = dict(os.environ)
    env.update(
        {
            "FAUX_CLAUDE": scenario,
            "ANTHROPIC_API_KEY": "sk-ant-ne-doit-jamais-passer",
            "POSTGRES_PASSWORD": "secret",
            "DATABASE_URL": "postgresql://x",
        }
    )
    if tmp is not None:
        env["FAUX_CLAUDE_PID"] = str(tmp / "pid")
    return MoteurClaudeCode(commande=[sys.executable, str(FAUX)], env=env, dossier_travail=tmp, **kwargs)  # type: ignore[arg-type]


MESSAGES = [Message("systeme", "Tu es JARVIS."), Message("utilisateur", "Salut")]


async def test_flux_et_resultat(tmp_path: Path) -> None:
    evenements = [e async for e in moteur(tmp=tmp_path).stream(MESSAGES)]
    deltas = [e.texte for e in evenements if isinstance(e, Delta)]
    assert deltas == ["Bonjour, ", "Monsieur."]
    fin = evenements[-1]
    assert isinstance(fin, Fin)
    assert fin.reponse.texte == "Bonjour, Monsieur."
    assert fin.reponse.modele == "claude-sonnet-5-5"  # modèle demandé, présent dans modelUsage
    assert fin.reponse.cout_usd == 0.0  # abonnement
    assert fin.reponse.usage.jetons_entree == 110
    assert fin.reponse.usage.jetons_sortie == 5
    assert fin.reponse.meta["source_auth"] == "none"
    assert fin.reponse.meta["cout_equivalent_api_usd"] == pytest.approx(0.0012)


async def test_aucune_cle_api_ni_secret_transmis(tmp_path: Path) -> None:
    reponse = await moteur(tmp=tmp_path).generate(MESSAGES)
    assert "FUITE" not in reponse.texte


async def test_refuse_une_authentification_par_cle_api(tmp_path: Path) -> None:
    with pytest.raises(ErreurMoteur, match="clé API"):
        await moteur("cle_api", tmp_path).generate(MESSAGES)


async def test_refuse_sans_source_authentification(tmp_path: Path) -> None:
    with pytest.raises(ErreurMoteur, match="authentification"):
        await moteur("sans_init", tmp_path).generate(MESSAGES)


async def test_erreur_de_la_cli(tmp_path: Path) -> None:
    with pytest.raises(ErreurMoteur, match="quota atteint"):
        await moteur("erreur", tmp_path).generate(MESSAGES)


def processus_vivant(pid: int) -> bool:
    if os.name == "nt":
        import subprocess

        sortie = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, check=False
        ).stdout
        return str(pid) in sortie
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


async def test_delai_depasse_tue_le_processus(tmp_path: Path) -> None:
    m = moteur("lent", tmp_path, delai=2.0)
    debut = time.monotonic()
    with pytest.raises(ErreurMoteur, match="n'a pas répondu"):
        await m.generate(MESSAGES)
    assert time.monotonic() - debut < 15
    pid = int((tmp_path / "pid").read_text())
    assert not processus_vivant(pid)


async def test_annulation_tue_le_processus(tmp_path: Path) -> None:
    m = moteur("lent", tmp_path, delai=60.0)
    flux = m.stream(MESSAGES)
    import asyncio

    tache = asyncio.ensure_future(flux.__anext__())
    for _ in range(100):
        if (tmp_path / "pid").exists() and (tmp_path / "pid").read_text():
            break
        await asyncio.sleep(0.1)
    tache.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tache
    await flux.aclose()
    pid = int((tmp_path / "pid").read_text())
    for _ in range(50):
        if not processus_vivant(pid):
            break
        await asyncio.sleep(0.1)
    assert not processus_vivant(pid)


async def test_prompt_par_entree_standard_et_long(tmp_path: Path) -> None:
    long = "x" * 50_000  # au-delà de la limite de la ligne de commande Windows
    reponse = await moteur("echo", tmp_path).generate([Message("utilisateur", long)])
    assert long in reponse.texte


async def test_options_modele_et_effort(tmp_path: Path) -> None:
    m = moteur(tmp=tmp_path)
    args = m.arguments("claude-opus-5-5", "max")
    assert args[args.index("--model") + 1] == "claude-opus-5-5"
    assert args[args.index("--effort") + 1] == "max"
    assert args[args.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in args and "--no-session-persistence" in args
    assert m._delai_pour("max") == 600.0 and m._delai_pour("high") == 120.0
    reponse = await m.generate(MESSAGES, Options(modele="opus"))
    assert reponse.modele == "claude-opus-5-5"


def test_resoudre_modele() -> None:
    assert resoudre_modele("sonnet") == "claude-sonnet-5-5"
    assert resoudre_modele("fable") == "claude-fable-5-2"
    assert resoudre_modele("haiku") == "claude-haiku-5-5"
    assert resoudre_modele("claude-opus-5-5") == "claude-opus-5-5"
    assert resoudre_modele("") is None


def test_environnement_propre() -> None:
    env = environnement_propre(
        {
            "PATH": "p",
            "ANTHROPIC_API_KEY": "k",
            "anthropic_api_key": "k",
            "POSTGRES_USER": "u",
            "JARVIS2_APP_MOT_DE_PASSE": "m",
            "GEMINI_API_KEY": "g",
            "OPENROUTER_API_KEY": "o",
            "DATABASE_URL": "d",
            "USERPROFILE": "c",
        }
    )
    assert env == {"PATH": "p", "USERPROFILE": "c"}


def test_prompt_coupe_l_historique_le_plus_ancien() -> None:
    messages = [Message("systeme", "S")]
    for i in range(50):
        messages += [Message("utilisateur", f"question {i} " + "a" * 3000), Message("assistant", f"réponse {i}")]
    messages.append(Message("utilisateur", "dernière"))
    prompt = construire_prompt(messages, limite=20_000)
    assert len(prompt) <= 20_000
    assert prompt.startswith("<consignes_systeme>\nS\n</consignes_systeme>")
    assert prompt.endswith("Nouveau message de l'utilisateur :\ndernière\n")
    assert "question 49" in prompt and "question 0 " not in prompt
    assert "JARVIS : réponse 49" in prompt


def test_prompt_exige_un_dernier_message_utilisateur() -> None:
    with pytest.raises(ErreurMoteur):
        construire_prompt([Message("assistant", "x")])


def test_morceau_texte() -> None:
    assert (
        morceau_texte(
            {
                "type": "stream_event",
                "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "a"}},
            }
        )
        == "a"
    )
    assert morceau_texte({"type": "stream_event", "event": {"type": "message_start"}}) is None
    assert morceau_texte({"type": "assistant"}) is None


async def test_sante_et_modeles(tmp_path: Path) -> None:
    m = moteur(tmp=tmp_path)
    sante = await m.health()
    assert sante.disponible and "9.9.9" in sante.detail
    ids = [x.id for x in await m.list_models()]
    assert ids == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-2"]


async def test_cli_introuvable() -> None:
    m = MoteurClaudeCode(commande=["introuvable-jarvis2-xyz"])
    assert not (await m.health()).disponible
    with pytest.raises(ErreurMoteur, match="introuvable"):
        await m.generate(MESSAGES)
