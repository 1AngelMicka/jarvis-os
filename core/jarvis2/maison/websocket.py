"""Client WebSocket minimal (RFC 6455, texte seulement), sans dépendance : juste ce qu'il faut pour OBS.

Une connexion courte par commande : poignée de main HTTP, trames texte masquées côté client, réponse aux « ping »,
fermeture propre. Pas de TLS : OBS écoute en clair sur le PC ou le réseau local (adresse vérifiée par l'appelant).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import os
import struct

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
TAILLE_MAX = 4 * 1024 * 1024  # une réponse d'OBS (liste des scènes) tient largement là-dedans


class ErreurWebSocket(ConnectionError):
    """Message en français, affichable tel quel."""


def cle_acceptee(cle: str) -> str:
    # SHA-1 imposé par la RFC 6455 pour la poignée de main (aucun usage de sécurité)
    return base64.b64encode(hashlib.sha1((cle + GUID).encode(), usedforsecurity=False).digest()).decode()


def trame(opcode: int, charge: bytes, masque: bytes | None) -> bytes:
    """Trame finale ; `masque` : 4 octets (client → serveur), None (serveur → client)."""
    tete = bytes([0x80 | opcode])
    bit = 0x80 if masque is not None else 0
    n = len(charge)
    if n < 126:
        tete += bytes([bit | n])
    elif n < 1 << 16:
        tete += bytes([bit | 126]) + struct.pack("!H", n)
    else:
        tete += bytes([bit | 127]) + struct.pack("!Q", n)
    if masque is None:
        return tete + charge
    return tete + masque + bytes(b ^ masque[i % 4] for i, b in enumerate(charge))


async def lire_trame(lecteur: asyncio.StreamReader) -> tuple[int, bytes]:
    """(opcode, charge) d'une trame entière ; les fragments (opcode 0) sont recollés."""
    morceaux: list[bytes] = []
    premier = -1
    while True:
        b0, b1 = await lecteur.readexactly(2)
        opcode, n = b0 & 0x0F, b1 & 0x7F
        if n == 126:
            (n,) = struct.unpack("!H", await lecteur.readexactly(2))
        elif n == 127:
            (n,) = struct.unpack("!Q", await lecteur.readexactly(8))
        if n > TAILLE_MAX:
            raise ErreurWebSocket("Réponse WebSocket trop grande")
        masque = await lecteur.readexactly(4) if b1 & 0x80 else None
        charge = await lecteur.readexactly(n)
        if masque is not None:
            charge = bytes(b ^ masque[i % 4] for i, b in enumerate(charge))
        if opcode >= 0x8:  # trame de contrôle : jamais fragmentée, rendue tout de suite
            return opcode, charge
        if premier < 0:
            premier = opcode
        morceaux.append(charge)
        if b0 & 0x80:
            return premier, b"".join(morceaux)


class ClientWebSocket:
    def __init__(self, lecteur: asyncio.StreamReader, ecrivain: asyncio.StreamWriter) -> None:
        self.lecteur = lecteur
        self.ecrivain = ecrivain

    @classmethod
    async def ouvrir(cls, hote: str, port: int, chemin: str = "/", protocole: str | None = None) -> ClientWebSocket:
        try:
            lecteur, ecrivain = await asyncio.open_connection(hote, port)
        except OSError as exc:
            raise ErreurWebSocket(f"Connexion impossible à {hote}:{port}") from exc
        cle = base64.b64encode(os.urandom(16)).decode()
        lignes = [
            f"GET {chemin} HTTP/1.1",
            f"Host: {hote}:{port}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {cle}",
            "Sec-WebSocket-Version: 13",
        ]
        if protocole:
            lignes.append(f"Sec-WebSocket-Protocol: {protocole}")
        ecrivain.write(("\r\n".join(lignes) + "\r\n\r\n").encode())
        await ecrivain.drain()
        try:
            entete = await lecteur.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
            ecrivain.close()
            raise ErreurWebSocket("Poignée de main WebSocket refusée") from exc
        statut, *champs = entete.decode("latin-1").split("\r\n")
        valeurs = {k.strip().lower(): v.strip() for k, _, v in (c.partition(":") for c in champs if c)}
        if " 101 " not in f"{statut} " or valeurs.get("sec-websocket-accept") != cle_acceptee(cle):
            ecrivain.close()
            raise ErreurWebSocket("Ce service ne parle pas WebSocket (est-ce bien OBS ?)")
        return cls(lecteur, ecrivain)

    async def envoyer(self, texte: str) -> None:
        self.ecrivain.write(trame(0x1, texte.encode("utf-8"), os.urandom(4)))
        await self.ecrivain.drain()

    async def recevoir(self) -> str:
        while True:
            try:
                opcode, charge = await lire_trame(self.lecteur)
            except asyncio.IncompleteReadError as exc:
                raise ErreurWebSocket("Connexion WebSocket coupée") from exc
            if opcode == 0x1:
                return charge.decode("utf-8")
            if opcode == 0x9:  # ping → pong
                self.ecrivain.write(trame(0xA, charge, os.urandom(4)))
                await self.ecrivain.drain()
            elif opcode == 0x8:
                code = struct.unpack("!H", charge[:2])[0] if len(charge) >= 2 else 1005
                raise ErreurWebSocket(f"Connexion fermée par le serveur (code {code})")

    async def fermer(self) -> None:
        with contextlib.suppress(OSError, RuntimeError):
            self.ecrivain.write(trame(0x8, struct.pack("!H", 1000), os.urandom(4)))
            await self.ecrivain.drain()
        self.ecrivain.close()
        with contextlib.suppress(OSError):
            await self.ecrivain.wait_closed()
