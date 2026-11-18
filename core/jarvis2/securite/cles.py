"""Clés d'accès (WebAuthn) : enregistrement sur un appareil, puis approbation des actions 🔴.

Chaque approbation signe un défi lié à UNE demande (vérification de l'utilisateur exigée : empreinte, visage ou
code de l'appareil). L'identifiant de partie (rp_id) est le nom d'hôte de la page : une adresse IP n'est pas
acceptée par les navigateurs, il faut ouvrir l'interface par `localhost` ou par un nom (ex. Tailscale).
"""

from __future__ import annotations

import ipaddress
import json
from datetime import timedelta
from typing import Any
from uuid import UUID

import asyncpg
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from ..db import Executant

DUREE_DEFI = timedelta(minutes=5)
NOM_PARTIE = "JARVIS 2"


class ErreurCle(Exception):
    """Message en français, affichable tel quel."""


def partie(hote: str) -> str:
    """rp_id à partir de l'en-tête Host (sans port) ; refuse une adresse IP."""
    nom = hote.rsplit(":", 1)[0] if not hote.startswith("[") else hote.split("]")[0].lstrip("[")
    try:
        ipaddress.ip_address(nom)
    except ValueError:
        return nom.lower()
    raise ErreurCle("Les clés d'accès exigent un nom d'hôte : ouvrez l'interface par http://localhost:<port>")


async def _garder_defi(conn: Executant, defi: bytes, type_: str, appareil: UUID, demande: UUID | None) -> None:
    await conn.execute("DELETE FROM defis_webauthn WHERE expire_le < now()")
    await conn.execute(
        "INSERT INTO defis_webauthn (defi, type, appareil_id, demande_id, expire_le)"
        " VALUES ($1, $2, $3, $4, now() + $5)",
        bytes_to_base64url(defi),
        type_,
        appareil,
        demande,
        DUREE_DEFI,
    )


async def _consommer_defi(conn: Executant, client_data: str, type_: str, appareil: UUID, demande: UUID | None) -> bytes:
    """Le défi signé doit avoir été émis pour cet appareil (et cette demande), ne sert qu'une fois."""
    try:
        defi = json.loads(base64url_to_bytes(client_data))["challenge"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ErreurCle("Réponse de la clé d'accès illisible") from exc
    trouve = await conn.fetchval(
        "DELETE FROM defis_webauthn WHERE defi = $1 AND type = $2 AND appareil_id = $3"
        " AND demande_id IS NOT DISTINCT FROM $4 AND expire_le > now() RETURNING defi",
        defi,
        type_,
        appareil,
        demande,
    )
    if trouve is None:
        raise ErreurCle("Défi inconnu, expiré ou déjà utilisé : recommencez")
    return base64url_to_bytes(defi)


async def options_enregistrement(conn: Executant, appareil: UUID, nom_appareil: str, rp_id: str) -> dict[str, Any]:
    existantes = await conn.fetch("SELECT id FROM cles_acces WHERE appareil_id = $1", appareil)
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=NOM_PARTIE,
        user_id=appareil.bytes,
        user_name=nom_appareil,
        user_display_name=nom_appareil,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED, user_verification=UserVerificationRequirement.REQUIRED
        ),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(r["id"])) for r in existantes],
    )
    await _garder_defi(conn, options.challenge, "enregistrement", appareil, None)
    resultat: dict[str, Any] = json.loads(options_to_json(options))
    return resultat


async def enregistrer(
    conn: Executant,
    appareil: UUID,
    credential: dict[str, Any],
    nom: str,
    rp_id: str,
    origine: str,
) -> str:
    client_data = str(credential.get("response", {}).get("clientDataJSON", ""))
    defi = await _consommer_defi(conn, client_data, "enregistrement", appareil, None)
    try:
        verifiee = verify_registration_response(
            credential=credential,
            expected_challenge=defi,
            expected_rp_id=rp_id,
            expected_origin=origine,
            require_user_verification=True,
        )
    except InvalidRegistrationResponse as exc:
        raise ErreurCle(f"Clé d'accès refusée : {exc}") from exc
    ident = bytes_to_base64url(verifiee.credential_id)
    await conn.execute(
        "INSERT INTO cles_acces (id, appareil_id, nom, cle_publique, compteur) VALUES ($1, $2, $3, $4, $5)",
        ident,
        appareil,
        nom.strip()[:80] or "Clé d'accès",
        verifiee.credential_public_key,
        verifiee.sign_count,
    )
    return ident


async def cles_utilisables(conn: Executant) -> list[asyncpg.Record]:
    """Clés d'accès des appareils non révoqués."""
    return await conn.fetch(
        "SELECT c.id, c.nom, c.cle_publique, c.compteur, c.appareil_id FROM cles_acces c"
        " JOIN appareils a ON a.id = c.appareil_id WHERE a.revoque_le IS NULL ORDER BY c.cree_le"
    )


async def options_approbation(conn: Executant, appareil: UUID, demande: UUID, rp_id: str) -> dict[str, Any]:
    cles = await cles_utilisables(conn)
    if not cles:
        raise ErreurCle("Aucune clé d'accès enregistrée : ajoutez-en une dans Sécurité pour approuver les actions 🔴")
    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(c["id"])) for c in cles],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    await _garder_defi(conn, options.challenge, "approbation", appareil, demande)
    resultat: dict[str, Any] = json.loads(options_to_json(options))
    return resultat


async def verifier_approbation(
    conn: Executant,
    appareil: UUID,
    demande: UUID,
    credential: dict[str, Any],
    rp_id: str,
    origine: str,
) -> str:
    """Vérifie la signature d'une approbation ; renvoie le nom de la clé utilisée."""
    client_data = str(credential.get("response", {}).get("clientDataJSON", ""))
    defi = await _consommer_defi(conn, client_data, "approbation", appareil, demande)
    cle = next((c for c in await cles_utilisables(conn) if c["id"] == credential.get("id")), None)
    if cle is None:
        raise ErreurCle("Clé d'accès inconnue ou appareil révoqué")
    try:
        verifiee = verify_authentication_response(
            credential=credential,
            expected_challenge=defi,
            expected_rp_id=rp_id,
            expected_origin=origine,
            credential_public_key=bytes(cle["cle_publique"]),
            credential_current_sign_count=int(cle["compteur"]),
            require_user_verification=True,
        )
    except InvalidAuthenticationResponse as exc:
        raise ErreurCle(f"Approbation refusée : {exc}") from exc
    await conn.execute(
        "UPDATE cles_acces SET compteur = $2, dernier_usage = now() WHERE id = $1", cle["id"], verifiee.new_sign_count
    )
    nom: str = cle["nom"]
    return nom
