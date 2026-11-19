"""Lot K3 : transcription robuste, reconnaissance du propriétaire, fin de tour, latence, dictée."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from jarvis2 import dictee, fin_tour, latence, proprietaire, transcription
from jarvis2.api import Contexte, creer_app
from jarvis2.config import Parametres
from jarvis2.db import Base
from jarvis2.securite import appareils
from jarvis2.securite.permissions import ErreurAction
from jarvis2.telechargements import ModeleAbsent
from jarvis2.transcription import (
    Appareil,
    Disjoncteur,
    Segment,
    TranscripteurRobuste,
    TranscriptionEnPause,
    detecter_appareil,
    filtrer,
)

from .test_agents import systeme
from .test_connecteurs import Faux

# --- Appareil ---------------------------------------------------------------------------------------------


def test_appareil_detecte() -> None:
    assert detecter_appareil("cpu", lambda: (1, {"int8"}), lambda: "nvidia").famille == "processeur"
    cuda = detecter_appareil("auto", lambda: (1, {"int8", "int8_float16"}), lambda: "nvidia")
    assert (cuda.famille, cuda.device, cuda.type_calcul) == ("cuda", "cuda", "int8_float16")
    rocm = detecter_appareil("auto", lambda: (1, {"int8"}), lambda: "amd")
    assert (rocm.famille, rocm.type_calcul) == ("rocm", "int8")
    sans = detecter_appareil("auto", lambda: (0, set()), lambda: "amd")
    assert sans.famille == "processeur" and sans.raison and "ROCm" in sans.raison
    assert detecter_appareil("auto", lambda: (0, set()), lambda: None).raison is None


# --- Filtres ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "texte",
    [
        "Sous-titres réalisés par la communauté d'Amara.org",
        "Sous-titrage ST' 501",
        "Sous-titrage Société Radio-Canada",
        "Merci d'avoir regardé cette vidéo !",
        "N'oubliez pas de vous abonner.",
        "Thank you for watching.",
        "Conversation en français avec Jarvis, l'assistant personnel.",
        "...",
    ],
)
def test_hallucinations_ecartees(texte: str) -> None:
    assert transcription.est_hallucination(texte)
    assert filtrer([Segment(texte)], 3.0)[0] == ""


def test_filtres_gardent_la_vraie_parole() -> None:
    texte, ecartes = filtrer(
        [
            Segment(" Allume la lumière du salon."),
            Segment(" Sous-titres réalisés par la communauté d'Amara.org"),
            Segment(" euh", sans_parole=0.9, log_prob=-1.2),
            Segment(" la la la la la la la la", compression=3.1),
        ],
        2.5,
    )
    assert texte == "Allume la lumière du salon."
    assert len(ecartes) == 3
    assert transcription.sans_repetitions("oui oui oui oui oui") == "oui"
    assert transcription.sans_repetitions("merci beaucoup, merci beaucoup, merci beaucoup, merci beaucoup") == (
        "merci beaucoup"
    )
    assert filtrer([Segment("Merci.")], 0.3)[0] == ""  # mot isolé sur un bruit
    assert filtrer([Segment("Merci.")], 1.2)[0] == "Merci."  # vraiment dit


# --- Disjoncteur ------------------------------------------------------------------------------------------


def test_disjoncteur() -> None:
    temps = [0.0]
    d = Disjoncteur(seuil=3, pause=60, horloge=lambda: temps[0])
    for _ in range(3):
        d.avant()
        d.echec(RuntimeError("panne"))
    with pytest.raises(TranscriptionEnPause) as err:
        d.avant()
    assert "60 s" in str(err.value) and d.en_dict()["ouvert"]
    temps[0] = 61
    d.avant()  # un essai à la fin de la pause
    d.echec(RuntimeError("encore"))
    with pytest.raises(TranscriptionEnPause):
        d.avant()  # un nouvel échec rouvre tout de suite
    temps[0] = 200
    d.avant()
    d.succes()
    assert d.en_dict() == {"ouvert": False, "reste_s": None, "echecs": 0, "derniere_erreur": "RuntimeError : encore"}


# --- Transcripteur ----------------------------------------------------------------------------------------


class FauxSegment:
    def __init__(self, text: str) -> None:
        self.text = text
        self.no_speech_prob = 0.01
        self.avg_logprob = -0.2
        self.compression_ratio = 1.2


class FauxModele:
    def __init__(self, textes: list[str] | None = None, echecs: int = 0) -> None:
        self.textes = textes or ["Bonjour Jarvis."]
        self.echecs = echecs
        self.appels = 0

    def transcribe(self, audio: Any, **options: Any) -> tuple[Any, Any]:
        self.appels += 1
        if self.echecs:
            self.echecs -= 1
            raise RuntimeError("cublas64_12.dll introuvable")
        texte = self.textes[min(self.appels - 1, len(self.textes) - 1)]
        return iter([FauxSegment(texte)]), type("Info", (), {"language": "fr"})()


def decodeur(audio: bytes) -> Any:
    """1 octet = 0,1 s ; « P » = parole, autre = silence."""
    return np.concatenate([np.full(1600, 0.5 if o == ord("P") else 0.0, dtype=np.float32) for o in audio])


def vad(echantillons: Any) -> list[tuple[int, int]]:
    plages, debut = [], None
    for i in range(0, len(echantillons), 1600):
        parle = echantillons[i] > 0.1
        if parle and debut is None:
            debut = i
        if not parle and debut is not None:
            plages.append((debut, i))
            debut = None
    if debut is not None:
        plages.append((debut, len(echantillons)))
    return plages


def robuste(
    tmp_path: Path,
    modeles: dict[str, FauxModele],
    appareil: Appareil | None = None,
    echec_carte: bool = False,
) -> TranscripteurRobuste:
    def chargeur(source: Path | str, a: Appareil, cache: Path) -> FauxModele:
        if a.device == "cuda" and echec_carte:
            raise RuntimeError("CUDA indisponible")
        return modeles[a.device]

    t = TranscripteurRobuste(
        tmp_path, "small", chargeur=chargeur, vad=vad, detecteur=lambda v: appareil or transcription.PROCESSEUR,
        decodeur=decodeur,
    )  # fmt: skip
    t._source = lambda: tmp_path  # type: ignore[method-assign]
    return t


async def test_sans_parole_whisper_n_est_pas_appele(tmp_path: Path) -> None:
    m = FauxModele()
    t = robuste(tmp_path, {"cpu": m})
    r = await t.transcrire_detail(b"....")
    assert r.texte == "" and r.ecartes == ["aucune parole (VAD)"] and m.appels == 0
    assert await t.transcrire(b"PPPPPP") == ("Bonjour Jarvis.", "fr")


async def test_repli_sur_le_processeur(tmp_path: Path) -> None:
    carte = Appareil("cuda", "cuda", "int8_float16")
    cpu = FauxModele(["Sur le processeur."])
    t = robuste(tmp_path, {"cpu": cpu}, carte, echec_carte=True)
    assert (await t.transcrire_detail(b"PPPPP")).texte == "Sur le processeur."
    assert t.appareil is not None and t.appareil.famille == "processeur" and "carte" in (t.appareil.raison or "")
    # La carte se charge mais échoue au calcul (bibliothèques CUDA absentes) : la phrase n'est pas perdue
    gpu = FauxModele(["Carte."], echecs=1)
    t2 = robuste(tmp_path, {"cuda": gpu, "cpu": FauxModele(["Repli."])}, carte)
    assert (await t2.transcrire_detail(b"PPPPP")).texte == "Repli."
    assert t2.appareil is not None and t2.appareil.device == "cpu"


async def test_disjoncteur_du_transcripteur(tmp_path: Path) -> None:
    t = robuste(tmp_path, {"cpu": FauxModele(echecs=10)})
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await t.transcrire_detail(b"PPPP")
    with pytest.raises(TranscriptionEnPause):
        await t.transcrire_detail(b"PPPP")
    assert t.etat()["disjoncteur"]["ouvert"]
    # Le modèle absent n'ouvre pas le disjoncteur
    t2 = robuste(tmp_path, {"cpu": FauxModele()})

    def absent() -> Path:
        raise ModeleAbsent("non téléchargé")

    t2._source = absent  # type: ignore[method-assign]
    for _ in range(4):
        with pytest.raises(ModeleAbsent):
            await t2.transcrire_detail(b"PPPP")
    assert t2.disjoncteur.echecs == 0


async def test_transcription_anticipee(tmp_path: Path) -> None:
    m = FauxModele(["Quelle heure est-il ?", "Quelle heure est-il à Tokyo ?"])
    t = robuste(tmp_path, {"cpu": m})
    a = await t.transcrire_detail(b"PPPPPP..", anticipation=True)
    assert a.texte == "Quelle heure est-il ?" and m.appels == 1
    # Fin de l'enregistrement : seulement du silence en plus → texte déjà prêt, Whisper pas rappelé
    r = await t.transcrire_detail(b"PPPPPP.....")
    assert r.anticipe and r.texte == "Quelle heure est-il ?" and m.appels == 1
    assert (await t.transcrire_detail(b"PPPPPP..")).anticipe  # même enregistrement
    # La personne a repris la parole : nouvelle transcription
    r2 = await t.transcrire_detail(b"PPPPPP..PPPP.")
    assert not r2.anticipe and r2.texte == "Quelle heure est-il à Tokyo ?" and m.appels == 2
    # Un autre enregistrement ne reprend jamais le texte anticipé
    assert not (await t.transcrire_detail(b"PP.PPPP")).anticipe


async def test_prechauffage(tmp_path: Path) -> None:
    m = FauxModele()
    t = robuste(tmp_path, {"cpu": m})
    assert not t.etat()["prechauffe"]
    await t.prechauffer()
    assert t.etat()["prechauffe"] and t.etat()["charge"] and m.appels == 1


# --- Fin de tour ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texte", "fini"),
    [
        ("Quelle heure est-il ?", True),
        ("Qu'est-ce qu'il y a ?", True),
        ("Allume la lumière du salon.", True),
        ("Je voudrais que tu", False),
        ("Ajoute du lait et", False),
        ("Rappelle-moi demain, euh", False),
        ("Envoie un message à…", False),
        ("", False),
    ],
)
def test_regle_de_fin_de_tour(texte: str, fini: bool) -> None:
    assert fin_tour.regle(texte).fini is fini


async def test_petit_modele_de_fin_de_tour() -> None:
    recus: list[dict[str, Any]] = []

    def repondre(requete: httpx.Request) -> httpx.Response:
        recus.append(json.loads(requete.content))
        return httpx.Response(200, json={"response": "oui"})

    juge = fin_tour.JugeFinDeTour("http://127.0.0.1:11434", "qwen3:0.6b")
    juge.transport = httpx.MockTransport(repondre)
    r = await fin_tour.evaluer("Mets de la musique", juge)  # la règle hésite : le petit modèle tranche
    assert r.fini and r.juge == "qwen3:0.6b"
    assert recus[0]["keep_alive"] == fin_tour.KEEP_ALIVE and recus[0]["think"] is False
    assert (await fin_tour.evaluer("Quelle heure est-il ?", juge)).juge is None  # règle sûre : pas d'appel
    assert len(recus) == 1

    def arrete(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé")

    juge.transport = httpx.MockTransport(arrete)  # Ollama arrêté : jamais démarré, la règle décide
    r = await fin_tour.evaluer("Mets de la musique", juge)
    assert r.juge is None and "sans réponse" in r.raison


# --- Latence ----------------------------------------------------------------------------------------------


async def test_latence_ollama() -> None:
    assert latence.verifier_adresse("http://localhost:11434").statut == "attention"
    assert latence.verifier_adresse("http://127.0.0.1:11434").statut == "ok"
    vus: list[str] = []

    def ollama(requete: httpx.Request) -> httpx.Response:
        vus.append(f"{requete.method} {requete.url.path}")
        if requete.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.12"})
        if requete.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "qwen3:8b", "expires_at": "2999-01-01T00:00:00Z"}]})
        if requete.url.path == "/api/generate":
            if b'"stream":true' in requete.content.replace(b" ", b""):
                lignes = '{"response":""}\n{"response":"D\'accord"}\n{"done":true}\n'
                return httpx.Response(200, content=lignes.encode())
            return httpx.Response(200, json={"done": True})
        return httpx.Response(404)

    legeres = await latence.mesurer_ollama("http://127.0.0.1:11434", None, False, httpx.MockTransport(ollama))
    assert [v.id for v in legeres] == ["latence.ollama", "latence.memoire"]
    assert "qwen3:8b" in legeres[1].detail and all(not v.startswith("POST") for v in vus)  # rien chargé
    completes = await latence.mesurer_ollama("http://127.0.0.1:11434", None, True, httpx.MockTransport(ollama))
    assert [v.id for v in completes][-2:] == ["latence.prechauffage", "latence.premier_mot"]
    assert "premier mot" in completes[-1].detail

    def arrete(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé")

    hors = await latence.mesurer_ollama("http://127.0.0.1:11434", None, True, httpx.MockTransport(arrete))
    assert len(hors) == 1 and hors[0].statut == "info" and "jamais" in hors[0].detail


async def test_latence_whisper(tmp_path: Path) -> None:
    t = robuste(tmp_path, {"cpu": FauxModele()})
    absent = await latence.mesurer_whisper(t, False)
    assert "non téléchargé" in absent[0].detail
    t.etat = lambda: {  # type: ignore[method-assign]
        **TranscripteurRobuste.etat(t), "telecharge": True,
    }  # fmt: skip
    leger = await latence.mesurer_whisper(t, False)
    assert "--latence" in leger[0].detail and not t.prechauffe
    complet = await latence.mesurer_whisper(t, True)
    assert complet[0].statut == "ok" and "préchauffage" in complet[0].detail and t.prechauffe


# --- Dictée -----------------------------------------------------------------------------------------------


def test_dictee_mise_en_forme() -> None:
    assert dictee.ponctuation_dite("bonjour virgule ça va point d'interrogation") == "bonjour, ça va ?"
    assert dictee.ponctuation_dite("première ligne à la ligne deuxième") == "première ligne\ndeuxième"
    corrections = dictee.valider_corrections([{"de": "jarvice", "vers": "JARVIS"}, {"de": "Jarvice", "vers": "x"}])
    assert corrections == [{"de": "jarvice", "vers": "JARVIS"}]  # doublon écarté
    assert dictee.corriger("Dis Jarvice, ouvre jarvicette", corrections) == "Dis JARVIS, ouvre jarvicette"
    assert dictee.corriger("Écrit à Éloïse", [{"de": "eloise", "vers": "Éloïse B."}]) == "Écrit à Éloïse B."
    assert dictee.mettre_en_forme("bonjour à tous", "phrase") == "Bonjour à tous."
    assert dictee.mettre_en_forme("on se voit demain.", "message") == "On se voit demain"
    assert dictee.mettre_en_forme("Git status.", "code") == "git status"
    assert dictee.mettre_en_forme("API REST.", "code") == "API REST"
    assert dictee.style_pour("C:\\Programmes\\Code.exe", {}) == "code"
    assert dictee.style_pour("discord.exe", {}) == "message"
    assert dictee.style_pour("inconnu.exe", {"inconnu.exe": "brut"}) == "brut"
    assert dictee.style_pour(None, {}) == "phrase"


# --- Reconnaissance du propriétaire ------------------------------------------------------------------------


def test_fbank() -> None:
    signal = np.sin(np.linspace(0, 2000 * np.pi, 16000)).astype(np.float32) * 0.3
    f = proprietaire.fbank(signal)
    assert f.shape == (98, 80) and abs(float(f.mean())) < 1e-3
    assert proprietaire.cosinus(np.array([1.0, 0.0]), np.array([1.0, 0.0])) == pytest.approx(1.0)


class FauxEmpreinteur:
    """La « voix » est le niveau moyen de l'extrait : 0,5 = propriétaire, 0,2 = quelqu'un d'autre."""

    def __init__(self, present: bool = True) -> None:
        self.present = present

    def disponible(self) -> tuple[bool, str | None]:
        return (True, None) if self.present else (False, "modèle de reconnaissance non téléchargé")

    def empreinte(self, echantillons: Any) -> Any:
        v = float(np.mean(echantillons))
        vecteur = np.array([v, 1 - v * 2, 0.1], dtype=np.float32)
        return vecteur / np.linalg.norm(vecteur)


def resultat(texte: str, niveau: float = 0.5, secondes: float = 4.0) -> transcription.Resultat:
    n = int(secondes * 16000)
    echantillons = np.full(n, niveau, dtype=np.float32)
    return transcription.Resultat(texte, "fr", secondes, secondes, [], False, {}, echantillons, [(0, n)])


@pytest.mark.base
async def test_proprietaire_ferme(pool: Base, tmp_path: Path) -> None:
    temps = [0.0]
    s = proprietaire.ServiceProprietaire(
        pool, tmp_path, tmp_path, empreinteur=FauxEmpreinteur(), horloge=lambda: temps[0]
    )
    etat = await s.etat()
    assert (
        etat["actif"] is False and etat["ferme"] is False and etat["raison"] == "aucune empreinte de voix enregistrée"
    )
    # Désactivée : rien ne change, même annoncé « à la voix »
    await s.garder("supprime la règle", "jaune", annoncee_voix=True)
    await s.regler(actif=True)
    assert (await s.etat())["ferme"] is True
    # Activée sans empreinte : toute demande 🟡🔴 dite à voix haute est refusée ; 🟢 et texte tapé passent
    await s.observer(resultat("Jarvis, supprime la règle de protection"))
    with pytest.raises(ErreurAction, match="indisponible"):
        await s.garder("supprime la règle de protection", "jaune")
    await s.garder("supprime la règle de protection", "vert")
    await s.garder("une phrase tapée au clavier", "rouge")
    with pytest.raises(ErreurAction, match="aucune vérification"):
        await s.garder("une phrase tapée au clavier", "rouge", annoncee_voix=True)
    # Inscription : 3 s de parole au moins, plusieurs empreintes
    with pytest.raises(ErreurAction, match="au moins"):
        await s.inscrire(resultat("", secondes=1.5))
    await s.inscrire(resultat(""))
    await s.inscrire(resultat("", niveau=0.48))
    assert len(s.empreintes()) == 2 and "vecteur" not in s.empreintes()[0]
    assert json.loads((tmp_path / "voix" / "empreintes.json").read_text(encoding="utf-8"))["empreintes"][0]["vecteur"]
    # Le propriétaire est reconnu ; une autre voix non ; une phrase trop courte non plus
    await s.observer(resultat("Supprime la règle « nuit »"))
    await s.garder("supprime la règle nuit", "jaune")
    await s.observer(resultat("Supprime toutes les règles", niveau=0.2))
    with pytest.raises(ErreurAction, match="pas été reconnue"):
        await s.garder("supprime toutes les règles", "rouge")
    await s.observer(resultat("Éteins tout", secondes=0.5))
    with pytest.raises(ErreurAction, match="trop courte"):
        await s.garder("éteins tout", "jaune")
    # L'attestation ne vaut que 2 minutes
    temps[0] = 200
    await s.garder("supprime toutes les règles", "rouge")  # plus vue comme venue de la voix
    # Modèle retiré : indisponible, donc fermée
    s.empreinteur = FauxEmpreinteur(present=False)
    await s.observer(resultat("Supprime la règle « nuit »"))
    with pytest.raises(ErreurAction, match="indisponible"):
        await s.garder("supprime la règle nuit", "jaune")
    ident = s.empreintes()[0]["id"]
    assert await s.retirer(ident) and not await s.retirer(ident)


# --- API --------------------------------------------------------------------------------------------------


async def client(
    pool: Base, tmp_path: Path, t: TranscripteurRobuste, hote: str = "localhost"
) -> tuple[httpx.AsyncClient, Contexte]:
    s = await systeme(pool, tmp_path, {"local": Faux("local", "local", externe=False)})
    ctx = Contexte(
        pool, s["depot"], s["connecteurs"].moteurs, s["service"], "local", connecteurs=s["connecteurs"],
        transcripteur=t, dossier_donnees=tmp_path, dossier_modeles=tmp_path,
    )  # fmt: skip
    ctx.proprietaire.empreinteur = FauxEmpreinteur()
    app = creer_app(Parametres(), ctx)
    app.state.ctx = ctx
    _, jeton = await appareils.creer(pool, "PC", "pc")
    c = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 50000)),
        base_url=f"http://{hote}:8765",
        headers={"Authorization": f"Bearer {jeton}"},
    )
    return c, ctx


@pytest.mark.base
async def test_api_transcription_et_fin_de_tour(pool: Base, tmp_path: Path) -> None:
    m = FauxModele(["Quelle heure est-il ?"])
    c, _ = await client(pool, tmp_path, robuste(tmp_path, {"cpu": m}))
    etat = (await c.get("/v1/voix/transcription")).json()
    assert etat["modele"] == "small" and etat["appareil"]["famille"] == "processeur"
    assert (await c.post("/v1/voix/prechauffer")).json()["prechauffe"] is True
    a = (await c.post("/v1/voix/anticipee", content=b"PPPPP..")).json()
    assert a["texte"] == "Quelle heure est-il ?" and a["fin_de_tour"]["fini"] is True
    appels = m.appels
    final = (await c.post("/v1/voix/transcrire", content=b"PPPPP....")).json()  # route existante, même cache
    assert final["texte"] == "Quelle heure est-il ?" and m.appels == appels
    assert (await c.post("/v1/voix/fin-de-tour", json={"texte": "Je voudrais que"})).json()["fini"] is False
    assert (await c.post("/v1/voix/anticipee", content=b"")).status_code == 422


@pytest.mark.base
async def test_api_proprietaire_refuse_a_la_voix(pool: Base, tmp_path: Path) -> None:
    c, _ = await client(pool, tmp_path, robuste(tmp_path, {"cpu": FauxModele()}))
    etat = (await c.get("/v1/voix/proprietaire")).json()
    assert etat["actif"] is False and etat["modele"]["id"] == "proprietaire"
    demande = {"action": "regle.supprimer", "parametres": {"regle_id": "00000000-0000-0000-0000-000000000001"}}
    voix = {"X-Jarvis-Voix": "1"}
    assert (await c.post("/v1/actions", json=demande, headers=voix)).json()["statut"] == "en_attente"
    etat = (await c.put("/v1/voix/proprietaire", json={"actif": True, "seuil": 0.6})).json()
    assert etat["actif"] and etat["seuil"] == 0.6 and etat["ferme"]
    refus = await c.post("/v1/actions", json=demande, headers=voix)
    assert refus.status_code == 422 and "refusée à la voix" in refus.json()["detail"]
    assert (await c.post("/v1/actions", json=demande)).json()["statut"] == "en_attente"  # à l'écran : possible
    # Empreinte : 3 s de parole au moins ; l'audio n'est pas gardé
    assert (await c.post("/v1/voix/proprietaire/empreintes", content=b"PPPPP")).status_code == 422
    ajout = (await c.post("/v1/voix/proprietaire/empreintes", content=b"P" * 40)).json()
    assert len(ajout["empreintes"]) == 1 and not ajout["ferme"]
    ident = ajout["empreinte"]["id"]
    assert (await c.delete(f"/v1/voix/proprietaire/empreintes/{ident}")).json()["empreintes"] == []
    assert (await c.delete(f"/v1/voix/proprietaire/empreintes/{ident}")).status_code == 404
    lignes = await pool.fetch("SELECT action FROM audit WHERE action LIKE 'voix.%' ORDER BY id")
    assert [r["action"] for r in lignes] == [
        "voix.proprietaire.regle",
        "voix.action_refusee",
        "voix.empreinte.ajoutee",
        "voix.empreinte.retiree",
    ]


@pytest.mark.base
async def test_api_dictee(pool: Base, tmp_path: Path) -> None:
    m = FauxModele(["Git status point."])
    c, ctx = await client(pool, tmp_path, robuste(tmp_path, {"cpu": m}))
    colles: list[str] = []
    ctx.dictee.colleur = colles.append
    ctx.dictee.premier_plan = lambda: "C:\\Apps\\Code.exe"
    assert (await c.get("/v1/dictee")).json()["actif"] is False
    assert (await c.post("/v1/dictee?coller=1", content=b"PPPP")).status_code == 409  # désactivée par défaut
    etat = (
        await c.put(
            "/v1/dictee",
            json={"actif": True, "corrections": [{"de": "git status point", "vers": "git status"}],
                  "styles": {"notepad.exe": "brut", "x.exe": "inconnu"}},
        )
    ).json()  # fmt: skip
    assert etat["actif"] and etat["styles"] == {"notepad.exe": "brut"} and etat["collage_possible"]
    rep = (await c.post("/v1/dictee?coller=1", content=b"PPPP")).json()
    assert rep == {**rep, "texte": "git status", "style": "code", "programme": "code.exe", "colle": True}
    assert colles == ["git status"]
    audit = await pool.fetchrow("SELECT details FROM audit WHERE action = 'dictee.collee'")
    assert audit is not None and "git" not in str(audit["details"])  # jamais le texte dicté au journal
    # Sans collage : le texte seulement
    assert (await c.post("/v1/dictee", content=b"PPPP")).json()["colle"] is False
    # Depuis un autre appareil (téléphone) : jamais de collage sur le PC
    loin, _ = await client(pool, tmp_path, robuste(tmp_path, {"cpu": m}), hote="jarvis.exemple.ts.net")
    assert (await loin.post("/v1/dictee?coller=1", content=b"PPPP")).status_code == 403
