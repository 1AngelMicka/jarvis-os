"""Gros téléchargements (modèles d'embeddings, Whisper…) : un seul module, en tâche de fond, jamais sans accord.

Chaque modèle a son dossier final dans le dossier des données (`modeles/<famille>/<nom>`). À côté, des marqueurs
lisibles par un autre processus (`jarvis2 docteur`) :

- `<nom>.downloading` : en cours (JSON : octets reçus, total, essai, processus, dernière mise à jour) ;
- `<nom>.ready` : prêt (JSON : date, fichiers) ;
- `<nom>.failed` : échoué (JSON : raison, date, essais).

Les fichiers arrivent dans `<nom>.partiel/` sous la forme `fichier.part`, renommés atomiquement à la fin de chaque
fichier ; le dossier entier est ensuite renommé atomiquement en `<nom>`. Trois essais avec une attente croissante ;
une coupure reprend où elle s'était arrêtée (en-tête `Range`) si le serveur le permet ; l'empreinte SHA-256 est
vérifiée quand elle est connue. Rien ne part sans un appel explicite à `Telechargeur.lancer` (clic de
l'utilisateur, `jarvis2 docteur --reparer`) : le démarrage du Core ne télécharge jamais rien.
"""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import hashlib
import json
import logging
import os
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

journal = logging.getLogger("jarvis2.telechargements")

HUB = "https://huggingface.co"
ESSAIS = 3
ATTENTE_BASE = 2.0  # secondes ; 2 s puis 4 s entre les essais
PERIODE_MARQUEUR = 1.0  # le marqueur « en cours » est réécrit au plus une fois par seconde
PERIME = 120.0  # un marqueur « en cours » sans nouvelles depuis 2 min : processus arrêté, reprise possible
MORCEAU = 1 << 20

Statut = Literal["absent", "en_cours", "interrompu", "pret", "echoue"]


class ErreurTelechargement(Exception):
    """Échec d'un essai ; `definitif` : inutile de réessayer (fichier introuvable, accès refusé…)."""

    def __init__(self, raison: str, *, definitif: bool = False) -> None:
        super().__init__(raison)
        self.definitif = definitif


class Arrete(Exception):
    """Arrêt du Core pendant un téléchargement : les fichiers partiels restent pour la reprise."""


class ModeleAbsent(RuntimeError):
    """Le modèle n'est pas téléchargé : il ne l'est jamais en silence, l'utilisateur doit l'accepter."""


@dataclass(frozen=True)
class Fichier:
    chemin: str  # relatif au dossier du modèle (« onnx/model.onnx »)
    url: str
    taille: int | None = None
    sha256: str | None = None


Resolveur = Callable[[httpx.Client], list[Fichier]]


@dataclass(frozen=True)
class Modele:
    """Un modèle téléchargeable : où il va, et comment connaître ses fichiers (résolu au moment de télécharger)."""

    id: str  # « embeddings », « voix »
    titre: str
    nom: str
    dossier: Path
    resoudre: Resolveur
    taille_estimee: int | None = None


@dataclass
class Etat:
    id: str
    titre: str
    nom: str
    statut: Statut
    octets: int = 0
    total: int | None = None
    raison: str | None = None
    essai: int | None = None
    maj: str | None = None
    taille_estimee: int | None = None

    def en_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "titre": self.titre,
            "nom": self.nom,
            "statut": self.statut,
            "octets": self.octets,
            "total": self.total,
            "raison": self.raison,
            "essai": self.essai,
            "maj": self.maj,
            "taille_estimee": self.taille_estimee,
        }

    @property
    def pourcentage(self) -> int | None:
        if not self.total:
            return None
        return min(100, int(self.octets * 100 / self.total))


# --- Marqueurs -----------------------------------------------------------------------------------------------


def marqueur(dossier: Path, sorte: Literal["downloading", "ready", "failed"]) -> Path:
    return dossier.with_name(f"{dossier.name}.{sorte}")


def dossier_partiel(dossier: Path) -> Path:
    return dossier.with_name(f"{dossier.name}.partiel")


def _maintenant() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _ecrire_json(chemin: Path, contenu: dict[str, Any]) -> None:
    """Écriture atomique (fichier temporaire puis renommage) : un lecteur ne voit jamais un JSON à moitié écrit."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(f"{chemin.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(contenu, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, chemin)


def _lire_json(chemin: Path) -> dict[str, Any] | None:
    try:
        valeur = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return valeur if isinstance(valeur, dict) else None


def lire_etat(modele: Modele, *, actif: bool = False) -> Etat:
    """État lu sur le disque seulement (utilisable par un autre processus). `actif` : tâche vivante ici."""
    e = Etat(modele.id, modele.titre, modele.nom, "absent", taille_estimee=modele.taille_estimee)
    en_cours = _lire_json(marqueur(modele.dossier, "downloading"))
    if en_cours is not None:
        e.octets = int(en_cours.get("octets") or 0)
        e.total = en_cours.get("total")
        e.essai = en_cours.get("essai")
        e.maj = en_cours.get("maj")
        e.raison = en_cours.get("raison")  # dernier essai raté, avant le suivant
        frais = time.time() - float(en_cours.get("horodatage") or 0) < PERIME
        e.statut = "en_cours" if actif or frais else "interrompu"
        return e
    pret = _lire_json(marqueur(modele.dossier, "ready"))
    if pret is not None and modele.dossier.is_dir():
        e.statut, e.maj = "pret", pret.get("maj")
        e.octets = int(pret.get("octets") or 0)
        e.total = e.octets or None
        return e
    echec = _lire_json(marqueur(modele.dossier, "failed"))
    if echec is not None:
        e.statut, e.raison, e.maj, e.essai = "echoue", echec.get("raison"), echec.get("maj"), echec.get("essais")
        return e
    if actif:
        e.statut = "en_cours"
    return e


def est_pret(modele_ou_dossier: Modele | Path) -> bool:
    dossier = modele_ou_dossier.dossier if isinstance(modele_ou_dossier, Modele) else modele_ou_dossier
    return dossier.is_dir() and marqueur(dossier, "ready").is_file()


# --- Téléchargement d'un modèle (fil à part : fichiers et réseau bloquants) -------------------------------------


@dataclass
class _Progres:
    modele: Modele
    essai: int = 1
    octets: int = 0
    total: int | None = None
    raison: str | None = None
    arret: threading.Event | None = None
    _derniere: float = field(default=0.0)

    def ecrire(self, *, force: bool = False) -> None:
        maintenant = time.time()
        if not force and maintenant - self._derniere < PERIODE_MARQUEUR:
            return
        self._derniere = maintenant
        contenu = {
            "octets": self.octets,
            "total": self.total,
            "essai": self.essai,
            "raison": self.raison,
            "pid": os.getpid(),
            "horodatage": maintenant,
            "maj": _maintenant(),
        }
        with contextlib.suppress(OSError):  # lu au même instant par un autre processus (Windows) : sans gravité
            _ecrire_json(marqueur(self.modele.dossier, "downloading"), contenu)


def _empreinte(chemin: Path) -> str:
    h = hashlib.sha256()
    with chemin.open("rb") as f:
        while morceau := f.read(MORCEAU):
            h.update(morceau)
    return h.hexdigest()


def _fichier_complet(cible: Path, f: Fichier) -> bool:
    if not cible.is_file():
        return False
    if f.taille is not None and cible.stat().st_size != f.taille:
        return False
    return f.sha256 is None or _empreinte(cible) == f.sha256


def _telecharger_fichier(client: httpx.Client, f: Fichier, cible: Path, progres: _Progres) -> int:
    """Télécharge un fichier dans `cible.part`, reprend si possible, vérifie, renomme. Renvoie sa taille."""
    if _fichier_complet(cible, f):  # déjà venu lors d'un essai précédent
        return cible.stat().st_size
    cible.parent.mkdir(parents=True, exist_ok=True)
    part = cible.with_name(f"{cible.name}.part")
    deja = part.stat().st_size if part.is_file() else 0
    if f.taille is not None and deja > f.taille:
        part.unlink()
        deja = 0
    base = progres.octets
    entetes = {"Range": f"bytes={deja}-"} if deja else {}
    try:
        with client.stream("GET", f.url, headers=entetes) as r:
            if r.status_code == 416:  # fichier partiel inutilisable côté serveur : on repart de zéro
                part.unlink(missing_ok=True)
                raise ErreurTelechargement(f"{f.chemin} : reprise refusée par le serveur")
            if r.status_code == 206 and deja and r.headers.get("content-range", "").startswith(f"bytes {deja}-"):
                mode = "ab"
            elif r.status_code == 200 or (r.status_code == 206 and not deja):
                mode, deja = "wb", 0
            elif r.status_code == 206:  # plage inattendue : on ne colle pas des morceaux au hasard
                part.unlink(missing_ok=True)
                raise ErreurTelechargement(f"{f.chemin} : plage inattendue")
            else:
                definitif = r.status_code in (401, 403, 404, 410)
                raise ErreurTelechargement(f"{f.chemin} : réponse HTTP {r.status_code}", definitif=definitif)
            progres.octets = base + deja
            with part.open(mode) as sortie:
                for morceau in r.iter_bytes():  # sans tampon : une coupure ne perd rien de reçu
                    if progres.arret is not None and progres.arret.is_set():
                        raise Arrete
                    sortie.write(morceau)
                    progres.octets += len(morceau)
                    progres.ecrire()
    except httpx.HTTPError as exc:  # coupure, délai dépassé : le fichier partiel est gardé pour la reprise
        raise ErreurTelechargement(f"{f.chemin} : connexion interrompue ({type(exc).__name__})") from exc
    taille = part.stat().st_size
    if f.taille is not None and taille != f.taille:
        if taille > f.taille:
            part.unlink()
        raise ErreurTelechargement(f"{f.chemin} : {taille} octets reçus sur {f.taille}")
    if f.sha256 is not None and _empreinte(part) != f.sha256.lower():
        part.unlink()
        raise ErreurTelechargement(f"{f.chemin} : empreinte SHA-256 différente de celle attendue")
    os.replace(part, cible)
    return taille


def _un_essai(client: httpx.Client, modele: Modele, progres: _Progres) -> list[str]:
    fichiers = modele.resoudre(client)
    if not fichiers:
        raise ErreurTelechargement("aucun fichier à télécharger pour ce modèle", definitif=True)
    tailles = [f.taille for f in fichiers]
    progres.total = sum(t for t in tailles if t is not None) if all(t is not None for t in tailles) else None
    progres.octets = 0
    partiel = dossier_partiel(modele.dossier)
    for f in fichiers:
        cible = (partiel / f.chemin).resolve()
        if not cible.is_relative_to(partiel.resolve()):  # chemin venu du réseau : jamais hors du dossier
            raise ErreurTelechargement(f"chemin refusé : {f.chemin}", definitif=True)
        avant = progres.octets
        progres.octets = avant + _telecharger_fichier(client, f, cible, progres)
        progres.ecrire()
    if modele.dossier.exists():  # ancienne copie incomplète (sans « .ready ») : remplacée
        shutil.rmtree(modele.dossier)
    os.replace(partiel, modele.dossier)
    return [f.chemin for f in fichiers]


def telecharger(
    modele: Modele,
    client: httpx.Client,
    *,
    essais: int = ESSAIS,
    attente: float = ATTENTE_BASE,
    dormir: Callable[[float], None] | None = None,
    arret: threading.Event | None = None,
) -> Etat:
    """Télécharge le modèle (bloquant). Conclu par un marqueur « prêt » ou « échoué », sauf arrêt demandé
    (`arret`) : le marqueur « en cours » reste et devient « interrompu », la reprise repart des fichiers partiels."""
    arret = arret or threading.Event()
    attendre = dormir or (lambda s: arret.wait(s))
    progres = _Progres(modele, arret=arret)
    marqueur(modele.dossier, "failed").unlink(missing_ok=True)
    marqueur(modele.dossier, "ready").unlink(missing_ok=True)
    for essai in range(1, essais + 1):
        progres.essai = essai
        progres.ecrire(force=True)
        try:
            fichiers = _un_essai(client, modele, progres)
        except Arrete:
            journal.info("Téléchargement de %s arrêté (reprise possible)", modele.nom)
            return lire_etat(modele)
        except ErreurTelechargement as exc:
            progres.raison = str(exc)
            journal.warning("Téléchargement de %s, essai %d/%d : %s", modele.nom, essai, essais, exc)
            if exc.definitif:
                break
        except Exception as exc:  # disque plein, droits, réponse illisible…
            progres.raison = f"{type(exc).__name__} : {exc}"
            journal.exception("Téléchargement de %s, essai %d/%d", modele.nom, essai, essais)
        else:
            octets = progres.octets
            _ecrire_json(
                marqueur(modele.dossier, "ready"), {"maj": _maintenant(), "octets": octets, "fichiers": fichiers}
            )
            marqueur(modele.dossier, "downloading").unlink(missing_ok=True)
            journal.info("Modèle %s téléchargé (%d octets)", modele.nom, octets)
            return lire_etat(modele)
        if essai < essais:
            progres.ecrire(force=True)
            attendre(attente * 2 ** (essai - 1))
            if arret.is_set():
                return lire_etat(modele)
    _ecrire_json(
        marqueur(modele.dossier, "failed"),
        {"raison": progres.raison or "échec inconnu", "maj": _maintenant(), "essais": progres.essai},
    )
    marqueur(modele.dossier, "downloading").unlink(missing_ok=True)
    return lire_etat(modele)


def nouveau_client() -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, connect=15.0),
        headers={"User-Agent": "jarvis2-telechargements"},
    )


class Telechargeur:
    """Lance les téléchargements en tâche de fond (un seul à la fois par modèle) et donne leur état."""

    def __init__(
        self,
        fabrique: Callable[[], httpx.Client] = nouveau_client,
        *,
        essais: int = ESSAIS,
        attente: float = ATTENTE_BASE,
    ) -> None:
        self.fabrique = fabrique
        self.essais = essais
        self.attente = attente
        self._taches: dict[Path, asyncio.Task[Etat]] = {}
        self._arret = threading.Event()

    def arreter(self) -> None:
        """Arrêt du Core : les fils de téléchargement s'arrêtent au prochain morceau."""
        self._arret.set()

    def actif(self, modele: Modele) -> bool:
        tache = self._taches.get(modele.dossier)
        return tache is not None and not tache.done()

    def etat(self, modele: Modele) -> Etat:
        return lire_etat(modele, actif=self.actif(modele))

    def _executer(self, modele: Modele) -> Etat:
        with self.fabrique() as client:
            return telecharger(modele, client, essais=self.essais, attente=self.attente, arret=self._arret)

    def lancer(self, modele: Modele, apres: Callable[[Etat], Any] | None = None) -> asyncio.Task[Etat]:
        """À n'appeler que sur une demande de l'utilisateur. Renvoie la tâche en cours si elle existe déjà."""
        tache = self._taches.get(modele.dossier)
        if tache is not None and not tache.done():
            return tache

        async def executer() -> Etat:
            etat = await asyncio.to_thread(self._executer, modele)
            if apres is not None:
                resultat = apres(etat)
                if asyncio.iscoroutine(resultat):
                    await resultat
            return etat

        tache = asyncio.get_running_loop().create_task(executer())
        self._taches[modele.dossier] = tache
        return tache

    async def attendre(self, modele: Modele) -> Etat:
        tache = self._taches.get(modele.dossier)
        return await tache if tache is not None else self.etat(modele)


# --- Catalogue : modèles Hugging Face (fastembed, faster-whisper) ----------------------------------------------


def _nom_dossier(nom: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "--" for c in nom.replace("/", "--"))


def fichiers_hugging_face(depot: str, motifs: list[str], hub: str = HUB) -> Resolveur:
    """Fichiers d'un dépôt Hugging Face filtrés par motifs ; tailles et empreintes (fichiers LFS) lues sur le hub."""

    def resoudre(client: httpx.Client) -> list[Fichier]:
        try:
            r = client.get(f"{hub}/api/models/{depot}/revision/main", params={"blobs": "true"})
        except httpx.HTTPError as exc:
            raise ErreurTelechargement(f"hub injoignable ({type(exc).__name__})") from exc
        if r.status_code != 200:
            raise ErreurTelechargement(
                f"dépôt {depot} : réponse HTTP {r.status_code}", definitif=r.status_code in (401, 403, 404)
            )
        info = r.json()
        revision = str(info.get("sha") or "main")
        fichiers = []
        for s in info.get("siblings") or []:
            nom = str(s.get("rfilename") or "")
            if not any(fnmatch.fnmatch(nom, m) for m in motifs):
                continue
            lfs = s.get("lfs") or {}
            fichiers.append(
                Fichier(
                    chemin=nom,
                    url=f"{hub}/{depot}/resolve/{revision}/{nom}",
                    taille=s.get("size") if isinstance(s.get("size"), int) else lfs.get("size"),
                    sha256=lfs.get("sha256"),
                )
            )
        return fichiers

    return resoudre


MOTIFS_FASTEMBED = [
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "preprocessor_config.json",
]
MOTIFS_WHISPER = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]


def description_fastembed(nom: str) -> dict[str, Any]:
    """Description fastembed du modèle (dépôt, fichier ONNX, fichiers annexes, taille)."""
    from fastembed import TextEmbedding

    from .embeddings import _ajouter_modeles

    _ajouter_modeles(TextEmbedding)
    for m in TextEmbedding.list_supported_models():
        if m["model"].lower() == nom.lower():
            return dict(m)
    raise ErreurTelechargement(f"modèle d'embeddings inconnu de fastembed : {nom}", definitif=True)


def dossier_embeddings(dossier_modeles: Path, nom: str) -> Path:
    return dossier_modeles / "embeddings" / _nom_dossier(nom)


def dossier_whisper(dossier_modeles: Path, nom: str) -> Path:
    return dossier_modeles / "whisper-jarvis" / _nom_dossier(nom)


def modele_embeddings(dossier_modeles: Path, nom: str, hub: str = HUB) -> Modele:
    def resoudre(client: httpx.Client) -> list[Fichier]:
        d = description_fastembed(nom)
        depot = (d.get("sources") or {}).get("hf")
        if not depot:
            raise ErreurTelechargement(f"{nom} : source non prise en charge (pas sur Hugging Face)", definitif=True)
        motifs = [*MOTIFS_FASTEMBED, d["model_file"], *(d.get("additional_files") or [])]
        return fichiers_hugging_face(depot, motifs, hub)(client)

    return Modele(
        "embeddings", "Modèle d'embeddings (mémoire)", nom, dossier_embeddings(dossier_modeles, nom), resoudre
    )


def depot_whisper(nom: str) -> str:
    if "/" in nom:
        return nom
    from faster_whisper.utils import _MODELS  # type: ignore[import-untyped]

    depot = _MODELS.get(nom)
    if not isinstance(depot, str):
        raise ErreurTelechargement(f"modèle Whisper inconnu : {nom}", definitif=True)
    return depot


def modele_whisper(dossier_modeles: Path, nom: str, hub: str = HUB) -> Modele:
    def resoudre(client: httpx.Client) -> list[Fichier]:
        return fichiers_hugging_face(depot_whisper(nom), MOTIFS_WHISPER, hub)(client)

    return Modele("voix", "Modèle de voix (Whisper)", nom, dossier_whisper(dossier_modeles, nom), resoudre)
