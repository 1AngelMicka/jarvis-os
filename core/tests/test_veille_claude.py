"""Phase 13, lot I : veille des sessions Claude Code de l'utilisateur (lecture seule, désactivée par défaut)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from jarvis2.ateliers.veille import (
    EtatSession,
    SourceFichiersEtat,
    VeilleClaudeCode,
    fichier_autorise,
    interpreter,
)
from jarvis2.db import Base

BASE = {
    "pid": 1,
    "sessionId": "abc",
    "cwd": "/projets/demo",
    "kind": "interactive",
    "statusUpdatedAt": 1_760_000_000_000,
}


def etat(**champs: Any) -> str | None:
    s = interpreter({**BASE, **champs})
    return s.etat if s else None


def test_format_interne_interprete() -> None:
    assert etat(status="busy") == "travaille"
    assert etat(status="idle") == "vous_attend"
    assert etat(status="waiting", waitingFor="approve Bash: npm test") == "permission"
    assert etat(status="waiting", waitingFor="sandbox request") == "permission"
    assert etat(status="waiting", waitingFor="input needed") == "vous_attend"
    assert etat(status="busy", state="blocked", needs="login required") == "bloquee"
    assert etat(status="inédit") == "inconnu"
    assert etat(status="busy", kind="background") is None  # sessions de fond : pas celles de l'utilisateur
    assert interpreter({"status": "busy"}) is None
    assert interpreter(["pas", "un", "objet"]) is None
    s = interpreter({**BASE, "status": "waiting", "waitingFor": "approve Edit: a.py", "name": "Ma session"})
    assert s is not None and s.nom == "Ma session" and s.projet == "demo" and s.detail == "approve Edit: a.py"
    assert s.depuis == datetime.fromtimestamp(1_760_000_000, UTC)
    # Les identifiants de compte ou d'organisation que le fichier peut contenir ne sont jamais repris
    s = interpreter({**BASE, "status": "idle", "ownerAccountUuid": "secret", "ownerOrganizationUuid": "secret"})
    assert s is not None and "secret" not in json.dumps(s.en_dict())


def test_seuls_les_fichiers_d_etat_sont_lus() -> None:
    assert fichier_autorise(Path("1234.json"))
    for interdit in ("1234.abcdef.key", ".credentials.json", "jeton.json", "1234.json.bak", "1234"):
        assert not fichier_autorise(Path(interdit)), interdit


def test_source_lecture_seule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dossier = tmp_path / "sessions"
    dossier.mkdir()
    (dossier / "10.json").write_text(json.dumps({**BASE, "pid": 10, "status": "busy"}), encoding="utf-8")
    (dossier / "11.json").write_text(json.dumps({**BASE, "pid": 11, "sessionId": "morte"}), encoding="utf-8")
    (dossier / "12.json").write_text("{ en cours d'écri", encoding="utf-8")
    (dossier / "10.0123abcd.key").write_text("CLE-SECRETE", encoding="utf-8")
    (dossier / ".credentials.json").write_text("{}", encoding="utf-8")
    avant = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in dossier.iterdir()}
    ouverts: list[str] = []
    ouvrir = Path.open

    def espion(self: Path, *args: Any, **kwargs: Any) -> Any:
        ouverts.append(self.name)
        mode = args[0] if args else kwargs.get("mode", "r")
        assert "w" not in mode and "a" not in mode and "+" not in mode, "écriture interdite"
        return ouvrir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", espion)
    source = SourceFichiersEtat(dossier, vivant=lambda pid: pid in (10, 12))
    sessions = source.lire()
    monkeypatch.undo()
    assert [(s.ident, s.etat) for s in sessions] == [("abc", "travaille")]
    assert sorted(ouverts) == ["10.json", "12.json"]  # ni la clé, ni les identifiants, ni la session fermée
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in dossier.iterdir()} == avant
    assert SourceFichiersEtat(tmp_path / "absent").lire() == []


class FauxSource:
    def __init__(self) -> None:
        self.etats: list[EtatSession] = []
        self.lectures = 0

    def lire(self) -> list[EtatSession]:
        self.lectures += 1
        return list(self.etats)


def session(etat: str, ident: str = "s1", dossier: str = "/projets/demo", nom: str = "Demo") -> EtatSession:
    return EtatSession(ident, nom, dossier, etat)  # type: ignore[arg-type]


@pytest.mark.base
async def test_veille_desactivee_par_defaut_puis_alertes(pool: Base, tmp_path: Path) -> None:
    source = FauxSource()
    veille = VeilleClaudeCode(pool, source, exclure=lambda t: "secret" in t.lower(), ignorer_dossiers=[tmp_path])
    await veille.charger()
    assert not veille.actif
    source.etats = [session("travaille")]
    assert await veille.sonder() == [] and source.lectures == 0  # désactivée : rien n'est lu

    await veille.regler(actif=True, voix=True)
    relue = VeilleClaudeCode(pool, source)
    await relue.charger()
    assert relue.reglages == {"actif": True, "voix": True, "notification": True}

    assert await veille.sonder() == []  # première lecture : une session qui travaille ne s'annonce pas
    source.etats = [
        session("vous_attend"),
        session("permission", "s2", "/projets/Projet-Secret"),  # sujet exclu : ni montré ni annoncé
        session("permission", "s3", str(tmp_path / "demo" / "abcd")),  # worktree d'un atelier de JARVIS
    ]
    (alerte,) = await veille.sonder()
    assert alerte.texte == "Claude Code a fini et vous attend dans « Demo »."
    assert [s.ident for s in veille.sessions] == ["s1"]
    source.etats = [session("permission")]
    (alerte,) = await veille.sonder()
    assert "permission" in alerte.texte and alerte.id == 2
    assert [a["id"] for a in veille.alertes_apres(1)] == [2]
    assert await veille.sonder() == []  # même état : rien de nouveau
    assert veille.resume() == (
        "Sessions Claude Code de l'utilisateur (veille en lecture seule) : "
        "« Demo » (demo) : bloquée sur une permission."
    )

    await veille.regler(actif=False)
    assert veille.sessions == [] and veille.resume() == "" and not veille.alertes_apres(0)
