"""Core de démonstration : base SQLite d'essai, jeu de données inventé, captures de la vitrine du dépôt.

Tout vit dans un dossier JETABLE (défaut : `<dossier temporaire>/jarvis2-demo`), jamais dans les données réelles :
le Core d'essai ne lit ni la configuration locale de l'utilisateur, ni `.env`, ni son coffre, ni ses moteurs.

Depuis `core/` (venv du Core) :

    uv run python ../scripts/demo.py preparer   # (re)crée la base d'essai et son accès
    uv run python ../scripts/demo.py serveur    # Core d'essai sur http://127.0.0.1:8811 (Ctrl+C pour l'arrêter)
    uv run python ../scripts/demo.py captures   # captures PNG + GIF dans docs/images (Core d'essai lancé, Edge
                                                # ou Chrome installé, Node ≥ 22, interface compilée)

Options : `--dossier <chemin>` (ou JARVIS2_DEMO_DOSSIER), `--port <n>` (défaut 8811, jamais 8765).
Aucun moteur n'est nécessaire : les réponses de JARVIS sont écrites directement dans la base.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
MARQUEUR = ".jarvis2-demo"  # un dossier sans ce marqueur n'est jamais vidé
FICHIER_ACCES = "acces-demo.txt"
PORT_REEL = 8765


# --- Jeu de données (inventé, neutre) ---------------------------------------------------------------------------

CONVERSATIONS: list[dict[str, Any]] = [
    {
        "titre": "Planifier un potager de printemps",
        "epinglee": True,
        "il_y_a": timedelta(minutes=12),
        "messages": [
            (
                "utilisateur",
                "J'ai une parcelle de 12 m² en plein soleil. Aide-moi à planifier un potager de printemps.",
            ),
            (
                "jarvis",
                "Voici un plan simple pour **12 m²** en plein soleil, découpé en quatre carrés de 3 m² :\n\n"
                "1. **Carré racines** : carottes, radis, betteraves (semis direct dès mi-mars).\n"
                "2. **Carré feuilles** : laitues, épinards, roquette, en lignes espacées de 25 cm.\n"
                "3. **Carré fruits** : tomates et courgettes, à planter après les dernières gelées.\n"
                "4. **Carré aromates** : basilic, persil, ciboulette, en bordure pour attirer les pollinisateurs.\n\n"
                "Pensez à la **rotation** : l'an prochain, chaque famille avance d'un carré. "
                "Voulez-vous un calendrier de semis semaine par semaine ?",
            ),
            ("utilisateur", "Oui, et rappelle-moi d'arroser les semis les soirs de grande chaleur."),
            (
                "jarvis",
                "Calendrier proposé :\n\n"
                "- **Semaine 11** : radis et épinards sous voile.\n"
                "- **Semaine 13** : carottes et laitues.\n"
                "- **Semaine 16** : betteraves, aromates en godets.\n"
                "- **Semaine 19** : tomates et courgettes en pleine terre.\n\n"
                "J'ai noté le rappel d'arrosage : il s'affichera les soirs où la température dépasse 28 °C.",
            ),
        ],
    },
    {
        "titre": "Résumé : l'essor de l'éolien en mer",
        "il_y_a": timedelta(hours=3),
        "messages": [
            ("utilisateur", "Résume-moi l'article sur l'éolien en mer que je t'ai confié ce matin, en cinq points."),
            (
                "jarvis",
                "En cinq points :\n\n"
                "1. Les parcs **posés** dominent encore ; les éoliennes **flottantes** ouvrent les eaux profondes.\n"
                "2. Les turbines dépassent désormais **15 MW** chacune, ce qui réduit le nombre de fondations.\n"
                "3. Le raccordement au réseau reste le premier poste de délai.\n"
                "4. La cohabitation avec la pêche se négocie zone par zone.\n"
                "5. Le recyclage des pales devient une exigence des appels d'offres.\n\n"
                "Source : l'article fourni, rangé en mémoire avec l'étiquette *énergie*.",
            ),
        ],
    },
    {
        "titre": "Pain au levain : horaires de la recette",
        "il_y_a": timedelta(days=1, hours=2),
        "messages": [
            ("utilisateur", "Je veux un pain au levain prêt pour samedi midi. Quand dois-je commencer ?"),
            (
                "jarvis",
                "Commencez **vendredi à 18 h** : rafraîchi du levain, autolyse à 21 h, pétrissage et pointage "
                "jusqu'à 23 h, puis apprêt au froid toute la nuit. Cuisson samedi à 10 h, 45 minutes à 240 °C.",
            ),
        ],
    },
    {
        "titre": "Préparer une randonnée de deux jours",
        "il_y_a": timedelta(days=2, hours=5),
        "messages": [
            ("utilisateur", "Liste de matériel pour une randonnée de deux jours avec une nuit en refuge."),
            (
                "jarvis",
                "L'essentiel : sac de 30 L, sac à viande, lampe frontale, veste imperméable, polaire, "
                "deux litres d'eau, en-cas salés, trousse de secours, carte et boussole. "
                "Le refuge fournit couvertures et repas du soir : vérifiez la réservation la veille.",
            ),
        ],
    },
    {
        "titre": "Idées de lectures pour l'été",
        "il_y_a": timedelta(days=4),
        "messages": [
            ("utilisateur", "Propose-moi trois genres de lectures pour l'été, sans titres précis."),
            (
                "jarvis",
                "Un récit de voyage à pied, un roman d'aventure maritime et un essai de vulgarisation "
                "sur l'astronomie : trois rythmes différents pour alterner selon l'humeur.",
            ),
        ],
    },
    {
        "titre": "Organiser le club de lecture du quartier",
        "il_y_a": timedelta(days=6),
        "messages": [
            ("utilisateur", "Comment organiser la première séance d'un club de lecture ?"),
            (
                "jarvis",
                "Choisissez un lieu calme, un livre court pour commencer, et trois questions ouvertes pour lancer "
                "la discussion. Une heure et demie suffit ; fixez la date suivante avant de vous quitter.",
            ),
        ],
    },
]

SOUVENIRS: list[dict[str, Any]] = [
    {
        "contenu": "Le potager fait 12 m², en plein soleil, découpé en quatre carrés de 3 m².",
        "type": "fait",
        "tags": ["potager", "jardin"],
        "origine": "conversation",
        "importance": 0.8,
        "il_y_a": timedelta(minutes=10),
    },
    {
        "contenu": "Rotation des cultures : chaque famille de légumes avance d'un carré chaque année.",
        "type": "decision",
        "tags": ["potager"],
        "origine": "conversation",
        "importance": 0.7,
        "il_y_a": timedelta(minutes=9),
    },
    {
        "contenu": "Les éoliennes flottantes ouvrent les eaux profondes à l'éolien en mer ; le raccordement reste "
        "le premier poste de délai.",
        "type": "fait",
        "tags": ["énergie", "éolien"],
        "origine": "conversation",
        "importance": 0.6,
        "il_y_a": timedelta(hours=3),
    },
    {
        "contenu": "Projet : installer un récupérateur d'eau de pluie de 300 L pour arroser le potager.",
        "type": "projet",
        "tags": ["potager", "eau"],
        "origine": "utilisateur",
        "importance": 0.7,
        "il_y_a": timedelta(days=1),
    },
    {
        "contenu": "Idée : un carnet de semis partagé avec le club de lecture, sous forme de fiches.",
        "type": "idee",
        "tags": ["jardin", "club"],
        "origine": "utilisateur",
        "importance": 0.4,
        "il_y_a": timedelta(days=2),
    },
    {
        "contenu": "Pain au levain : cuisson 45 minutes à 240 °C, apprêt au froid toute la nuit.",
        "type": "note",
        "tags": ["cuisine"],
        "origine": "conversation",
        "importance": 0.5,
        "il_y_a": timedelta(days=1, hours=2),
    },
    {
        "contenu": "Préférence : des réponses courtes, en listes, avec les chiffres en gras.",
        "type": "decision",
        "tags": ["préférences"],
        "origine": "profil",
        "importance": 0.9,
        "il_y_a": timedelta(days=5),
    },
    {
        "contenu": "Le club de lecture se réunit le premier jeudi du mois, une heure et demie.",
        "type": "fait",
        "tags": ["club"],
        "origine": "conversation",
        "importance": 0.5,
        "il_y_a": timedelta(days=6),
    },
]

RAPPORT_TOMATES = (
    "## Variétés de tomates anciennes pour un petit potager\n\n"
    "- **Cœur de bœuf** : gros fruits charnus, tuteurage solide indispensable.\n"
    "- **Noire de Crimée** : saveur douce, supporte bien la chaleur.\n"
    "- **Poire jaune** : petits fruits, très productive, idéale en bordure.\n\n"
    "Conseil : deux pieds de chaque suffisent pour un carré de 3 m²."
)
RAPPORT_STOCKAGE = (
    "## Stockage de l'énergie à la maison : état des lieux\n\n"
    "1. Batteries domestiques : coût en baisse, durée de vie d'une dizaine d'années.\n"
    "2. Ballon d'eau chaude piloté : le stockage le moins cher, souvent oublié.\n"
    "3. Recharge pilotée du véhicule : utile si l'on produit en journée."
)

MISSIONS: list[dict[str, Any]] = [
    {
        "type": "recherche",
        "objectif": "Comparer trois variétés de tomates anciennes adaptées à un petit potager",
        "statut": "terminee",
        "rapport": RAPPORT_TOMATES,
        "etapes": ["plan", "recherche (3 requêtes : web)", "rapport (6 sources)", "rangé en mémoire"],
        "il_y_a": timedelta(hours=1),
    },
    {
        "type": "brainstorm",
        "objectif": "Dix idées d'animations pour le club de lecture",
        "statut": "terminee",
        "rapport": "## Idées\n\n1. Lecture à voix haute d'un extrait choisi.\n2. Échange de livres.\n"
        "3. Une séance en plein air au printemps.",
        "etapes": ["brainstorm", "rangé en mémoire"],
        "il_y_a": timedelta(days=1, hours=4),
    },
    {
        "type": "recherche",
        "objectif": "Faire le point sur le stockage de l'énergie à la maison",
        "statut": "terminee",
        "rapport": RAPPORT_STOCKAGE,
        "etapes": ["plan", "recherche (4 requêtes : web)", "rapport (8 sources)", "rangé en mémoire"],
        "il_y_a": timedelta(days=3),
    },
]

CHANTIERS: list[dict[str, Any]] = [
    {
        "titre": "Installer le récupérateur d'eau de pluie",
        "description": "Choisir la cuve, le collecteur de gouttière et l'emplacement près du potager.",
        "categorie": "maison",
        "statut": "en_cours",
        "progression": 40,
        "etapes": [("Mesurer la gouttière", True), ("Choisir une cuve de 300 L", True), ("Poser le collecteur", False)],
        "responsable": "utilisateur",
        "origine": "utilisateur",
        "priorite": 1,
    },
    {
        "titre": "Calendrier de semis du printemps",
        "description": "Calendrier semaine par semaine, avec rappels d'arrosage.",
        "categorie": "jardin",
        "statut": "en_attente_utilisateur",
        "progression": 75,
        "etapes": [("Lister les cultures", True), ("Placer les semis", True), ("Valider les rappels", False)],
        "responsable": "jarvis",
        "origine": "jarvis",
        "priorite": 2,
        "action_utilisateur": "Valider les rappels d'arrosage proposés.",
    },
    {
        "titre": "Préparer la séance de juin du club de lecture",
        "description": "Choisir le livre et préparer trois questions ouvertes.",
        "categorie": "loisirs",
        "statut": "a_faire",
        "progression": 0,
        "etapes": [("Choisir le livre", False), ("Écrire les questions", False)],
        "responsable": "utilisateur",
        "origine": "utilisateur",
        "priorite": 3,
    },
]


def sources_inventees(mission: dict[str, Any]) -> list[dict[str, str]]:
    """Sources fictives (domaine réservé example.org) : la carte d'une mission de recherche montre leur nombre."""
    if mission["type"] != "recherche":
        return []
    return [
        {"titre": f"Fiche {i} : {mission['objectif'].lower()}", "url": f"https://example.org/demo/{i}", "extrait": "…"}
        for i in range(1, 4)
    ]


# --- Dossier jetable et environnement isolé ----------------------------------------------------------------------


def dossier_defaut() -> Path:
    return Path(os.environ.get("JARVIS2_DEMO_DOSSIER") or Path(tempfile.gettempdir()) / "jarvis2-demo")


def environnement_isole(dossier: Path, port: int) -> dict[str, str]:
    """Environnement MINIMAL du Core d'essai : rien de l'utilisateur (ni clés d'API, ni configuration, ni coffre,
    ni dossier personnel, ni programmes de son PATH comme les CLI des moteurs)."""
    if port == PORT_REEL:
        raise SystemExit(f"Port {PORT_REEL} réservé au Core réel : choisissez un autre port.")
    maison = dossier / "maison"
    systeme = os.environ.get("SYSTEMROOT", r"C:\Windows")
    chemins = [str(Path(sys.executable).parent)]
    if sys.platform == "win32":
        chemins += [rf"{systeme}\System32", systeme, rf"{systeme}\System32\Wbem"]
    else:
        chemins += ["/usr/bin", "/bin"]
    env = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "OS") if k in os.environ}
    env |= {
        "PATH": os.pathsep.join(chemins),
        "HOME": str(maison),
        "USERPROFILE": str(maison),
        "APPDATA": str(maison / "AppData" / "Roaming"),
        "LOCALAPPDATA": str(maison / "AppData" / "Local"),
        "XDG_CONFIG_HOME": str(maison / ".config"),
        "XDG_DATA_HOME": str(maison / ".local" / "share"),
        "TEMP": str(dossier / "temp"),
        "TMP": str(dossier / "temp"),
        "CLAUDE_CONFIG_DIR": str(maison / ".claude"),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "JARVIS2_CONFIG": str(dossier / "config" / "config.toml"),  # absent : configuration vide
        "JARVIS2_DOSSIER_DONNEES": str(dossier / "donnees"),
        "JARVIS2_STOCKAGE": "sqlite",
        "JARVIS2_SQLITE": str(dossier / "donnees" / "jarvis2.db"),
        "JARVIS2_HOTE": "127.0.0.1",
        "JARVIS2_PORT": str(port),
        "JARVIS2_OLLAMA_URL": "http://127.0.0.1:9",  # port fermé : aucun Ollama réel n'est interrogé
        "JARVIS2_CLAUDE_COMMANDE": str(dossier / "absent" / "claude"),
        "JARVIS2_NIVEAU_JOURNAL": "WARNING",
    }
    for d in (maison / "AppData" / "Roaming", maison / "AppData" / "Local", dossier / "temp", dossier / "config"):
        d.mkdir(parents=True, exist_ok=True)
    return env


def appliquer_isolement(dossier: Path, port: int) -> None:
    """Dans ce processus : environnement isolé, et `.env` du dépôt ignoré (`Parametres` ne lit plus de fichier)."""
    os.environ.clear()
    os.environ.update(environnement_isole(dossier, port))
    from jarvis2.config import Parametres

    Parametres.model_config["env_file"] = None


def vider(dossier: Path) -> None:
    if dossier.exists():
        if not (dossier / MARQUEUR).is_file():
            raise SystemExit(f"{dossier} existe sans marqueur {MARQUEUR} : dossier refusé (rien n'a été supprimé).")
        shutil.rmtree(dossier)
    dossier.mkdir(parents=True)
    (dossier / MARQUEUR).write_text("Dossier jetable du Core de démonstration de JARVIS 2.\n", encoding="utf-8")


# --- Remplissage --------------------------------------------------------------------------------------------------


async def remplir(dossier: Path) -> str:
    from jarvis2.config import parametres
    from jarvis2.db_sqlite import BaseSQLite, appliquer_migrations
    from jarvis2.securite import appareils

    chemin = parametres().chemin_sqlite
    chemin.parent.mkdir(parents=True, exist_ok=True)
    await appliquer_migrations(chemin)
    base = await BaseSQLite.ouvrir(chemin)
    maintenant = datetime.now(UTC)
    try:
        for conv in CONVERSATIONS:
            debut = maintenant - conv["il_y_a"]
            ident = await base.fetchval(
                "INSERT INTO conversations (titre, titre_source, epinglee, cree_le, maj_le, connecteur, modele)"
                " VALUES ($1, 'auto', $2, $3, $4, 'ollama', 'demo-local') RETURNING id",
                conv["titre"],
                conv.get("epinglee", False),
                debut - timedelta(minutes=2 * len(conv["messages"])),
                debut,
            )
            for i, (role, contenu) in enumerate(conv["messages"]):
                quand = debut - timedelta(minutes=2 * (len(conv["messages"]) - i))
                meta: dict[str, Any] = {}
                if role == "jarvis":
                    meta = {"moteur": "ollama", "modele": "demo-local", "cout_usd": 0, "duree_ms": 1800 + 140 * i}
                await base.execute(
                    "INSERT INTO messages (conversation_id, role, contenu, horodatage, meta)"
                    " VALUES ($1, $2, $3, $4, $5)",
                    ident,
                    role,
                    contenu,
                    quand,
                    meta,
                )
        for s in SOUVENIRS:
            quand = maintenant - s["il_y_a"]
            await base.execute(
                "INSERT INTO memoires (contenu, type, tags, source, origine, importance, cree_le, maj_le, observed_at)"
                " VALUES ($1, $2, $3, 'demo', $4, $5, $6, $6, $6)",
                s["contenu"],
                s["type"],
                s["tags"],
                s["origine"],
                s["importance"],
                quand,
            )
        for m in MISSIONS:
            fin = maintenant - m["il_y_a"]
            debut = fin - timedelta(minutes=4)
            etapes = [
                {"nom": nom, "le": (debut + timedelta(minutes=i)).isoformat()} for i, nom in enumerate(m["etapes"])
            ]
            await base.execute(
                "INSERT INTO missions (type, objectif, statut, progression, etapes, resultat, acteur, cree_le,"
                " demarre_le, termine_le) VALUES ($1, $2, $3, 100, $4, $5, 'appareil:Démonstration', $6, $6, $7)",
                m["type"],
                m["objectif"],
                m["statut"],
                etapes,
                {"rapport": m["rapport"], "sources": sources_inventees(m), "souvenir_id": None, "moteur": "ollama"},
                debut,
                fin,
            )
        for c in CHANTIERS:
            etapes = [{"titre": t, "fait": f} for t, f in c["etapes"]]
            courante = next((t for t, f in c["etapes"] if not f), None)
            await base.execute(
                "INSERT INTO chantiers (titre, description, categorie, statut, progression, etape_courante, etapes,"
                " responsable, action_utilisateur, priorite, cree_par, origine)"
                " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'demo', $11)",
                c["titre"],
                c["description"],
                c["categorie"],
                c["statut"],
                c["progression"],
                courante,
                etapes,
                c["responsable"],
                c.get("action_utilisateur"),
                c["priorite"],
                c["origine"],
            )
        # Assistant de premier lancement déjà terminé ; mémoire « déjà vue » (pas de notification au chargement)
        await base.execute(
            "UPDATE etat_systeme SET valeur = $1 WHERE cle = 'accueil'", {"termine": True, "par": "demo"}
        )
        _, acces = await appareils.creer(base, "Navigateur de démonstration", "navigateur")
    finally:
        await base.close()
    return acces


# --- Commandes ----------------------------------------------------------------------------------------------------


def preparer(dossier: Path, port: int) -> None:
    vider(dossier)
    appliquer_isolement(dossier, port)
    acces = asyncio.run(remplir(dossier))
    (dossier / FICHIER_ACCES).write_text(acces + "\n", encoding="utf-8")
    print(f"Base d'essai prête : {dossier}")


def serveur(dossier: Path, port: int) -> int:
    if not (dossier / MARQUEUR).is_file():
        raise SystemExit(f"Base d'essai absente : lancez d'abord « demo.py preparer --dossier {dossier} ».")
    # Sous-processus à l'environnement minimal : même les variables héritées par ses enfants sont isolées.
    env = environnement_isole(dossier, port)
    commande = [sys.executable, str(Path(__file__).resolve()), "_core", "--dossier", str(dossier), "--port", str(port)]
    print(f"Core d'essai : http://127.0.0.1:{port}  (Ctrl+C pour l'arrêter)")
    try:
        return subprocess.call(commande, env=env, cwd=dossier)
    except KeyboardInterrupt:
        return 0


def core_interne(dossier: Path, port: int) -> int:
    appliquer_isolement(dossier, port)
    from jarvis2.__main__ import main

    return main(["serveur"])


def captures(dossier: Path, port: int, sortie: Path) -> int:
    """Captures brutes par le navigateur (scripts/captures-demo.mjs), puis optimisées ici (Pillow)."""
    from PIL import Image

    acces = (dossier / FICHIER_ACCES).read_text(encoding="utf-8").strip()
    brut = dossier / "captures"
    shutil.rmtree(brut, ignore_errors=True)
    brut.mkdir(parents=True)
    node = shutil.which("node")
    if node is None:
        raise SystemExit("Node.js (≥ 22) introuvable : il pilote le navigateur des captures.")
    env = {**os.environ, "JARVIS2_DEMO_ACCES": acces}
    script = RACINE / "scripts" / "captures-demo.mjs"
    code = subprocess.call([node, str(script), f"http://127.0.0.1:{port}", str(brut)], env=env)
    if code:
        return code
    sortie.mkdir(parents=True, exist_ok=True)
    for png in sorted(brut.glob("*.png")):
        if png.stem.startswith("gif-"):
            continue
        cible = sortie / png.name
        optimiser_png(Image.open(png), cible)
        print(f"{cible.name} : {cible.stat().st_size // 1024} Ko")
    images = [Image.open(p) for p in sorted(brut.glob("gif-*.png"))]
    if images:
        gif = sortie / "demo.gif"
        ecrire_gif(images, gif)
        print(f"{gif.name} : {gif.stat().st_size // 1024} Ko ({len(images)} images)")
    return 0


def optimiser_png(image: Any, cible: Path, limite: int = 480 * 1024) -> None:
    """PNG en couleurs vraies s'il tient sous la limite, sinon palette de 256 couleurs (tramage)."""
    from PIL import Image

    rgb = image.convert("RGB")
    rgb.save(cible, optimize=True)
    if cible.stat().st_size > limite:
        rgb.quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG).save(
            cible, optimize=True
        )


def ecrire_gif(images: list[Any], cible: Path, largeur: int = 640, duree_ms: int = 1600) -> None:
    from PIL import Image

    cadres = []
    for im in images:
        rgb = im.convert("RGB")
        rgb = rgb.resize((largeur, round(rgb.height * largeur / rgb.width)), Image.Resampling.LANCZOS)
        cadres.append(rgb.quantize(64, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE))
    cadres[0].save(cible, save_all=True, append_images=cadres[1:], duration=duree_ms, loop=0, optimize=True)


def main() -> int:
    analyseur = argparse.ArgumentParser(description="Core de démonstration de JARVIS 2 (données inventées)")
    analyseur.add_argument("commande", choices=["preparer", "serveur", "captures", "_core"])
    analyseur.add_argument("--dossier", type=Path, default=dossier_defaut(), help="dossier jetable de la démo")
    analyseur.add_argument("--port", type=int, default=8811, help="port du Core d'essai (défaut 8811)")
    analyseur.add_argument("--sortie", type=Path, default=RACINE / "docs" / "images", help="dossier des captures")
    args = analyseur.parse_args()
    dossier = args.dossier.resolve()
    if args.commande == "preparer":
        preparer(dossier, args.port)
        return 0
    if args.commande == "serveur":
        return serveur(dossier, args.port)
    if args.commande == "captures":
        return captures(dossier, args.port, args.sortie)
    return core_interne(dossier, args.port)


if __name__ == "__main__":
    sys.exit(main())
