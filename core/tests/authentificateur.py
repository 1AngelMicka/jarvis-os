"""Authentificateur WebAuthn logiciel (tests) : crée une clé ES256 et signe les défis comme un vrai appareil."""

from __future__ import annotations

import hashlib
import json
import secrets
import struct
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import bytes_to_base64url, encode_cbor


def _b64(data: bytes) -> str:
    return bytes_to_base64url(data)


class Authentificateur:
    def __init__(self, rp_id: str = "localhost", origine: str = "http://localhost:8765") -> None:
        self.rp_id = rp_id
        self.origine = origine
        self.cle = ec.generate_private_key(ec.SECP256R1())
        self.id = secrets.token_bytes(16)
        self.compteur = 0

    def _client_data(self, type_: str, defi: str) -> bytes:
        return json.dumps(
            {"type": type_, "challenge": defi, "origin": self.origine, "crossOrigin": False}, separators=(",", ":")
        ).encode()

    def _auth_data(self, drapeaux: int, attestee: bytes = b"") -> bytes:
        self.compteur += 1
        return (
            hashlib.sha256(self.rp_id.encode()).digest()
            + bytes([drapeaux])
            + struct.pack(">I", self.compteur)
            + attestee
        )

    def creer(self, options: dict[str, Any]) -> dict[str, Any]:
        """Réponse à `navigator.credentials.create()` (attestation « none »)."""
        publique = self.cle.public_key().public_numbers()
        cose = encode_cbor({1: 2, 3: -7, -1: 1, -2: publique.x.to_bytes(32, "big"), -3: publique.y.to_bytes(32, "big")})
        attestee = bytes(16) + struct.pack(">H", len(self.id)) + self.id + cose
        auth_data = self._auth_data(0x45, attestee)  # présence + vérification + données attestées
        objet = encode_cbor({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": _b64(self.id),
            "rawId": _b64(self.id),
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64(self._client_data("webauthn.create", options["challenge"])),
                "attestationObject": _b64(objet),
            },
        }

    def signer(self, options: dict[str, Any], defi: str | None = None) -> dict[str, Any]:
        """Réponse à `navigator.credentials.get()` (vérification de l'utilisateur faite)."""
        client_data = self._client_data("webauthn.get", defi or options["challenge"])
        auth_data = self._auth_data(0x05)
        signature = self.cle.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "id": _b64(self.id),
            "rawId": _b64(self.id),
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64(client_data),
                "authenticatorData": _b64(auth_data),
                "signature": _b64(signature),
                "userHandle": None,
            },
        }
