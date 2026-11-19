"""Reconnaissance du propriétaire à la voix (lot K3) : ECAPA-TDNN, plusieurs empreintes, désactivée par défaut.

- Modèle : ECAPA-TDNN 512 de WeSpeaker (VoxCeleb, licence Apache-2.0), au format ONNX (≈ 25 Mo), exécuté par
  onnxruntime sur le processeur. Téléchargé seulement sur accord (`telechargements.py`, identifiant « proprietaire »).
- Empreintes : vecteurs calculés sur le PC et gardés dans le dossier des données (`voix/empreintes.json`), jamais
  dans la base, jamais envoyés à un service, jamais exportés ; l'audio lui-même n'est pas gardé.
- Vérification : similarité cosinus avec la meilleure empreinte, au-dessus d'un seuil réglable.
- **Fermée** : quand la reconnaissance est activée, une action 🟡🔴 demandée à la voix n'est acceptée que si la phrase
  a été reconnue comme celle du propriétaire. Modèle absent, aucune empreinte, parole trop courte, voix d'un autre :
  l'action est refusée (les actions 🟢 ne changent pas).
- Profils par personne (lot 14-D18) : d'autres voix de la maison peuvent avoir leurs empreintes, rangées sous
  l'identifiant de leur profil (`profil`). Elles ne comptent JAMAIS comme le propriétaire : une phrase plus proche
  d'un profil que du propriétaire est « inconnue » pour les actions, mais attribuée à ce profil (présence, volume).
- Une phrase est « venue de la voix » si elle reprend une transcription des 2 dernières minutes (comparaison du texte
  normalisé), ou si l'interface l'annonce (en-tête `X-Jarvis-Voix`).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from . import telechargements
from .securite.permissions import ErreurAction
from .voix import analyser_eveil, sans_accents

if TYPE_CHECKING:
    from .db import Base
    from .transcription import Resultat

journal = logging.getLogger("jarvis2.proprietaire")

CLE = "proprietaire"
REGLAGES_DEFAUT: dict[str, Any] = {"actif": False, "seuil": 0.5}
DEPOT_MODELE = "Wespeaker/wespeaker-voxceleb-ecapa-tdnn512"
FICHIER_MODELE = "voxceleb_ECAPA512.onnx"
NOM_MODELE = "wespeaker-voxceleb-ecapa-tdnn512"
EMPREINTES_MAX = 10
EMPREINTES_PROFIL_MAX = 5
PAROLE_INSCRIPTION = 3.0  # secondes de parole au moins pour une empreinte
PAROLE_VERIFICATION = 1.0
DUREE_ATTESTATION = 120.0
TAUX = 16000

Verdict = Literal["reconnu", "inconnu", "indisponible", "trop_court", "non_verifie"]

MESSAGES: dict[str, str] = {
    "inconnu": "la voix n'a pas été reconnue comme celle du propriétaire",
    "indisponible": "la reconnaissance du propriétaire est indisponible",
    "trop_court": "la phrase était trop courte pour reconnaître la voix",
    "non_verifie": "la voix n'a pas été vérifiée",
    "absente": "aucune vérification de la voix n'a été faite pour cette phrase",
}


def modele_proprietaire(dossier_modeles: Path, hub: str = telechargements.HUB) -> telechargements.Modele:
    return telechargements.Modele(
        "proprietaire",
        "Reconnaissance du propriétaire (ECAPA-TDNN)",
        NOM_MODELE,
        dossier_modeles / "locuteur" / NOM_MODELE,
        telechargements.fichiers_hugging_face(DEPOT_MODELE, [FICHIER_MODELE, "config.yaml"], hub),
        taille_estimee=25_000_000,
    )


# --- Caractéristiques (fbank à la manière de Kaldi, comme WeSpeaker) ---------------------------------------


def _mel(f: Any) -> Any:
    import numpy as np

    return 1127.0 * np.log1p(np.asarray(f) / 700.0)


def banc_mel(n_mel: int = 80, n_fft: int = 512, taux: int = TAUX, bas: float = 20.0) -> Any:
    import numpy as np

    haut = taux / 2
    mel_bas, mel_haut = _mel(bas), _mel(haut)
    centres = np.linspace(mel_bas, mel_haut, n_mel + 2)
    freqs = _mel(np.arange(n_fft // 2 + 1) * taux / n_fft)
    banc = np.zeros((n_mel, n_fft // 2 + 1), dtype=np.float32)
    for i in range(n_mel):
        g, c, d = centres[i], centres[i + 1], centres[i + 2]
        montee = (freqs - g) / (c - g)
        descente = (d - freqs) / (d - c)
        banc[i] = np.maximum(0.0, np.minimum(montee, descente))
    return banc


def fbank(echantillons: Any, n_mel: int = 80) -> Any:
    """Log-énergies de 80 bandes mel, trames de 25 ms toutes les 10 ms, moyenne retirée (CMN)."""
    import numpy as np

    x = np.asarray(echantillons, dtype=np.float32) * 32768.0
    longueur, pas, n_fft = 400, 160, 512
    if len(x) < longueur:
        raise ValueError("Extrait trop court")
    n = 1 + (len(x) - longueur) // pas
    index = np.arange(longueur)[None, :] + pas * np.arange(n)[:, None]
    trames = x[index]
    trames = trames - trames.mean(axis=1, keepdims=True)
    trames = np.concatenate([trames[:, :1] * (1 - 0.97), trames[:, 1:] - 0.97 * trames[:, :-1]], axis=1)
    trames = trames * np.hamming(longueur).astype(np.float32)
    spectre = np.abs(np.fft.rfft(trames, n=n_fft)) ** 2
    energies = np.log(np.maximum(spectre @ banc_mel(n_mel, n_fft).T, np.finfo(np.float32).eps))
    return (energies - energies.mean(axis=0, keepdims=True)).astype(np.float32)


def parole_seule(echantillons: Any, plages: list[tuple[int, int]]) -> Any:
    import numpy as np

    if not plages:
        return np.asarray(echantillons, dtype=np.float32)
    return np.concatenate([echantillons[d:f] for d, f in plages]).astype(np.float32)


def cosinus(a: Any, b: Any) -> float:
    import numpy as np

    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if not na or not nb:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class EmpreinteurEcapa:
    """ECAPA-TDNN (ONNX) : extrait de parole → vecteur (192 valeurs). Chargé à la première utilisation."""

    def __init__(self, dossier: Path) -> None:
        self.dossier = dossier
        self._session: Any = None

    @property
    def fichier(self) -> Path:
        return self.dossier / FICHIER_MODELE

    def disponible(self) -> tuple[bool, str | None]:
        if not self.fichier.is_file():
            return False, "modèle de reconnaissance non téléchargé"
        if importlib.util.find_spec("onnxruntime") is None:
            return False, "onnxruntime absent"
        return True, None

    def empreinte(self, echantillons: Any) -> Any:
        import numpy as np

        if self._session is None:
            import onnxruntime as ort  # type: ignore[import-untyped]

            options = ort.SessionOptions()
            options.log_severity_level = 3
            self._session = ort.InferenceSession(str(self.fichier), options, providers=["CPUExecutionProvider"])
        entree = self._session.get_inputs()[0].name
        sortie = self._session.run(None, {entree: fbank(echantillons)[None, :, :]})[0]
        vecteur = np.asarray(sortie, dtype=np.float32).reshape(-1)
        return vecteur / max(float(np.linalg.norm(vecteur)), 1e-9)


# --- Service ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Attestation:
    verdict: Verdict
    score: float | None
    instant: float
    profil: str | None = None  # profil reconnu (autre personne de la maison), None pour le propriétaire ou inconnu


def voix_annoncee(entetes: Any) -> bool:
    """L'interface annonce une demande dite à voix haute (en-tête `X-Jarvis-Voix: 1`)."""
    return str(entetes.get("x-jarvis-voix", "")).strip().lower() in ("1", "oui", "true")


def normaliser(texte: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", sans_accents(texte).lower()).split())


class ServiceProprietaire:
    def __init__(
        self,
        pool: Base,
        dossier_donnees: Path | None,
        dossier_modeles: Path | None,
        *,
        empreinteur: Any = None,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self.pool = pool
        self.fichier = dossier_donnees / "voix" / "empreintes.json" if dossier_donnees is not None else None
        self.dossier_modeles = dossier_modeles
        self.empreinteur = empreinteur or (
            EmpreinteurEcapa(modele_proprietaire(dossier_modeles).dossier) if dossier_modeles is not None else None
        )
        self.horloge = horloge
        self.reglages: dict[str, Any] | None = None
        self._attestations: dict[str, Attestation] = {}
        self._verrou = asyncio.Lock()

    # -- réglages et empreintes ------------------------------------------------------------------------------

    async def charger(self) -> dict[str, Any]:
        if self.reglages is None:
            brut = await self.pool.fetchval("SELECT valeur FROM etat_systeme WHERE cle = $1", CLE)
            valeur = json.loads(brut) if isinstance(brut, str) else (brut or {})
            self.reglages = {**REGLAGES_DEFAUT, **{k: v for k, v in dict(valeur).items() if k in REGLAGES_DEFAUT}}
        return self.reglages

    async def regler(self, actif: bool | None = None, seuil: float | None = None) -> dict[str, Any]:
        reglages = dict(await self.charger())
        if actif is not None:
            reglages["actif"] = bool(actif)
        if seuil is not None:
            reglages["seuil"] = round(min(0.9, max(0.2, float(seuil))), 2)
        # La ligne est créée par la migration 022 : le rôle applicatif n'écrit que par UPDATE
        await self.pool.execute(
            "UPDATE etat_systeme SET valeur = $2::text::jsonb, maj_le = now() WHERE cle = $1", CLE, json.dumps(reglages)
        )
        self.reglages = reglages
        return reglages

    def _lire(self) -> list[dict[str, Any]]:
        if self.fichier is None or not self.fichier.is_file():
            return []
        try:
            donnees = json.loads(self.fichier.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            journal.warning("Empreintes de voix illisibles : ignorées")
            return []
        return [e for e in donnees.get("empreintes", []) if isinstance(e, dict) and isinstance(e.get("vecteur"), list)]

    def _ecrire(self, empreintes: list[dict[str, Any]]) -> None:
        if self.fichier is None:
            raise ErreurAction("Dossier des données absent : empreintes impossibles à garder")
        self.fichier.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.fichier.with_name(f"{self.fichier.name}.tmp")
        tmp.write_text(json.dumps({"version": 1, "modele": NOM_MODELE, "empreintes": empreintes}), encoding="utf-8")
        tmp.replace(self.fichier)

    def _du_proprietaire(self) -> list[dict[str, Any]]:
        return [e for e in self._lire() if not e.get("profil")]

    def empreintes(self, profil: str | None = None) -> list[dict[str, Any]]:
        """Empreintes du propriétaire (ou d'un profil) : jamais le vecteur."""
        return [
            {k: e.get(k) for k in ("id", "cree_le", "parole_s")}
            for e in self._lire()
            if (e.get("profil") or None) == profil
        ]

    def profils_inscrits(self) -> dict[str, int]:
        """Nombre d'empreintes par profil (pour l'interface)."""
        compte: dict[str, int] = {}
        for e in self._lire():
            if e.get("profil"):
                compte[str(e["profil"])] = compte.get(str(e["profil"]), 0) + 1
        return compte

    def disponibilite(self) -> tuple[bool, str | None]:
        if self.empreinteur is None:
            return False, "dossier des modèles absent"
        ok, raison = self.empreinteur.disponible()
        if not ok:
            return False, raison
        if not self._du_proprietaire():
            return False, "aucune empreinte de voix enregistrée"
        return True, None

    async def etat(self) -> dict[str, Any]:
        reglages = await self.charger()
        ok, raison = self.disponibilite()
        return {
            **reglages,
            "disponible": ok,
            "raison": raison,
            "empreintes": self.empreintes(),
            "empreintes_max": EMPREINTES_MAX,
            "ferme": bool(reglages["actif"]) and not ok,  # activée mais indisponible : 🟡🔴 à la voix refusés
        }

    async def inscrire(self, resultat: Resultat, profil: str | None = None) -> dict[str, Any]:
        """Nouvelle empreinte depuis un enregistrement (3 s de parole au moins), du propriétaire ou d'un profil."""
        if self.empreinteur is None or not self.empreinteur.disponible()[0]:
            raise ErreurAction("Téléchargez d'abord le modèle de reconnaissance du propriétaire")
        if resultat.duree_parole < PAROLE_INSCRIPTION:
            raise ErreurAction(
                f"Parlez au moins {PAROLE_INSCRIPTION:.0f} secondes (entendu : {resultat.duree_parole:.1f} s de parole)"
            )
        async with self._verrou:
            empreintes = self._lire()
            maximum = EMPREINTES_PROFIL_MAX if profil else EMPREINTES_MAX
            if sum(1 for e in empreintes if (e.get("profil") or None) == profil) >= maximum:
                raise ErreurAction(f"{maximum} empreintes au plus : retirez-en une d'abord")
            extrait = parole_seule(resultat.echantillons, resultat.plages)
            vecteur = await asyncio.to_thread(self.empreinteur.empreinte, extrait)
            nouvelle = {
                "id": uuid.uuid4().hex[:12],
                "cree_le": datetime.now(UTC).isoformat(timespec="seconds"),
                "parole_s": round(resultat.duree_parole, 1),
                "vecteur": [round(float(v), 6) for v in vecteur],
                **({"profil": profil} if profil else {}),
            }
            empreintes.append(nouvelle)
            self._ecrire(empreintes)
        return {k: nouvelle[k] for k in ("id", "cree_le", "parole_s")}

    async def retirer_profil(self, profil: str) -> int:
        """Retire toutes les empreintes d'un profil (profil supprimé)."""
        async with self._verrou:
            empreintes = self._lire()
            reste = [e for e in empreintes if e.get("profil") != profil]
            if len(reste) != len(empreintes):
                self._ecrire(reste)
        return len(empreintes) - len(reste)

    async def retirer(self, ident: str) -> bool:
        async with self._verrou:
            empreintes = self._lire()
            reste = [e for e in empreintes if e.get("id") != ident]
            if len(reste) == len(empreintes):
                return False
            self._ecrire(reste)
        return True

    # -- vérification ----------------------------------------------------------------------------------------

    async def verifier(self, resultat: Resultat) -> tuple[Verdict, float | None]:
        verdict, score, _ = await self.identifier(resultat)
        return verdict, score

    async def identifier(self, resultat: Resultat) -> tuple[Verdict, float | None, str | None]:
        """Verdict pour le propriétaire, score, et profil reconnu (une autre personne de la maison) s'il y en a un."""
        reglages = await self.charger()
        if not reglages["actif"]:
            return "non_verifie", None, None
        ok, _ = self.disponibilite()
        if not ok or self.empreinteur is None or resultat.echantillons is None:
            return "indisponible", None, None
        if resultat.duree_parole < PAROLE_VERIFICATION:
            return "trop_court", None, None
        try:
            extrait = parole_seule(resultat.echantillons, resultat.plages)
            vecteur = await asyncio.to_thread(self.empreinteur.empreinte, extrait)
        except Exception:
            journal.exception("Empreinte de la voix impossible")
            return "indisponible", None, None
        seuil = float(reglages["seuil"])
        toutes = self._lire()
        score = max(cosinus(vecteur, e["vecteur"]) for e in toutes if not e.get("profil"))
        profils = [(cosinus(vecteur, e["vecteur"]), str(e["profil"])) for e in toutes if e.get("profil")]
        meilleur = max(profils, default=None)
        if meilleur is not None and meilleur[0] >= seuil and meilleur[0] > score:
            return "inconnu", round(score, 3), meilleur[1]  # une autre personne de la maison : jamais le propriétaire
        return ("reconnu" if score >= seuil else "inconnu"), round(score, 3), None

    async def observer(self, resultat: Resultat) -> None:
        """Après chaque transcription : la phrase est notée « venue de la voix », avec le verdict."""
        if not resultat.texte:
            return
        verdict, score, profil = await self.identifier(resultat)
        maintenant = self.horloge()
        self._attestations = {k: a for k, a in self._attestations.items() if maintenant - a.instant < DUREE_ATTESTATION}
        attestation = Attestation(verdict, score, maintenant, profil)
        for texte in (resultat.texte, analyser_eveil(resultat.texte).commande):
            cle = normaliser(texte)
            if cle:
                self._attestations[cle] = attestation
        if verdict not in ("reconnu", "non_verifie"):
            journal.info("Voix : verdict « %s » (score %s)", verdict, score)

    def derniere_reconnue(self) -> Attestation | None:
        """La dernière phrase reconnue comme celle du propriétaire, dans les 2 dernières minutes (actions 🔴 maison)."""
        maintenant = self.horloge()
        trouvees = [
            a
            for a in self._attestations.values()
            if a.verdict == "reconnu" and a.profil is None and maintenant - a.instant < DUREE_ATTESTATION
        ]
        return max(trouvees, key=lambda a: a.instant) if trouvees else None

    def attestation(self, phrase: str) -> Attestation | None:
        """L'attestation d'une transcription récente qui correspond à la phrase (égale, ou l'une contient l'autre)."""
        cle = normaliser(phrase)
        if not cle:
            return None
        maintenant = self.horloge()
        trouvees = [
            a
            for t, a in self._attestations.items()
            if maintenant - a.instant < DUREE_ATTESTATION and (t == cle or (len(cle) >= 8 and (cle in t or t in cle)))
        ]
        return max(trouvees, key=lambda a: a.instant) if trouvees else None

    async def garder(self, phrase: str, niveau: str, annoncee_voix: bool = False, acteur: str = "voix") -> None:
        """Refuse (ErreurAction) une action 🟡🔴 venue de la voix si le propriétaire n'est pas reconnu."""
        if niveau == "vert":
            return
        reglages = await self.charger()
        if not reglages["actif"]:
            return
        attestation = self.attestation(phrase)
        if attestation is None and not annoncee_voix:
            return  # phrase tapée : rien à vérifier
        if attestation is not None and attestation.verdict == "reconnu":
            return
        verdict = attestation.verdict if attestation is not None else "absente"
        raison = MESSAGES[verdict]
        from .securite import audit

        await audit.journaliser(
            self.pool,
            acteur=acteur,
            action="voix.action_refusee",
            niveau="jaune",
            details={"verdict": verdict, "score": attestation.score if attestation is not None else None},
        )
        raise ErreurAction(f"Action refusée à la voix : {raison}. Faites la demande à l'écran.")
