"""Satellites vocaux, pièces et profils par personne (lot 14-D18).

- **Satellite** : un appareil qui écoute dans une pièce (Home Assistant Voice, ESP32-S3 sous ESPHome, ou tout client
  Wyoming). Il détecte lui-même le mot d'éveil ; seul l'audio APRÈS l'éveil part vers le PC (voir `wyoming.py`).
- **Une clé par appareil** : tirée au hasard à l'ajout, montrée UNE fois ; la base ne garde que son empreinte SHA-256.
  Retirer un satellite révoque sa clé.
- **Présence par pièce** : la dernière phrase entendue par un satellite note l'heure et la personne reconnue à la voix
  (propriétaire, profil, ou inconnue). Rien d'autre : ni le texte ni l'audio.
- **Plafond de volume** par satellite et par profil : la voix de JARVIS n'y dépasse jamais le plus bas des deux.
- **Profils par personne** : un nom et un plafond de volume ; les empreintes de voix (dossier des données, jamais en
  base) sont gérées par `proprietaire.py` sous l'identifiant du profil. Un profil n'est jamais le propriétaire.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from ..securite.permissions import ErreurAction

if TYPE_CHECKING:
    from ..db import Base, Ligne

PRESENCE = timedelta(minutes=10)  # une pièce est « occupée » 10 minutes après la dernière phrase entendue
COLONNES = "id, nom, piece, volume_max, actif, cree_le, vu_le, personne"


def empreinte(cle: str) -> str:
    return hashlib.sha256(cle.encode("utf-8")).hexdigest()


def identifiant(nom: str) -> str:
    base = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:30] or "appareil"
    return f"{base}-{secrets.token_hex(3)}"


def _texte(valeur: str, quoi: str) -> str:
    propre = " ".join(valeur.split())
    if not 1 <= len(propre) <= 60:
        raise ErreurAction(f"{quoi} : de 1 à 60 caractères")
    return propre


def _volume(valeur: Any) -> int:
    try:
        nombre = int(valeur)
    except (TypeError, ValueError) as exc:
        raise ErreurAction("Plafond de volume : de 0 à 100 %") from exc
    if not 0 <= nombre <= 100:
        raise ErreurAction("Plafond de volume : de 0 à 100 %")
    return nombre


def _date(valeur: Any) -> str | None:
    return valeur.isoformat() if isinstance(valeur, datetime) else (str(valeur) if valeur else None)


def _satellite(r: Ligne) -> dict[str, Any]:
    return {
        "id": r["id"],
        "nom": r["nom"],
        "piece": r["piece"],
        "volume_max": r["volume_max"],
        "actif": bool(r["actif"]),
        "cree_le": _date(r["cree_le"]),
        "vu_le": _date(r["vu_le"]),
        "personne": r["personne"],
    }


class ServiceSatellites:
    def __init__(self, pool: Base) -> None:
        self.pool = pool

    # -- satellites ------------------------------------------------------------------------------------------------

    async def lister(self) -> list[dict[str, Any]]:
        lignes = await self.pool.fetch(f"SELECT {COLONNES} FROM satellites_maison ORDER BY piece, nom")  # noqa: S608
        return [_satellite(r) for r in lignes]

    async def obtenir(self, ident: str) -> dict[str, Any] | None:
        r = await self.pool.fetchrow(f"SELECT {COLONNES} FROM satellites_maison WHERE id = $1", ident)  # noqa: S608
        return _satellite(r) if r else None

    async def ajouter(self, nom: str, piece: str, volume_max: Any = 70) -> tuple[dict[str, Any], str]:
        """Nouveau satellite : renvoie sa fiche et sa clé (montrée une seule fois, jamais gardée en clair)."""
        if int(await self.pool.fetchval("SELECT count(*) FROM satellites_maison") or 0) >= 50:
            raise ErreurAction("50 satellites au plus")
        propre = _texte(nom, "Nom")
        cle = secrets.token_urlsafe(32)
        ident = identifiant(propre)
        await self.pool.execute(
            "INSERT INTO satellites_maison (id, nom, piece, empreinte_cle, volume_max) VALUES ($1, $2, $3, $4, $5)",
            ident,
            propre,
            _texte(piece, "Pièce"),
            empreinte(cle),
            _volume(volume_max),
        )
        fiche = await self.obtenir(ident)
        assert fiche is not None
        return fiche, cle

    async def modifier(
        self, ident: str, nom: str | None = None, piece: str | None = None, volume_max: Any = None, actif: Any = None
    ) -> dict[str, Any]:
        actuel = await self.obtenir(ident)
        if actuel is None:
            raise ErreurAction("Satellite introuvable")
        await self.pool.execute(
            "UPDATE satellites_maison SET nom = $2, piece = $3, volume_max = $4, actif = $5 WHERE id = $1",
            ident,
            _texte(nom, "Nom") if nom is not None else actuel["nom"],
            _texte(piece, "Pièce") if piece is not None else actuel["piece"],
            _volume(volume_max) if volume_max is not None else actuel["volume_max"],
            bool(actif) if actif is not None else actuel["actif"],
        )
        fiche = await self.obtenir(ident)
        assert fiche is not None
        return fiche

    async def retirer(self, ident: str) -> bool:
        statut = await self.pool.execute("DELETE FROM satellites_maison WHERE id = $1", ident)
        return not statut.endswith(" 0")

    async def authentifier(self, ident: str, cle: str) -> dict[str, Any] | None:
        """Le satellite présente sa clé : empreinte comparée à temps constant ; satellite retiré ou coupé : refus."""
        r = await self.pool.fetchrow(
            f"SELECT {COLONNES}, empreinte_cle FROM satellites_maison WHERE id = $1",  # noqa: S608
            str(ident)[:40],
        )
        attendue = r["empreinte_cle"] if r else "0" * 64
        ok = hmac.compare_digest(empreinte(str(cle)), attendue)
        if r is None or not ok or not r["actif"]:
            return None
        return _satellite(r)

    async def vu(self, ident: str, personne: str | None) -> None:
        """Présence : une phrase vient d'être entendue par ce satellite (personne reconnue ou None)."""
        await self.pool.execute(
            "UPDATE satellites_maison SET vu_le = $2, personne = $3 WHERE id = $1",
            ident,
            datetime.now(UTC),
            personne,
        )

    async def pieces(self) -> list[dict[str, Any]]:
        """Pièces (celles des satellites) et présence : occupée si une voix y a été entendue depuis moins de 10 min."""
        maintenant = datetime.now(UTC)
        pieces: dict[str, dict[str, Any]] = {}
        noms = {p["id"]: p["nom"] for p in await self.profils()}
        for s in await self.lister():
            piece = pieces.setdefault(
                s["piece"], {"piece": s["piece"], "satellites": 0, "vu_le": None, "personne": None, "occupee": False}
            )
            piece["satellites"] += 1
            if s["vu_le"] and (piece["vu_le"] is None or s["vu_le"] > piece["vu_le"]):
                vu = datetime.fromisoformat(s["vu_le"])
                vu = vu if vu.tzinfo else vu.replace(tzinfo=UTC)
                piece.update(
                    vu_le=s["vu_le"],
                    personne=("Propriétaire" if s["personne"] == "proprietaire" else noms.get(s["personne"]))
                    if s["personne"]
                    else None,
                    occupee=maintenant - vu < PRESENCE,
                )
        return sorted(pieces.values(), key=lambda p: p["piece"])

    # -- profils -------------------------------------------------------------------------------------------------

    async def profils(self) -> list[dict[str, Any]]:
        lignes = await self.pool.fetch("SELECT id, nom, volume_max, cree_le FROM profils_voix ORDER BY nom")
        return [
            {"id": r["id"], "nom": r["nom"], "volume_max": r["volume_max"], "cree_le": _date(r["cree_le"])}
            for r in lignes
        ]

    async def profil(self, ident: str | None) -> dict[str, Any] | None:
        if not ident:
            return None
        return next((p for p in await self.profils() if p["id"] == ident), None)

    async def ajouter_profil(self, nom: str, volume_max: Any = 100) -> dict[str, Any]:
        if int(await self.pool.fetchval("SELECT count(*) FROM profils_voix") or 0) >= 20:
            raise ErreurAction("20 profils au plus")
        propre = _texte(nom, "Nom")
        ident = identifiant(propre)
        await self.pool.execute(
            "INSERT INTO profils_voix (id, nom, volume_max) VALUES ($1, $2, $3)", ident, propre, _volume(volume_max)
        )
        profil = await self.profil(ident)
        assert profil is not None
        return profil

    async def modifier_profil(self, ident: str, nom: str | None, volume_max: Any) -> dict[str, Any]:
        actuel = await self.profil(ident)
        if actuel is None:
            raise ErreurAction("Profil introuvable")
        await self.pool.execute(
            "UPDATE profils_voix SET nom = $2, volume_max = $3 WHERE id = $1",
            ident,
            _texte(nom, "Nom") if nom is not None else actuel["nom"],
            _volume(volume_max) if volume_max is not None else actuel["volume_max"],
        )
        profil = await self.profil(ident)
        assert profil is not None
        return profil

    async def retirer_profil(self, ident: str) -> bool:
        statut = await self.pool.execute("DELETE FROM profils_voix WHERE id = $1", ident)
        return not statut.endswith(" 0")
