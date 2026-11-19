"""Notifications Web Push vers le téléphone (PWA), sans service tiers à configurer.

- **Clés VAPID générées localement** au premier besoin, rangées dans le dossier des données (`push/vapid.pem`,
  lisible du seul utilisateur) : jamais dans git, jamais en base, jamais dans un journal.
- **Chiffrement de bout en bout** (RFC 8291, `aes128gcm`) : le service de notification du navigateur (Google, Apple,
  Mozilla, Microsoft) transporte un message qu'il ne peut pas lire. Le message reste court et générique (« une
  action 🔴 attend ta décision ») : le détail ne s'affiche qu'une fois l'interface ouverte, avec le jeton de
  l'appareil.
- **Adresses permises** : seulement les services de notification connus, en HTTPS (un appareil ne peut pas faire
  envoyer de requête par le Core vers une adresse de son choix).
- Abonnement expiré (404 / 410) : retiré tout seul.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import struct
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from cryptography.hazmat.primitives import hashes, hmac, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .db import Base

if TYPE_CHECKING:
    from .securite.permissions import Approbations, Demande

journal = logging.getLogger("jarvis2.push")

# Contact VAPID exigé par les services : l'adresse publique du projet, jamais celle de l'utilisateur
CONTACT_VAPID = "https://github.com/1AngelMicka/jarvis-os"
DUREE_VIE = 60 * 60  # TTL : un rappel vieux de plus d'une heure n'a plus de sens
TAILLE_MAX = 3000  # octets de message en clair (les services acceptent ~4 Ko chiffrés)
HOTES_PERMIS = (
    "fcm.googleapis.com",
    "updates.push.services.mozilla.com",
    "push.services.mozilla.com",
    "web.push.apple.com",
)
SUFFIXES_PERMIS = (".push.apple.com", ".notify.windows.com")
INTERVALLE_RAPPELS = 30.0

Envoyeur = Callable[[str, dict[str, str], bytes], Awaitable[int]]


class ErreurPush(ValueError):
    """Message en français, affichable tel quel."""


def b64(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode()


def deb64(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def adresse_permise(endpoint: str) -> bool:
    try:
        u = urlsplit(endpoint)
    except ValueError:
        return False
    hote = (u.hostname or "").lower()
    return (
        u.scheme == "https"
        and u.port in (None, 443)
        and not u.username
        and (hote in HOTES_PERMIS or hote.endswith(SUFFIXES_PERMIS))
    )


# --- Clés VAPID ---------------------------------------------------------------------------------------------


def charger_ou_creer_cle(dossier: Path) -> ec.EllipticCurvePrivateKey:
    """Clé privée VAPID du dossier des données ; créée (droits 0600) si elle n'existe pas."""
    chemin = dossier / "push" / "vapid.pem"
    if chemin.exists():
        cle = serialization.load_pem_private_key(chemin.read_bytes(), password=None)
        if not isinstance(cle, ec.EllipticCurvePrivateKey):
            raise ErreurPush("Clé VAPID illisible : supprimez push/vapid.pem pour en recréer une")
        return cle
    chemin.parent.mkdir(parents=True, exist_ok=True)
    cle = ec.generate_private_key(ec.SECP256R1())
    pem = cle.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    descripteur = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descripteur, "wb") as f:
        f.write(pem)
    journal.info("Clés de notification (VAPID) créées dans le dossier des données")
    return cle


def cle_publique_brute(cle: ec.EllipticCurvePrivateKey) -> bytes:
    return cle.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def jeton_vapid(cle: ec.EllipticCurvePrivateKey, endpoint: str, maintenant: float | None = None) -> str:
    """JWT ES256 (RFC 8292) : audience = origine du service, valable 12 h."""
    u = urlsplit(endpoint)
    entete = b64(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    revendications = {
        "aud": f"{u.scheme}://{u.netloc}",
        "exp": int((maintenant or time.time()) + 12 * 3600),
        "sub": CONTACT_VAPID,
    }
    corps = b64(json.dumps(revendications, separators=(",", ":")).encode())
    signature_der = cle.sign(f"{entete}.{corps}".encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(signature_der)
    return f"{entete}.{corps}.{b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


# --- Chiffrement RFC 8291 (aes128gcm) -----------------------------------------------------------------------


def _hmac(cle: bytes, donnees: bytes) -> bytes:
    h = hmac.HMAC(cle, hashes.SHA256())
    h.update(donnees)
    return h.finalize()


def chiffrer(
    message: bytes,
    p256dh: str,
    auth: str,
    *,
    cle_serveur: ec.EllipticCurvePrivateKey | None = None,
    sel: bytes | None = None,
) -> bytes:
    """Corps chiffré pour l'abonnement (clé publique `p256dh` et secret `auth` du navigateur)."""
    ua_public = deb64(p256dh)
    secret_auth = deb64(auth)
    if len(ua_public) != 65 or ua_public[0] != 4 or len(secret_auth) != 16:
        raise ErreurPush("Clés d'abonnement invalides")
    cle_ua = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    ephemere = cle_serveur or ec.generate_private_key(ec.SECP256R1())
    as_public = cle_publique_brute(ephemere)
    partage = ephemere.exchange(ec.ECDH(), cle_ua)
    prk_cle = _hmac(secret_auth, partage)
    ikm = _hmac(prk_cle, b"WebPush: info\x00" + ua_public + as_public + b"\x01")
    sel = sel or os.urandom(16)
    prk = _hmac(sel, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    chiffre = AESGCM(cek).encrypt(nonce, message + b"\x02", None)  # un seul enregistrement, délimiteur final
    return sel + struct.pack(">I", 4096) + bytes([len(as_public)]) + as_public + chiffre


async def envoyer_http(endpoint: str, entetes: dict[str, str], corps: bytes) -> int:
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        reponse = await client.post(endpoint, headers=entetes, content=corps)
    return reponse.status_code


@dataclass(frozen=True, slots=True)
class Abonnement:
    id: UUID
    appareil_id: UUID
    endpoint: str
    p256dh: str
    auth: str


class ServicePush:
    def __init__(self, pool: Base, dossier: Path | None, envoyeur: Envoyeur = envoyer_http) -> None:
        self.pool = pool
        self.dossier = dossier
        self.envoyeur = envoyeur
        self._cle: ec.EllipticCurvePrivateKey | None = None

    @property
    def disponible(self) -> bool:
        return self.dossier is not None

    def cle(self) -> ec.EllipticCurvePrivateKey:
        if self.dossier is None:
            raise ErreurPush("Notifications indisponibles : aucun dossier des données")
        if self._cle is None:
            self._cle = charger_ou_creer_cle(self.dossier)
        return self._cle

    def cle_publique(self) -> str:
        return b64(cle_publique_brute(self.cle()))

    async def abonner(self, appareil: UUID, endpoint: str, p256dh: str, auth: str) -> None:
        if not adresse_permise(endpoint):
            raise ErreurPush("Service de notification non reconnu (HTTPS des navigateurs connus seulement)")
        chiffrer(b"essai", p256dh, auth)  # refuse tout de suite des clés illisibles
        await self.pool.execute(
            "INSERT INTO abonnements_push (appareil_id, endpoint, p256dh, auth) VALUES ($1, $2, $3, $4)"
            " ON CONFLICT (endpoint) DO UPDATE SET appareil_id = excluded.appareil_id, p256dh = excluded.p256dh,"
            " auth = excluded.auth, echecs = 0",
            appareil,
            endpoint,
            p256dh,
            auth,
        )

    async def desabonner(self, appareil: UUID, endpoint: str | None = None) -> int:
        if endpoint is None:
            statut = await self.pool.execute("DELETE FROM abonnements_push WHERE appareil_id = $1", appareil)
        else:
            statut = await self.pool.execute(
                "DELETE FROM abonnements_push WHERE appareil_id = $1 AND endpoint = $2", appareil, endpoint
            )
        return int(statut.rsplit(" ", 1)[-1] or 0)

    async def abonne(self, appareil: UUID) -> bool:
        return bool(await self.pool.fetchval("SELECT count(*) FROM abonnements_push WHERE appareil_id = $1", appareil))

    async def _abonnements(self, appareil: UUID | None) -> list[Abonnement]:
        lignes = await self.pool.fetch(
            "SELECT p.id, p.appareil_id, p.endpoint, p.p256dh, p.auth FROM abonnements_push p"
            " JOIN appareils a ON a.id = p.appareil_id"
            " WHERE a.revoque_le IS NULL AND ($1::uuid IS NULL OR p.appareil_id = $1)",
            appareil,
        )
        return [Abonnement(r["id"], r["appareil_id"], r["endpoint"], r["p256dh"], r["auth"]) for r in lignes]

    async def envoyer(self, message: dict[str, Any], appareil: UUID | None = None) -> int:
        """Pousse `message` (titre, corps, url, etiquette) aux appareils abonnés ; renvoie le nombre de remises."""
        if not self.disponible:
            return 0
        clair = json.dumps(message, ensure_ascii=False).encode()
        if len(clair) > TAILLE_MAX:
            raise ErreurPush("Message de notification trop long")
        cle = self.cle()
        remis = 0
        for ab in await self._abonnements(appareil):
            if not adresse_permise(ab.endpoint):  # base modifiée à la main : on n'envoie pas
                continue
            entetes = {
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
                "TTL": str(DUREE_VIE),
                "Urgency": "high",
                "Authorization": f"vapid t={jeton_vapid(cle, ab.endpoint)}, k={self.cle_publique()}",
            }
            try:
                statut = await self.envoyeur(ab.endpoint, entetes, chiffrer(clair, ab.p256dh, ab.auth))
            except (httpx.HTTPError, OSError) as exc:
                journal.warning("Notification non remise (%s)", type(exc).__name__)
                statut = 0
            if statut in (404, 410):  # abonnement expiré ou retiré par le navigateur
                await self.pool.execute("DELETE FROM abonnements_push WHERE id = $1", ab.id)
            elif 200 <= statut < 300:
                remis += 1
                await self.pool.execute(
                    "UPDATE abonnements_push SET dernier_envoi = now(), echecs = 0 WHERE id = $1", ab.id
                )
            else:
                await self.pool.execute("UPDATE abonnements_push SET echecs = echecs + 1 WHERE id = $1", ab.id)
        return remis

    # --- Demandes : appel de décision ---------------------------------------------------------------------

    @staticmethod
    def message_demande(demande: Demande, description: str, rappel: bool = False) -> dict[str, Any]:
        """Message court et générique : ni paramètres ni résumé (ils ne quittent pas le PC)."""
        rouge = demande.niveau == "rouge"
        return {
            "titre": ("Rappel : " if rappel else "") + ("🔴 Décision demandée" if rouge else "🟡 Approbation demandée"),
            "corps": f"{description[:120]} — oui, non ou plus tard" + (" (clé d'accès pour oui)" if rouge else ""),
            "url": f"/#decision={demande.id}",
            "etiquette": f"demande-{demande.id}",
        }

    async def notifier_demande(self, demande: Demande, description: str, rappel: bool = False) -> int:
        try:
            return await self.envoyer(self.message_demande(demande, description, rappel))
        except ErreurPush as exc:
            journal.warning("Notification de demande impossible : %s", exc)
            return 0

    async def rappels(self, approbations: Approbations) -> int:
        """Demandes reportées (« plus tard ») dont l'heure de rappel est passée : un rappel chacune."""
        envoyes = 0
        for demande in await approbations.rappels_dus():
            action = approbations.registre.actions.get(demande.action)
            envoyes += await self.notifier_demande(demande, action.description if action else demande.action, True)
        return envoyes

    async def boucle(self, approbations: Approbations) -> None:
        while True:
            await asyncio.sleep(INTERVALLE_RAPPELS)
            try:
                await self.rappels(approbations)
            except Exception:  # la boucle ne doit jamais s'arrêter sur une erreur passagère
                journal.exception("Rappels des demandes")
