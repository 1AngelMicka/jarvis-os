"""Diagnostic de l'installation (`jarvis2 docteur`, assistant de premier lancement).

Chaque vérification dit ce qu'elle voit, et ce qu'il faut faire : une réparation automatique sûre (`reparation`),
sinon une aide (commande ou lien). Rien n'est modifié par le diagnostic lui-même.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from . import telechargements
from .db import ErreurBaseOuReseau, Executant, lister_migrations, version_schema
from .securite import audit

if TYPE_CHECKING:
    from .config import Parametres
    from .connecteurs import Connecteurs
    from .tailscale import EtatTailscale

Statut = Literal["ok", "info", "attention", "erreur"]
ESPACE_MINIMUM = 2 * 1024**3  # modèle d'embeddings, journaux, base


@dataclass(frozen=True)
class Verification:
    id: str
    titre: str
    statut: Statut
    detail: str
    reparation: str | None = None  # réparation automatique proposée (bouton « Réparer »)
    aide: str | None = None  # commande ou lien à suivre sinon

    def en_dict(self) -> dict[str, Any]:
        return asdict(self)


def verifier_python() -> Verification:
    v = sys.version_info
    ok = (3, 12) <= (v.major, v.minor) < (3, 14)
    return Verification(
        "python",
        "Python",
        "ok" if ok else "erreur",
        f"Python {v.major}.{v.minor}.{v.micro}" + ("" if ok else " : versions prises en charge 3.12 et 3.13"),
        aide=None if ok else "Réinstallez avec le script d'installation (uv choisit le bon Python).",
    )


def verifier_donnees(dossier: Path) -> Verification:
    try:
        dossier.mkdir(parents=True, exist_ok=True)
        essai = dossier / f".essai-{uuid.uuid4().hex}"
        essai.write_text("ok", encoding="utf-8")
        essai.unlink()
    except OSError as exc:
        return Verification("donnees", "Dossier des données", "erreur", f"{dossier} : écriture impossible ({exc})")
    libre = shutil.disk_usage(dossier).free
    go = libre / 1024**3
    if libre < ESPACE_MINIMUM / 4:
        return Verification("donnees", "Dossier des données", "erreur", f"{dossier} : {go:.1f} Go libres seulement")
    statut: Statut = "ok" if libre >= ESPACE_MINIMUM else "attention"
    return Verification(
        "donnees",
        "Dossier des données",
        statut,
        f"{dossier} ({go:.0f} Go libres)",
        aide=None if statut == "ok" else "Libérez de la place ou déplacez les données (JARVIS2_DOSSIER_DONNEES).",
    )


async def verifier_stockage(p: Parametres, base: Executant | None) -> Verification:
    moteur = "SQLite" if p.stockage_effectif == "sqlite" else "PostgreSQL"
    ou = str(p.chemin_sqlite) if p.stockage_effectif == "sqlite" else f"{p.pg_hote}:{p.pg_port}/{p.postgres_db}"
    if base is None:
        return Verification("stockage", "Stockage", "erreur", f"{moteur} ({ou}) : inaccessible")
    try:
        actuelle = await version_schema(base)
    except ErreurBaseOuReseau as exc:
        if p.stockage_effectif == "sqlite":
            return Verification(
                "stockage", "Stockage", "attention", f"{moteur} ({ou}) : base à créer", reparation="migrer"
            )
        return Verification("stockage", "Stockage", "erreur", f"{moteur} ({ou}) : {type(exc).__name__}")
    derniere = lister_migrations(base.dialecte)[-1][0]
    if actuelle != derniere:
        return Verification(
            "stockage",
            "Stockage",
            "attention",
            f"{moteur} ({ou}) : schéma {actuelle or 'absent'}, {derniere} attendu",
            reparation="migrer" if p.stockage_effectif == "sqlite" else None,
            aide=None if p.stockage_effectif == "sqlite" else "jarvis2 migrer",
        )
    return Verification("stockage", "Stockage", "ok", f"{moteur} ({ou}), schéma {actuelle}")


def verifier_interface(dossier: Path) -> Verification:
    if (dossier / "index.html").is_file():
        return Verification("interface", "Interface", "ok", "interface compilée présente")
    return Verification(
        "interface",
        "Interface",
        "erreur",
        f"interface compilée absente ({dossier})",
        aide="Réinstallez JARVIS 2 ; en développement : cd interface ; npm run build",
    )


def modele_present(dossier: Path, nom_modele: str) -> bool:
    cle = nom_modele.rsplit("/", 1)[-1].lower()
    return dossier.is_dir() and any(cle in d.name.lower() for d in dossier.iterdir() if d.is_dir())


def _mo(octets: int) -> str:
    return f"{octets / 1_000_000:.0f} Mo" if octets >= 1_000_000 else f"{octets / 1000:.0f} ko"


def decrire_telechargement(e: telechargements.Etat) -> str:
    """Phrase d'état d'un téléchargement, lue sur ses marqueurs (aussi depuis un autre processus)."""
    if e.statut == "en_cours":
        part = f"{_mo(e.octets)} sur {_mo(e.total)} ({e.pourcentage} %)" if e.total else _mo(e.octets)
        essai = f", essai {e.essai}/{telechargements.ESSAIS}" if e.essai and e.essai > 1 else ""
        return f"téléchargement en cours : {part}{essai}"
    if e.statut == "interrompu":
        return f"téléchargement interrompu à {_mo(e.octets)} (reprise possible)"
    if e.statut == "echoue":
        return f"téléchargement échoué : {e.raison or 'raison inconnue'}"
    return "présent"


def _verifier_telechargeable(
    id_verif: str,
    titre: str,
    e: telechargements.Etat,
    ancien_cache: bool,
    reparation: str,
    a_telecharger: str,
    statut_absent: Statut,
) -> Verification:
    nom = e.nom.rsplit("/", 1)[-1]
    if e.statut == "pret" or (e.statut == "absent" and ancien_cache):
        return Verification(id_verif, titre, "ok", f"{nom} présent")
    if e.statut == "en_cours":
        return Verification(id_verif, titre, "info", f"{nom} : {decrire_telechargement(e)}")
    if e.statut in ("interrompu", "echoue"):
        return Verification(id_verif, titre, "attention", f"{nom} : {decrire_telechargement(e)}", reparation=reparation)
    return Verification(id_verif, titre, statut_absent, f"{nom} {a_telecharger}", reparation=reparation)


def verifier_modele(dossier: Path, nom_modele: str, chargement: str | None = None) -> Verification:
    titre = "Mémoire (modèle d'embeddings)"
    e = telechargements.lire_etat(telechargements.modele_embeddings(dossier, nom_modele))
    if chargement == "en_cours" and e.statut != "en_cours":
        return Verification("modele", titre, "info", f"{nom_modele.rsplit('/', 1)[-1]} : chargement…")
    return _verifier_telechargeable(
        "modele",
        titre,
        e,
        modele_present(dossier, nom_modele),
        "telecharger_modele",
        "à télécharger (environ 220 Mo, une seule fois ; rien ne part sans votre accord)",
        "attention",
    )


def verifier_voix(dossier: Path, nom_modele: str) -> Verification:
    """Modèle Whisper de la dictée : facultatif, proposé, jamais téléchargé sans accord."""
    e = telechargements.lire_etat(telechargements.modele_whisper(dossier, nom_modele))
    ancien = (dossier / "whisper").is_dir() and any(
        nom_modele.lower() in d.name.lower() for d in (dossier / "whisper").iterdir() if d.is_dir()
    )
    return _verifier_telechargeable(
        "voix",
        "Dictée (modèle Whisper)",
        e,
        ancien,
        "telecharger_voix",
        "à télécharger pour la dictée (facultatif ; rien ne part sans votre accord)",
        "info",
    )


async def verifier_cerveaux(connecteurs: Connecteurs | None) -> list[Verification]:
    if connecteurs is None:
        return []
    etats = await connecteurs.etats(tous=True)
    utilisables = [e for e in etats if e.utilisable]
    sorties = []
    if utilisables:
        noms = ", ".join(connecteurs.definitions[e.id].moteur.interne.nom for e in utilisables)
        sorties.append(Verification("cerveau", "Cerveau", "ok", f"Utilisable : {noms}"))
    else:
        sorties.append(
            Verification(
                "cerveau",
                "Cerveau",
                "erreur",
                "Aucun connecteur d'IA utilisable",
                aide="Page Connecteurs : connectez Claude Code, ajoutez une clé d'API ou lancez Ollama.",
            )
        )
    claude = next((e for e in etats if e.id == "claude_code"), None)
    if claude is not None and claude.sante.installe and connecteurs.conditions_a_accepter("claude_code"):
        sorties.append(
            Verification(
                "claude_code",
                "Claude Code",
                "attention",
                f"Installé ({claude.sante.detail}) : avertissement à lire et accepter avant le premier usage",
                aide="Page Connecteurs, carte Claude Code",
            )
        )
    elif claude is not None and not claude.sante.installe:
        sorties.append(
            Verification(
                "claude_code",
                "Claude Code",
                "info",
                "Non installé (facultatif : il permet d'utiliser votre abonnement Claude)",
                aide="https://code.claude.com",
            )
        )
    return sorties


def verifier_reseau(p: Parametres) -> Verification:
    if p.hote in ("127.0.0.1", "localhost", "::1"):
        return Verification("reseau", "Réseau", "ok", f"Le Core n'écoute que sur ce PC ({p.hote}:{p.port})")
    return Verification(
        "reseau",
        "Réseau",
        "attention",
        f"Le Core écoute sur {p.hote}:{p.port} (JARVIS2_OUVERTURE_RESEAU) : tout appareil du réseau peut le joindre",
        aide="Préférez Tailscale (tailscale serve) et JARVIS2_HOTE=127.0.0.1",
    )


def verifier_telephone(ts: EtatTailscale | None, port: int) -> Verification:
    titre = "Téléphone (accès à distance)"
    if ts is None or not ts.installe:
        return Verification(
            "telephone",
            titre,
            "info",
            "Tailscale non installé : le téléphone ne joint pas encore JARVIS",
            aide="https://tailscale.com/download",
        )
    if not ts.connecte:
        return Verification(
            "telephone", titre, "info", "Tailscale installé mais non connecté sur ce PC", aide="tailscale up"
        )
    if not ts.serve_actif:
        return Verification(
            "telephone",
            titre,
            "attention",
            f"Tailscale connecté ({ts.nom}) ; le Core n'est pas encore publié",
            aide=ts.commande_serve(port),
        )
    return Verification("telephone", titre, "ok", f"Joignable depuis vos appareils : {ts.adresse}")


def verifier_materiel() -> Verification:
    """Matériel détecté et modèles locaux conseillés (une seule table : `materiel.TABLE`). Rien n'est installé."""
    from . import materiel

    m = materiel.detecter()
    conseils = [
        f"{c['titre']} : {c['conseille']['modele']}" for c in materiel.conseiller(m) if c["conseille"] is not None
    ]
    detail = materiel.resume(m) + (" — conseillé : " + " ; ".join(conseils) if conseils else "")
    return Verification(
        "materiel",
        "Matériel et modèles locaux",
        "info",
        detail,
        aide="Les modèles Ollama se téléchargent à la main (ollama pull <modèle>) ; JARVIS n'installe rien.",
    )


async def verifier_audit(base: Executant | None) -> Verification | None:
    if base is None:
        return None
    try:
        rompue = await audit.verifier(base)
    except ErreurBaseOuReseau:
        return None
    if rompue is None:
        return Verification("audit", "Journal d'audit", "ok", "chaîne d'empreintes intacte")
    return Verification("audit", "Journal d'audit", "erreur", f"altération détectée à l'entrée {rompue}")


def verifier_ecran(sans_ecran: bool, graphique: bool | None = None) -> Verification:
    """Mode sans écran (serveur domestique) : dit si le contrôle de l'écran est coupé, ou s'il devrait l'être."""
    from .ecran import session_graphique

    if sans_ecran:
        return Verification(
            "ecran",
            "Écran",
            "info",
            "Mode sans écran : capture, clics et contrôle de l'écran désactivés ; voix par le micro du navigateur",
        )
    if graphique is None:
        graphique = session_graphique()
    if graphique:
        return Verification("ecran", "Écran", "ok", "Session graphique disponible : fonctions d'écran actives")
    return Verification(
        "ecran",
        "Écran",
        "attention",
        "Aucune session graphique détectée (ni DISPLAY ni WAYLAND_DISPLAY) : les fonctions d'écran échoueraient",
        aide="jarvis2 serveur --sans-ecran (ou JARVIS2_SANS_ECRAN=true)",
    )


async def diagnostiquer(
    p: Parametres,
    base: Executant | None,
    connecteurs: Connecteurs | None = None,
    tailscale: EtatTailscale | None = None,
    chargement_modele: str | None = None,
    urgence_active: bool = False,
    sans_ecran: bool | None = None,
) -> list[Verification]:
    stockage, cerveaux, journal_audit, materiel = await asyncio.gather(
        verifier_stockage(p, base),
        verifier_cerveaux(connecteurs),
        verifier_audit(base),
        asyncio.to_thread(verifier_materiel),
    )
    resultats: list[Verification] = [
        verifier_python(),
        verifier_donnees(p.dossier_donnees),
        stockage,
        verifier_interface(p.dossier_interface),
        verifier_modele(p.dossier_modeles, p.modele_embeddings, chargement_modele),
        verifier_voix(p.dossier_modeles, p.modele_voix),
        *cerveaux,
        materiel,
        verifier_reseau(p),
        verifier_telephone(tailscale, p.port),
        verifier_ecran(p.sans_ecran if sans_ecran is None else sans_ecran),
    ]
    if journal_audit is not None:
        resultats.append(journal_audit)
    if urgence_active:
        resultats.append(Verification("urgence", "Arrêt d'urgence", "attention", "Actif : les écritures sont refusées"))
    return resultats


def texte(verifications: Sequence[Verification]) -> str:
    symboles = {"ok": "✔", "info": "·", "attention": "!", "erreur": "✖"}
    lignes = []
    for v in verifications:
        lignes.append(f" {symboles[v.statut]} {v.titre} : {v.detail}")
        if v.reparation:
            lignes.append(
                "     réparable automatiquement : jarvis2 docteur --reparer (ou « Réparer » dans l'interface)"
            )
        if v.aide:
            lignes.append(f"     → {v.aide}")
    return "\n".join(lignes)
