"""Gros téléchargements : serveur HTTP local factice (coupure, erreur 500, reprise, empreinte), marqueurs, API."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import httpx
import pytest
from fastapi import HTTPException

from jarvis2 import api_telechargements, diagnostic, telechargements
from jarvis2.telechargements import Fichier, Modele, Telechargeur, lire_etat, marqueur, telecharger

GROS = bytes(range(256)) * 64  # 16 Kio
PETIT = b'{"nom": "factice"}'
DEPOT = "essai/modele-factice"


class Serveur(BaseHTTPRequestHandler):
    """Fichiers servis avec ou sans `Range` ; `pannes[chemin]` : actions consommées une par requête."""

    fichiers: ClassVar[dict[str, bytes]] = {}
    pannes: ClassVar[dict[str, list[str]]] = {}
    plages: ClassVar[list[tuple[str, str | None]]] = []
    sans_range: ClassVar[bool] = False
    empreintes: ClassVar[dict[str, str]] = {}
    noms: ClassVar[list[str]] = []

    def log_message(self, format: str, *args: Any) -> None:  # silence
        pass

    def _repondre(self, code: int, corps: bytes, entetes: dict[str, str] | None = None) -> None:
        self.send_response(code)
        for k, v in (entetes or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def do_GET(self) -> None:
        chemin = self.path.split("?", 1)[0]
        if chemin == f"/api/models/{DEPOT}/revision/main":
            siblings = []
            for nom in self.noms:
                contenu = self.fichiers[f"/{DEPOT}/resolve/abc123/{nom}"]
                s: dict[str, Any] = {"rfilename": nom, "size": len(contenu)}
                if nom in self.empreintes:
                    s["lfs"] = {"sha256": self.empreintes[nom], "size": len(contenu)}
                siblings.append(s)
            self._repondre(200, json.dumps({"sha": "abc123", "siblings": siblings}).encode())
            return
        plage = self.headers.get("Range")
        self.plages.append((chemin, plage))
        action = (self.pannes.get(chemin) or [""]).pop(0) if self.pannes.get(chemin) else ""
        if chemin not in self.fichiers:
            self._repondre(404, b"absent")
            return
        if action == "500":
            self._repondre(500, b"erreur")
            return
        contenu = self.fichiers[chemin]
        debut = 0
        if plage and not self.sans_range:
            debut = int(plage.removeprefix("bytes=").split("-")[0])
            if debut >= len(contenu):
                self._repondre(416, b"")
                return
        corps = contenu[debut:]
        self.send_response(206 if debut else 200)
        if debut:
            self.send_header("Content-Range", f"bytes {debut}-{len(contenu) - 1}/{len(contenu)}")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        if action.startswith("coupure:"):  # connexion coupée au milieu du corps
            self.wfile.write(corps[: int(action.split(":")[1])])
            self.wfile.flush()
            self.close_connection = True
            return
        self.wfile.write(corps)


@pytest.fixture
def serveur() -> Iterator[str]:
    Serveur.fichiers, Serveur.pannes, Serveur.plages, Serveur.empreintes = {}, {}, [], {}
    Serveur.sans_range = False
    Serveur.noms = ["config.json", "model.bin"]
    for nom, contenu in (("config.json", PETIT), ("model.bin", GROS), ("autre.txt", b"ignore")):
        Serveur.fichiers[f"/{DEPOT}/resolve/abc123/{nom}"] = contenu
    Serveur.empreintes["model.bin"] = hashlib.sha256(GROS).hexdigest()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Serveur)
    fil = threading.Thread(target=httpd.serve_forever, daemon=True)
    fil.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _modele(hub: str, dossier: Path, motifs: list[str] | None = None) -> Modele:
    resoudre = telechargements.fichiers_hugging_face(DEPOT, motifs or ["config.json", "model.bin"], hub)
    return Modele("essai", "Modèle d'essai", DEPOT, dossier / "modeles" / "essai", resoudre)


def _telecharger(modele: Modele, attentes: list[float] | None = None) -> telechargements.Etat:
    with httpx.Client(timeout=5) as client:
        return telecharger(modele, client, attente=2.0, dormir=(attentes if attentes is not None else []).append)


def _url(nom: str) -> str:
    return f"/{DEPOT}/resolve/abc123/{nom}"


def test_telechargement_complet_et_marqueurs(serveur: str, tmp_path: Path) -> None:
    m = _modele(serveur, tmp_path)
    e = _telecharger(m)
    assert e.statut == "pret" and e.octets == len(PETIT) + len(GROS)
    assert (m.dossier / "model.bin").read_bytes() == GROS and (m.dossier / "config.json").read_bytes() == PETIT
    assert not (m.dossier / "autre.txt").exists()  # filtré par les motifs
    assert marqueur(m.dossier, "ready").is_file() and telechargements.est_pret(m)
    assert not marqueur(m.dossier, "downloading").exists() and not marqueur(m.dossier, "failed").exists()
    assert not telechargements.dossier_partiel(m.dossier).exists()  # renommé d'un bloc
    assert not list(m.dossier.rglob("*.part"))


def test_reprise_apres_coupure(serveur: str, tmp_path: Path) -> None:
    Serveur.pannes[_url("model.bin")] = ["coupure:5000"]
    attentes: list[float] = []
    e = _telecharger(_modele(serveur, tmp_path), attentes)
    assert e.statut == "pret" and attentes == [2.0]  # un seul nouvel essai
    plages = [p for c, p in Serveur.plages if c == _url("model.bin")]
    assert plages == [None, "bytes=5000-"]  # reprise là où la coupure l'avait laissé
    assert (tmp_path / "modeles" / "essai" / "model.bin").read_bytes() == GROS


def test_reprise_sans_range_repart_de_zero(serveur: str, tmp_path: Path) -> None:
    Serveur.pannes[_url("model.bin")] = ["coupure:5000"]
    Serveur.sans_range = True  # serveur qui ignore `Range` : réponse 200 complète, on réécrit tout
    e = _telecharger(_modele(serveur, tmp_path))
    assert e.statut == "pret" and (tmp_path / "modeles" / "essai" / "model.bin").read_bytes() == GROS


def test_arret_du_core_garde_le_partiel(serveur: str, tmp_path: Path) -> None:
    m = _modele(serveur, tmp_path)
    arret = threading.Event()
    arret.set()  # Core arrêté dès le premier morceau
    with httpx.Client(timeout=5) as client:
        e = telecharger(m, client, arret=arret)
    assert e.statut == "en_cours" and not marqueur(m.dossier, "failed").exists()  # ni prêt ni échoué
    assert _telecharger(m).statut == "pret"  # nouvel accord : on reprend


def test_erreur_500_puis_succes(serveur: str, tmp_path: Path) -> None:
    Serveur.pannes[_url("model.bin")] = ["500", "500"]
    attentes: list[float] = []
    e = _telecharger(_modele(serveur, tmp_path), attentes)
    assert e.statut == "pret" and attentes == [2.0, 4.0]  # attente croissante


def test_trois_essais_puis_echec_avec_raison(serveur: str, tmp_path: Path) -> None:
    Serveur.pannes[_url("model.bin")] = ["500"] * 5
    m = _modele(serveur, tmp_path)
    attentes: list[float] = []
    e = _telecharger(m, attentes)
    assert e.statut == "echoue" and "HTTP 500" in (e.raison or "") and e.essai == 3
    assert attentes == [2.0, 4.0]
    assert len([c for c, _ in Serveur.plages if c == _url("model.bin")]) == 3
    assert marqueur(m.dossier, "failed").is_file() and not marqueur(m.dossier, "downloading").exists()
    assert not m.dossier.exists()  # jamais de dossier final incomplet
    v = diagnostic.verifier_modele(tmp_path, "inutile")  # autre modèle : absent
    assert v.reparation == "telecharger_modele"
    # Réessayer : le fichier déjà complet n'est pas retéléchargé, le marqueur d'échec disparaît
    Serveur.plages.clear()
    Serveur.pannes.clear()  # le serveur est revenu
    assert _telecharger(m).statut == "pret"
    assert [c for c, _ in Serveur.plages] == [_url("model.bin")]
    assert not marqueur(m.dossier, "failed").exists()


def test_empreinte_fausse_refusee(serveur: str, tmp_path: Path) -> None:
    Serveur.empreintes["model.bin"] = "0" * 64
    m = _modele(serveur, tmp_path)
    e = _telecharger(m)
    assert e.statut == "echoue" and "empreinte" in (e.raison or "")
    assert not list(tmp_path.rglob("*.part")) and not m.dossier.exists()


def test_fichier_introuvable_sans_nouvel_essai(serveur: str, tmp_path: Path) -> None:
    del Serveur.fichiers[_url("model.bin")]
    Serveur.noms = ["config.json"]
    resoudre = telechargements.fichiers_hugging_face(DEPOT, ["*"], serveur)
    m = Modele("essai", "Essai", DEPOT, tmp_path / "essai", lambda c: [*resoudre(c), Fichier("x.bin", serveur + "/x")])
    attentes: list[float] = []
    e = _telecharger(m, attentes)
    assert e.statut == "echoue" and "404" in (e.raison or "") and attentes == []


def test_chemin_hostile_refuse(tmp_path: Path) -> None:
    m = Modele("essai", "Essai", "x", tmp_path / "m" / "essai", lambda c: [Fichier("../../evade.txt", "http://x/")])
    e = _telecharger(m)
    assert e.statut == "echoue" and "chemin refusé" in (e.raison or "")
    assert not (tmp_path / "evade.txt").exists()


def test_marqueur_en_cours_perime(tmp_path: Path) -> None:
    m = Modele("essai", "Essai", "x", tmp_path / "essai", lambda c: [])
    contenu = {"octets": 50, "total": 200, "essai": 2, "horodatage": time.time(), "pid": os.getpid()}
    marqueur(m.dossier, "downloading").write_text(json.dumps(contenu), encoding="utf-8")
    e = lire_etat(m)
    assert e.statut == "en_cours" and e.pourcentage == 25
    assert "25 %" in diagnostic.decrire_telechargement(e) and "essai 2/3" in diagnostic.decrire_telechargement(e)
    contenu["horodatage"] = time.time() - 3600  # processus arrêté en route
    marqueur(m.dossier, "downloading").write_text(json.dumps(contenu), encoding="utf-8")
    assert lire_etat(m).statut == "interrompu"
    assert lire_etat(m, actif=True).statut == "en_cours"


async def test_telechargeur_en_tache_de_fond(serveur: str, tmp_path: Path) -> None:
    m = _modele(serveur, tmp_path)
    vus: list[str] = []
    t = Telechargeur(lambda: httpx.Client(timeout=5), attente=0)
    tache = t.lancer(m, lambda e: vus.append(e.statut))
    assert t.lancer(m) is tache  # un seul téléchargement à la fois par modèle
    assert (await t.attendre(m)).statut == "pret" and vus == ["pret"]
    assert t.etat(m).statut == "pret"


def test_diagnostic_lit_les_marqueurs(tmp_path: Path) -> None:
    dossier = telechargements.dossier_embeddings(tmp_path, "org/mini")
    dossier.parent.mkdir(parents=True)
    assert diagnostic.verifier_modele(tmp_path, "org/mini").statut == "attention"
    marqueur(dossier, "failed").write_text(json.dumps({"raison": "réponse HTTP 500", "essais": 3}), encoding="utf-8")
    v = diagnostic.verifier_modele(tmp_path, "org/mini")
    assert v.statut == "attention" and "réponse HTTP 500" in v.detail and v.reparation == "telecharger_modele"
    marqueur(dossier, "failed").unlink()
    dossier.mkdir()
    marqueur(dossier, "ready").write_text("{}", encoding="utf-8")
    assert diagnostic.verifier_modele(tmp_path, "org/mini").statut == "ok"
    voix = diagnostic.verifier_voix(tmp_path, "base")
    assert voix.statut == "info" and voix.reparation == "telecharger_voix"  # facultatif, proposé


def test_encodeur_ne_telecharge_jamais(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")  # garde-fou : aucun accès réseau même en cas de régression
    from jarvis2.embeddings import EncodeurFastEmbed

    e = EncodeurFastEmbed(tmp_path)
    assert not e.present()
    with pytest.raises(telechargements.ModeleAbsent, match="non téléchargé"):
        e.encoder_sync("essai")
    assert not list(tmp_path.rglob("*.onnx"))


SANS_P: Any = None  # paramètres inutiles : `modeles` est remplacé


async def test_lancement_par_l_api(serveur: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m = _modele(serveur, tmp_path)
    monkeypatch.setattr(api_telechargements, "modeles", lambda p: {"embeddings": m})
    ctx: Any = SimpleNamespace(telechargeur=Telechargeur(lambda: httpx.Client(timeout=5), attente=0), memoire=None)
    assert api_telechargements.etats(ctx, SANS_P)[0]["statut"] == "absent"
    api_telechargements.lancer(ctx, SANS_P, "embeddings")
    assert (await ctx.telechargeur.attendre(m)).statut == "pret"
    assert api_telechargements.etats(ctx, SANS_P)[0]["statut"] == "pret"
    with pytest.raises(HTTPException):
        api_telechargements.lancer(ctx, SANS_P, "inconnu")
