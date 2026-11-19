"""Philips Hue par l'API locale du pont (API v1, HTTPS sur le réseau local) : rien ne passe par le cloud Hue.

- Découverte : mDNS (`_hue._tcp.local`) sur le réseau local ; le service en ligne de Signify
  (discovery.meethue.com) seulement si l'utilisateur l'accepte explicitement.
- Appairage : l'utilisateur appuie sur le bouton du pont, puis JARVIS demande une clé (« username ») gardée dans le
  coffre local.
- Le pont présente un certificat signé par l'autorité de Signify, absente des magasins du système : il n'est donc
  pas vérifié. En contrepartie, l'adresse doit être privée (réseau local) : la clé ne part jamais sur Internet.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import struct
from dataclasses import dataclass
from typing import Any

import httpx

DELAI = 6.0
URL_DECOUVERTE = "https://discovery.meethue.com/"
SERVICE_MDNS = "_hue._tcp.local"
GROUPE_MDNS = ("224.0.0.251", 5353)
COULEUR = re.compile(r"^#?([0-9a-fA-F]{6})$")


class ErreurHue(RuntimeError):
    """Message en français, affichable tel quel."""


def adresse_locale(adresse: str, boucle: bool = False) -> str:
    """Adresse IP privée (réseau local) ou, si `boucle`, de bouclage ; sinon refus."""
    texte = adresse.strip()
    hote, _, port = texte.rpartition(":") if texte.count(":") == 1 else (texte, "", "")
    try:
        ip = ipaddress.ip_address(hote)
    except ValueError as exc:
        raise ErreurHue("Adresse invalide : une adresse IP du réseau local est attendue (ex. 192.168.1.20)") from exc
    if not (ip.is_private and not ip.is_loopback and not ip.is_unspecified) and not (boucle and ip.is_loopback):
        raise ErreurHue("Adresse refusée : seules les adresses du réseau local sont acceptées")
    if port and not (port.isdigit() and 0 < int(port) < 65536):
        raise ErreurHue("Port invalide")
    return f"{ip}:{port}" if port else str(ip)


def couleur_xy(hexa: str) -> list[float]:
    """« #RRGGBB » → coordonnées CIE xy (gamut large, formule publiée par Philips)."""
    m = COULEUR.match(hexa.strip())
    if not m:
        raise ErreurHue("Couleur invalide : format #RRGGBB attendu")
    valeurs = [int(m.group(1)[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = (((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92 for v in valeurs)
    x = r * 0.664511 + g * 0.154324 + b * 0.162028
    y = r * 0.283881 + g * 0.668433 + b * 0.047685
    z = r * 0.000088 + g * 0.072310 + b * 0.986039
    total = x + y + z
    return [0.3227, 0.329] if total == 0 else [round(x / total, 4), round(y / total, 4)]


def luminosite_pont(pourcent: Any) -> int:
    try:
        valeur = float(pourcent)
    except (TypeError, ValueError) as exc:
        raise ErreurHue("Luminosité invalide : un pourcentage de 1 à 100 est attendu") from exc
    if not 1 <= valeur <= 100:
        raise ErreurHue("Luminosité invalide : un pourcentage de 1 à 100 est attendu")
    return max(1, round(valeur * 254 / 100))


# --- Découverte ------------------------------------------------------------------------------------------


def requete_mdns(service: str = SERVICE_MDNS) -> bytes:
    """Question PTR « QU » (réponse en unicast demandée) pour `service`."""
    nom = b"".join(bytes([len(p)]) + p.encode() for p in service.split(".")) + b"\x00"
    return struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0) + nom + struct.pack("!HH", 12, 0x8001)


def reponse_hue(paquet: bytes) -> bool:
    """Réponse mDNS (bit QR) qui parle du service Hue."""
    return len(paquet) >= 12 and bool(paquet[2] & 0x80) and b"\x04_hue" in paquet


async def decouvrir_mdns(delai: float = 2.0) -> list[str]:
    """Adresses des ponts qui répondent sur le réseau local (rien ne sort du réseau local)."""
    boucle = asyncio.get_running_loop()
    trouves: set[str] = set()

    class Protocole(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
            if reponse_hue(data):
                trouves.add(str(addr[0]))

    prise = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    prise.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)  # jamais au-delà du réseau local
    prise.bind(("0.0.0.0", 0))  # noqa: S104 — port éphémère, pour recevoir les réponses unicast
    prise.setblocking(False)
    transport, _ = await boucle.create_datagram_endpoint(Protocole, sock=prise)
    try:
        transport.sendto(requete_mdns(), GROUPE_MDNS)
        await asyncio.sleep(delai)
    finally:
        transport.close()
    return sorted(a for a in trouves if _privee(a))


def _privee(adresse: str) -> bool:
    try:
        adresse_locale(adresse)
    except ErreurHue:
        return False
    return True


async def decouvrir_en_ligne(transport: httpx.AsyncBaseTransport | None = None) -> list[str]:
    """Service de Signify : à n'appeler qu'avec l'accord explicite de l'utilisateur (il voit l'adresse publique)."""
    async with httpx.AsyncClient(timeout=DELAI, transport=transport) as client:
        try:
            rep = await client.get(URL_DECOUVERTE)
            rep.raise_for_status()
            ponts = rep.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ErreurHue("Service de découverte Hue injoignable") from exc
    adresses = (
        [str(p.get("internalipaddress", "")) for p in ponts if isinstance(p, dict)] if isinstance(ponts, list) else []
    )
    return sorted({a for a in adresses if _privee(a)})


# --- Pont --------------------------------------------------------------------------------------------------


@dataclass
class PontHue:
    adresse: str
    cle: str | None = None
    transport: httpx.AsyncBaseTransport | None = None

    def _client(self) -> httpx.AsyncClient:
        # verify=False : certificat de l'AC Signify (voir l'en-tête) ; adresse privée imposée par adresse_locale
        return httpx.AsyncClient(
            base_url=f"https://{adresse_locale(self.adresse)}/api",
            timeout=DELAI,
            verify=False,  # noqa: S501
            transport=self.transport,
        )

    async def _appel(self, methode: str, chemin: str, corps: Any = None) -> Any:
        try:
            async with self._client() as client:
                rep = await client.request(methode, chemin, json=corps)
                rep.raise_for_status()
                donnees = rep.json()
        except httpx.HTTPError as exc:
            raise ErreurHue(f"Pont Hue injoignable à {self.adresse}") from exc
        except ValueError as exc:
            raise ErreurHue("Réponse illisible : est-ce bien un pont Hue ?") from exc
        if isinstance(donnees, list):
            erreurs = [d["error"] for d in donnees if isinstance(d, dict) and "error" in d]
            if erreurs:
                e = erreurs[0]
                if e.get("type") == 1:
                    raise ErreurHue("Clé du pont refusée : appairez de nouveau JARVIS")
                if e.get("type") == 101:
                    raise ErreurHue("Appuyez sur le bouton du pont Hue, puis relancez l'appairage (30 s)")
                raise ErreurHue(f"Le pont a refusé : {e.get('description', 'erreur')}")
        return donnees

    def _chemin(self, suite: str) -> str:
        if not self.cle:
            raise ErreurHue("Pont Hue non appairé")
        return f"/{self.cle}/{suite}"

    async def appairer(self, appareil: str = "jarvis2#pc") -> str:
        """Le bouton du pont doit avoir été pressé dans les 30 s : renvoie la clé (à mettre dans le coffre)."""
        donnees = await self._appel("POST", "", {"devicetype": appareil[:40]})
        try:
            cle = str(donnees[0]["success"]["username"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ErreurHue("Appairage refusé par le pont") from exc
        self.cle = cle
        return cle

    async def etat(self) -> dict[str, Any]:
        lumieres = await self._appel("GET", self._chemin("lights"))
        groupes = await self._appel("GET", self._chemin("groups"))
        scenes = await self._appel("GET", self._chemin("scenes"))
        return {
            "lumieres": [
                {
                    "id": str(i),
                    "nom": str(lampe.get("name", i)),
                    "allumee": bool((lampe.get("state") or {}).get("on")),
                    "joignable": bool((lampe.get("state") or {}).get("reachable", True)),
                    "luminosite": round(int((lampe.get("state") or {}).get("bri", 0)) * 100 / 254),
                }
                for i, lampe in (lumieres or {}).items()
            ],
            "groupes": [
                {"id": str(i), "nom": str(g.get("name", i)), "type": g.get("type")} for i, g in (groupes or {}).items()
            ],
            "scenes": [
                {"id": str(i), "nom": str(s.get("name", i)), "groupe": s.get("group")}
                for i, s in (scenes or {}).items()
            ],
        }

    async def regler(self, cible: str, ident: str, etat: dict[str, Any]) -> None:
        """`cible` : « lumiere » (état d'une lampe) ou « groupe » (pièce, zone ; « 0 » : toutes les lampes)."""
        if not re.fullmatch(r"[0-9]{1,4}", ident):
            raise ErreurHue("Identifiant de lampe ou de groupe invalide")
        if cible == "lumiere":
            await self._appel("PUT", self._chemin(f"lights/{ident}/state"), etat)
        elif cible == "groupe":
            await self._appel("PUT", self._chemin(f"groups/{ident}/action"), etat)
        else:
            raise ErreurHue("Cible : « lumiere » ou « groupe »")

    async def scene(self, ident: str) -> dict[str, Any]:
        scenes = await self._appel("GET", self._chemin("scenes"))
        if not isinstance(scenes, dict) or ident not in scenes:
            raise ErreurHue(f"Scène Hue inconnue : « {ident} »")
        groupe = str(scenes[ident].get("group") or "0")
        await self._appel("PUT", self._chemin(f"groups/{groupe}/action"), {"scene": ident})
        return {"scene": ident, "nom": scenes[ident].get("name"), "groupe": groupe}
