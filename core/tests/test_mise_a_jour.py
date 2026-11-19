"""Mise à jour du Core : numéros de version, indicateur 1×/jour désactivable, commande `jarvis2 mettre-a-jour`.

L'API GitHub est toujours SIMULÉE (httpx.MockTransport) ; tout vrai transport réseau est interdit pendant ces tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis2 import __version__, mise_a_jour
from jarvis2.db import Base
from jarvis2.mise_a_jour import (
    ErreurVersions,
    ServiceMisesAJour,
    analyser_version,
    commande_maj,
    detecter_methode,
    lire_publication,
    mettre_a_jour,
    plus_recente,
    tronquer,
)

ROUE = "https://github.com/1AngelMicka/jarvis-os/releases/download/v99.0.0/jarvis2-99.0.0-py3-none-any.whl"


@pytest.fixture(autouse=True)
def sans_reseau(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aucun appel réseau réel : le vrai transport httpx échoue le test s'il est utilisé."""

    async def interdit(self: Any, requete: httpx.Request) -> httpx.Response:
        raise AssertionError(f"appel réseau réel interdit : {requete.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", interdit)


def reponse_github(tag: str = "v99.0.0", **extra: Any) -> dict[str, Any]:
    return {
        "tag_name": tag,
        "name": f"JARVIS 2 {tag}",
        "body": "## Nouveautés\n- Mise à jour depuis les Réglages\n<script>alert(1)</script>",
        "html_url": f"https://github.com/1AngelMicka/jarvis-os/releases/tag/{tag}",
        "published_at": "2026-11-10T09:00:00Z",
        "assets": [
            {"name": "JARVIS2_setup.exe", "browser_download_url": ROUE.replace(".whl", ".exe")},
            {"name": "jarvis2-99.0.0-py3-none-any.whl", "browser_download_url": ROUE},
        ],
        **extra,
    }


class FauxGitHub:
    def __init__(self, statut: int = 200, corps: Any = None, entetes: dict[str, str] | None = None) -> None:
        self.statut, self.corps, self.entetes = statut, corps if corps is not None else reponse_github(), entetes or {}
        self.appels: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def repondre(requete: httpx.Request) -> httpx.Response:
            self.appels.append(requete)
            return httpx.Response(self.statut, json=self.corps, headers=self.entetes)

        return httpx.MockTransport(repondre)


def hors_ligne() -> httpx.MockTransport:
    def repondre(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("hors ligne", request=requete)

    return httpx.MockTransport(repondre)


# --- Numéros de version ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("candidate", "installee", "attendu"),
    [
        ("v0.9.0", "0.8.0", True),
        ("0.8.1", "0.8.0", True),
        ("0.10.0", "0.9.0", True),  # comparaison numérique, pas alphabétique
        ("1.0", "0.99.99", True),
        ("v0.8.0", "0.8.0", False),
        ("0.8", "0.8.0", False),  # zéros de fin sans effet
        ("0.7.9", "0.8.0", False),
        ("1.0.0-rc.1", "1.0.0", False),  # une préversion passe avant la version finale
        ("1.0.0", "1.0.0-rc.1", True),
        ("1.0.0+build.5", "1.0.0", False),
        ("nightly", "0.8.0", False),  # illisible : jamais « nouvelle »
        ("", "0.8.0", False),
        (None, "0.8.0", False),
    ],
)
def test_plus_recente(candidate: str | None, installee: str, attendu: bool) -> None:
    assert plus_recente(candidate, installee) is attendu


def test_analyser_version() -> None:
    assert analyser_version("v0.9.0") == ((0, 9), (1, ""))
    assert analyser_version("V1.2.3-beta") == ((1, 2, 3), (0, "beta"))
    assert analyser_version("version 2") is None


def test_tronquer() -> None:
    assert tronquer("court", 100) == "court"
    texte = "ligne une\n" + "mot " * 200
    coupe = tronquer(texte, 50)
    assert len(coupe) <= 52 and coupe.endswith(" …") and not coupe[:-2].endswith(" ")


def test_lire_publication_verifie_les_adresses() -> None:
    pub = lire_publication(reponse_github())
    assert pub.version == "99.0.0" and pub.roue == ROUE and pub.publiee_le == "2026-11-10T09:00:00Z"
    # Adresses étrangères au dépôt (ou chargées de caractères de commande) : ignorées
    piege = reponse_github(
        html_url="https://exemple.invalid/page",
        assets=[
            {"name": "a.whl", "browser_download_url": "https://exemple.invalid/jarvis2.whl"},
            {"name": "b.whl", "browser_download_url": ROUE + "'; Remove-Item x; '"},
        ],
    )
    pub = lire_publication(piege)
    assert pub.url == mise_a_jour.URL_VERSIONS and pub.roue is None
    with pytest.raises(ErreurVersions):
        lire_publication({"tag_name": "nightly"})


# --- API GitHub simulée ----------------------------------------------------------------------------------------------


async def test_requete_sans_jeton_et_user_agent_generique() -> None:
    gh = FauxGitHub()
    pub = await mise_a_jour.derniere_publication(gh.transport())
    assert pub.version == "99.0.0"
    (requete,) = gh.appels
    assert str(requete.url) == "https://api.github.com/repos/1AngelMicka/jarvis-os/releases/latest"
    assert requete.headers["user-agent"] == "jarvis2"
    assert "authorization" not in requete.headers


@pytest.mark.parametrize(
    ("statut", "entetes", "message"),
    [
        (403, {"x-ratelimit-remaining": "0"}, "limite de débit"),
        (429, {}, "limite de débit"),
        (404, {}, "aucune version publiée"),
        (500, {}, "code 500"),
    ],
)
async def test_erreurs_github(statut: int, entetes: dict[str, str], message: str) -> None:
    with pytest.raises(ErreurVersions, match=message):
        await mise_a_jour.derniere_publication(FauxGitHub(statut, {"message": "x"}, entetes).transport())


async def test_hors_ligne() -> None:
    with pytest.raises(ErreurVersions, match="injoignable"):
        await mise_a_jour.derniere_publication(hors_ligne())


# --- Indicateur : au plus une fois par jour, désactivable -----------------------------------------------------------


class Horloge:
    def __init__(self) -> None:
        self.maintenant = datetime(2026, 11, 19, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.maintenant


async def test_verification_une_fois_par_jour(pool: Base) -> None:
    gh, horloge = FauxGitHub(), Horloge()
    service = ServiceMisesAJour(pool, gh.transport(), horloge)
    etat = await service.decrire()
    assert len(gh.appels) == 1
    assert etat["active"] is True and etat["installee"] == __version__
    assert etat["derniere"] == "99.0.0" and etat["nouvelle"] is True
    assert etat["url"] == "https://github.com/1AngelMicka/jarvis-os/releases/tag/v99.0.0"
    assert "<script>" in etat["notes"]  # texte brut : l'interface l'affiche tel quel, sans l'interpréter
    assert etat["verifie_le"] == "2026-11-19T08:00:00+00:00" and etat["commande"] == "jarvis2 mettre-a-jour"
    # Même jour, et même après un redémarrage (date gardée en base) : aucun nouvel appel
    horloge.maintenant += timedelta(hours=23)
    await service.decrire()
    assert (await ServiceMisesAJour(pool, gh.transport(), horloge).decrire())["nouvelle"] is True
    assert len(gh.appels) == 1
    # Le lendemain : une nouvelle vérification
    horloge.maintenant += timedelta(hours=1)
    await service.decrire()
    assert len(gh.appels) == 2


async def test_pas_de_nouvelle_version(pool: Base) -> None:
    gh = FauxGitHub(corps=reponse_github(tag=f"v{__version__}"))
    etat = await ServiceMisesAJour(pool, gh.transport()).decrire()
    assert etat["derniere"] == __version__ and etat["nouvelle"] is False


async def test_echec_pas_reessaye_le_meme_jour(pool: Base) -> None:
    horloge = Horloge()
    gh = FauxGitHub(403, {"message": "rate limit"}, {"x-ratelimit-remaining": "0"})
    service = ServiceMisesAJour(pool, gh.transport(), horloge)
    etat = await service.decrire()
    assert "limite de débit" in etat["erreur"] and etat["derniere"] is None and etat["nouvelle"] is False
    await service.decrire()
    assert len(gh.appels) == 1


async def test_desactivee_aucun_appel(pool: Base) -> None:
    gh = FauxGitHub()
    service = ServiceMisesAJour(pool, gh.transport())
    etat = await service.regler(False)
    assert etat["active"] is False and etat["nouvelle"] is False and etat["derniere"] is None
    assert (await service.decrire())["active"] is False
    assert gh.appels == []
    # Réactivée : vérifie tout de suite
    etat = await service.regler(True)
    assert etat["active"] is True and etat["nouvelle"] is True and len(gh.appels) == 1


# --- Commande `jarvis2 mettre-a-jour` --------------------------------------------------------------------------------


class Lanceur:
    def __init__(self, code: int = 0) -> None:
        self.code = code
        self.commandes: list[list[str]] = []

    def __call__(self, commande: list[str]) -> int:
        self.commandes.append(commande)
        return self.code


def _commande(oui: bool = False, reponse: str = "", **options: Any) -> tuple[int, Lanceur]:
    lanceur = Lanceur(options.pop("code", 0))
    options.setdefault("transport", FauxGitHub().transport())
    options.setdefault("methode", "uv")
    code = mettre_a_jour(
        oui, demander=lambda _q: reponse, executer=lanceur, trouver=lambda nom: f"/bin/{nom}", **options
    )
    return code, lanceur


def test_refus_rien_lance(capsys: pytest.CaptureFixture[str]) -> None:
    for reponse in ("", "n", "non", "peut-être"):
        code, lanceur = _commande(reponse=reponse)
        assert code == 0 and lanceur.commandes == []
    sortie = capsys.readouterr().out
    assert "Nouvelle version disponible : 99.0.0 (publiée le 2026-11-10)" in sortie
    assert "Mise à jour depuis les Réglages" in sortie and "Rien n'a été modifié." in sortie


def test_sans_terminal_vaut_refus() -> None:
    def ferme(_q: str) -> str:
        raise EOFError

    lanceur = Lanceur()
    code = mettre_a_jour(
        transport=FauxGitHub().transport(), demander=ferme, executer=lanceur, methode="uv", trouver=lambda n: n
    )
    assert code == 0 and lanceur.commandes == []


def test_accord_uv_installe_la_roue_de_la_version() -> None:
    code, lanceur = _commande(reponse="o")
    assert code == 0
    assert lanceur.commandes == [["uv", "tool", "install", "--force", "--python", "3.13", ROUE]]


def test_option_oui_et_pipx() -> None:
    code, lanceur = _commande(oui=True, methode="pipx")
    assert code == 0 and lanceur.commandes == [["pipx", "install", "--force", "--python", "3.13", ROUE]]


def test_echec_de_la_commande() -> None:
    code, _ = _commande(oui=True, code=1)
    assert code == 3


@pytest.mark.parametrize("methode", ["developpement", "inconnue"])
def test_developpement_ou_inconnue_rien_lance(methode: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, lanceur = _commande(oui=True, methode=methode)
    assert code == 0 and lanceur.commandes == []
    sortie = capsys.readouterr().out
    assert ("git pull" in sortie) if methode == "developpement" else ("uv tool install --force" in sortie)


def test_programme_introuvable_rien_lance() -> None:
    lanceur = Lanceur()
    code = mettre_a_jour(
        True, transport=FauxGitHub().transport(), executer=lanceur, methode="uv", trouver=lambda _n: None
    )
    assert code == 0 and lanceur.commandes == []


def test_hors_ligne_rien_lance(capsys: pytest.CaptureFixture[str]) -> None:
    code, lanceur = _commande(oui=True, transport=hors_ligne())
    assert code == 1 and lanceur.commandes == []
    assert "Impossible de vérifier la dernière version" in capsys.readouterr().out


def test_deja_a_jour(capsys: pytest.CaptureFixture[str]) -> None:
    code, lanceur = _commande(oui=True, transport=FauxGitHub(corps=reponse_github(tag=f"v{__version__}")).transport())
    assert code == 0 and lanceur.commandes == []
    assert "est à jour" in capsys.readouterr().out


def test_detecter_methode(tmp_path: Path) -> None:
    paquet = tmp_path / "site-packages" / "jarvis2"
    paquet.mkdir(parents=True)
    uv = tmp_path / "uv" / "tools" / "jarvis2"
    assert detecter_methode(uv, paquet) == "uv"
    recu = tmp_path / "ailleurs"
    recu.mkdir()
    (recu / "uv-receipt.toml").write_text("[tool]\n", encoding="utf-8")
    assert detecter_methode(recu, paquet) == "uv"
    assert detecter_methode(tmp_path / "pipx" / "venvs" / "jarvis2", paquet) == "pipx"
    assert detecter_methode(tmp_path / "venv", paquet) == "inconnue"
    depot = tmp_path / "core"
    (depot / "jarvis2").mkdir(parents=True)
    (depot / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    assert detecter_methode(depot / ".venv", depot / "jarvis2") == "developpement"
    assert commande_maj("developpement", ROUE) is None


def test_commande_cli_branchee(monkeypatch: pytest.MonkeyPatch) -> None:
    from jarvis2.__main__ import main

    vus: list[bool] = []

    def faux(oui: bool) -> int:
        vus.append(oui)
        return 0

    monkeypatch.setattr(mise_a_jour, "mettre_a_jour", faux)
    assert main(["mettre-a-jour", "--oui"]) == 0 and vus == [True]
