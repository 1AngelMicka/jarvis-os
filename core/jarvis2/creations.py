"""Créations : petites pages HTML générées à la demande, ouvertes dans un BAC À SABLE isolé.

- La page est servie seule (`/creations/<id>`) avec une CSP qui l'isole : `sandbox allow-scripts` (origine
  unique : ni cookies, ni stockage, ni accès à l'interface de JARVIS), `connect-src 'none'` (aucune requête réseau :
  rien ne peut sortir), aucune ressource externe.
- L'adresse porte un jeton signé à courte durée (l'iframe ne peut pas envoyer l'en-tête d'appareil).
- Chaque modification est une nouvelle version (`creation_versions`).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from typing import Any
from uuid import UUID

from .db import Base, Executant
from .dialogue import ServiceDialogue
from .moteurs.base import Message
from .securite.filtre import masquer

CSP_CREATION = (
    "sandbox allow-scripts allow-forms allow-modals; default-src 'none'; script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; "
    "form-action 'none'; base-uri 'none'; frame-ancestors {origine}"
)
DUREE_JETON = 600  # secondes
CONSIGNE = (
    "Tu es JARVIS et tu crées une petite page web autonome : UN SEUL fichier HTML complet (<!doctype html>), CSS et "
    "JavaScript en ligne, AUCUNE ressource externe (pas de CDN, pas de police en ligne, pas d'image distante, pas de "
    "requête réseau : elles seront bloquées). En français, soignée, utilisable sur téléphone. Réponds UNIQUEMENT par "
    "le code HTML."
)
# frame-ancestors nomme l'origine de l'interface : sous `sandbox`, « 'self' » désignerait l'origine opaque de la page
# elle-même et l'iframe serait bloquée.
SECRET = secrets.token_bytes(32)  # propre à ce démarrage du Core : un lien de création ne survit pas au redémarrage


def extraire_html(texte: str) -> str:
    """Le HTML de la réponse (bloc ```html … ``` ou document brut)."""
    bloc = re.search(r"```(?:html)?\s*(.*?)```", texte, re.DOTALL | re.IGNORECASE)
    html = (bloc.group(1) if bloc else texte).strip()
    debut = re.search(r"<!doctype html|<html", html, re.IGNORECASE)
    return html[debut.start() :] if debut else html


def jeton(creation: UUID, version: int, maintenant: float | None = None) -> str:
    expire = int((maintenant or time.time()) + DUREE_JETON)
    message = f"{creation}:{version}:{expire}".encode()
    signature = hmac.new(SECRET, message, hashlib.sha256).hexdigest()[:32]
    return f"{expire}.{signature}"


def verifier_jeton(creation: UUID, version: int, valeur: str, maintenant: float | None = None) -> bool:
    try:
        expire_texte, signature = valeur.split(".", 1)
        expire = int(expire_texte)
    except ValueError:
        return False
    if expire < (maintenant or time.time()):
        return False
    attendu = hmac.new(SECRET, f"{creation}:{version}:{expire}".encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(attendu, signature)


async def generer(dialogue: ServiceDialogue, demande: str, html_actuel: str | None = None) -> tuple[str, str]:
    """HTML d'une nouvelle création (ou version suivante) ; renvoie (html, identifiant du connecteur)."""
    instance = await dialogue.choisir_moteur(None, None, demande)
    texte = (
        demande
        if html_actuel is None
        else f"Page actuelle :\n```html\n{html_actuel}\n```\n\nModification demandée : {demande}"
    )
    messages = [Message("systeme", CONSIGNE), Message("utilisateur", texte)]
    if instance.interne.externe:
        messages = [Message(m.role, masquer(m.contenu).texte) for m in messages]
    reponse = await instance.generate(messages)
    html = extraire_html(reponse.texte)
    if "<" not in html:
        raise ValueError("La réponse ne contient pas de page HTML")
    return html, instance.id_moteur


async def creer(base: Base, dialogue: ServiceDialogue, titre: str, demande: str, acteur: str) -> dict[str, Any]:
    html, moteur = await generer(dialogue, demande)
    ident: UUID = await base.fetchval(
        "INSERT INTO creations (titre, description, version_courante, cree_par) VALUES ($1, $2, 1, $3) RETURNING id",
        titre.strip()[:200] or "Création",
        demande[:2000],
        acteur,
    )
    await base.execute(
        "INSERT INTO creation_versions (creation_id, version, html, demande, modele) VALUES ($1, 1, $2, $3, $4)",
        ident,
        html,
        demande[:4000],
        moteur,
    )
    return {"id": str(ident), "version": 1, "moteur": moteur}


async def modifier(base: Base, dialogue: ServiceDialogue, ident: UUID, demande: str) -> dict[str, Any]:
    actuelle = await page(base, ident)
    if actuelle is None:
        raise LookupError("Création introuvable")
    html, moteur = await generer(dialogue, demande, actuelle["html"])
    version = int(actuelle["version"]) + 1
    await base.execute(
        "INSERT INTO creation_versions (creation_id, version, html, demande, modele) VALUES ($1, $2, $3, $4, $5)",
        ident,
        version,
        html,
        demande[:4000],
        moteur,
    )
    await base.execute("UPDATE creations SET version_courante = $2, maj_le = now() WHERE id = $1", ident, version)
    return {"id": str(ident), "version": version, "moteur": moteur}


async def lister(conn: Executant) -> list[dict[str, Any]]:
    lignes = await conn.fetch(
        "SELECT id, titre, description, version_courante, cree_le, maj_le FROM creations WHERE NOT archive"
        " ORDER BY maj_le DESC LIMIT 50"
    )
    return [dict(r) for r in lignes]


async def page(conn: Executant, ident: UUID, version: int | None = None) -> dict[str, Any] | None:
    ligne = await conn.fetchrow(
        "SELECT v.version, v.html, c.titre FROM creations c JOIN creation_versions v ON v.creation_id = c.id"
        " WHERE c.id = $1 AND v.version = coalesce($2, c.version_courante)",
        ident,
        version,
    )
    return dict(ligne) if ligne else None
