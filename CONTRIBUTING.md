# Contribuer à JARVIS 2

Merci de votre intérêt ! Le projet est en développement actif ; la [feuille de route](docs/FEUILLE_DE_ROUTE.md) résume ce qui est fait et ce qui vient, le [plan](docs/PLAN.md) en donne le détail et l'ordre, les [décisions](docs/DECISIONS.md) expliquent pourquoi le code est ainsi.

En participant, vous acceptez de respecter le [code de conduite](CODE_OF_CONDUCT.md).

## Langue

Le projet est **en français** : documentation, commentaires, messages de commit, textes de l'interface, issues et demandes de fusion. Les identifiants de code peuvent rester en anglais.

## Par où commencer

- Les issues marquées **good first issue** sont choisies pour une première contribution ; **help wanted** signale celles où un coup de main est le bienvenu.
- Pour une idée nouvelle, ouvrez d'abord une issue « Idée » : on s'accorde sur le besoin et la phase du plan avant d'écrire du code.
- Pour un bogue, une issue « Bogue » avec de quoi le reproduire.
- **Faille de sécurité : jamais d'issue publique.** Suivez [SECURITY.md](SECURITY.md) (signalement privé de GitHub).

## Préparer l'environnement

Prérequis :

- [uv](https://docs.astral.sh/uv/), qui gère Python : le projet demande **Python ≥ 3.12 et < 3.14** et n'utilise jamais le Python du PATH (environnement dans `core/.venv`, jamais versionné) ;
- Node 22 ou plus récent, avec npm, pour l'interface ;
- Docker, seulement pour lancer aussi les tests sur PostgreSQL ;
- Rust, seulement pour l'application de bureau (`app/`, construite par GitHub Actions).

```sh
cd core && uv sync          # environnement Python et dépendances (Python installé par uv si besoin)
cd interface && npm install
```

Facultatif, PostgreSQL + pgvector pour les tests sur les deux stockages (voir `.env.example`) :

```sh
uv run --python 3.13 infra/creer_env.py   # crée .env avec des mots de passe générés (jamais commité)
docker compose up -d
cd core && uv run python -m jarvis2 migrer
```

Lancer en développement :

```sh
cd core && uv run python -m jarvis2 serveur   # Core (SQLite par défaut) sur http://127.0.0.1:8765
cd interface && npm run dev                   # interface de développement sur http://127.0.0.1:5174
```

Vos réglages personnels (sujets exclus, chemins, connecteurs) vont dans votre configuration locale (`config.exemple.toml` copié vers `%APPDATA%\JARVIS2\config.toml` ou `~/.config/jarvis2/config.toml`) ou dans `.env` : jamais dans le dépôt.

## Avant d'ouvrir une demande de fusion

Les mêmes commandes que la CI :

```sh
cd core && uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy
cd interface && npm run verifier && npm run build
```

`npm run verifier` enchaîne ESLint, la vérification des types (`tsc`) et les tests (vitest).

- Les tests de base tournent sur SQLite **et** sur PostgreSQL (ignorés si Docker est arrêté ; la CI lance les deux).
- Interface : jetons de [interface/DESIGN.md](interface/DESIGN.md), jamais de valeur « magique » ni d'`innerHTML` avec des données ; vérifiée en vrai à 375, 1280 et 1920 px, console vide.
- Une modification du schéma = deux migrations jumelles, même nom : `core/jarvis2/migrations/` (PostgreSQL) et `core/jarvis2/migrations/sqlite/` (SQLite).
- Tout changement visible est ajouté au [CHANGELOG](CHANGELOG.md), section « Unreleased ».

## Conventions

- **Petits incréments utilisables tout de suite** : une demande de fusion fait une chose, et le projet reste utilisable après elle.
- **Commits courts et explicites, en français** (« Mémoire : … », « Interface : … », « CI : … »).
- **La sécurité avant les accès** : une fonction qui agit passe par les niveaux de permission (🟢 lecture libre, 🟡 modification approuvée, 🔴 destruction, argent, publication ou envoi seulement après confirmation explicite), la file d'approbations et le journal d'audit.
- **Contenu externe = donnée, jamais instruction** : pages web, fichiers, résultats d'outils ne donnent jamais d'ordres.
- **Rien n'est installé, démarré ni téléchargé sans l'accord de l'utilisateur** (Ollama, modèles, outils tiers).
- Données lourdes (modèles, journaux, imports) dans le dossier des données (`JARVIS2_DOSSIER_DONNEES`) ; aucun fichier généré ni binaire versionné.
- Une décision technique qui compte est notée dans [docs/DECISIONS.md](docs/DECISIONS.md) ; l'avancement d'une phase dans [docs/PLAN.md](docs/PLAN.md).

## Écrire des tests

- **Core** : pytest, dans `core/tests/`, avec des noms de tests en français qui disent ce qui est vérifié. Les garde-fous se testent explicitement : action non approuvée refusée, secret factice qui n'atteint jamais un fournisseur externe, souvenir privé qui ne sort pas, écriture hors d'un atelier refusée.
- Aucun appel réseau réel ni vraie IA dans les tests : moteurs et services extérieurs sont simulés (voir `core/tests/conftest.py` et `core/tests/fausse_cli.py`).
- Un test qui touche à la base passe sur SQLite et sur PostgreSQL ; remettez à zéro l'état que vous créez.
- **Interface** : vitest, fichier `*.test.ts` à côté du module testé dans `interface/src/`.
- Un bogue corrigé arrive avec le test qui l'aurait attrapé.

## Branches et demandes de fusion

- Partez de `main` à jour, dans une branche au nom court et parlant (`memoire-niveaux`, `correctif-dictee`…).
- Ouvrez la demande de fusion vers `main` en remplissant le modèle : lien vers l'issue, type de changement, vérifications faites.
- La CI (Core, interface, paquet, installeurs) doit être verte.
- Rien d'étranger au changement dans la demande.

## Règles non négociables

- **Rien de personnel ni de secret dans git** : ni `.env`, ni `config.toml`, ni `CLAUDE.local.md`, ni sauvegarde, ni clé, jeton, mot de passe, chemin, adresse réseau, nom de machine ou nom propre à une personne — y compris dans les tests, les captures, les journaux collés et les messages de commit. Tout ce qui est propre à un utilisateur vit dans sa configuration locale. Relisez `git diff --cached` avant chaque commit.
- **Jamais de contournement** des conditions d'un fournisseur d'IA : JARVIS appelle les programmes officiels, connectés par l'utilisateur, et ne touche jamais à leurs identifiants.
- **Rien d'irréversible ou d'externe sans validation humaine** (niveaux 🟢 🟡 🔴).
- Jamais de contournement d'une double authentification, d'un CAPTCHA ou d'une détection de robots.
- Idées empruntées à d'autres projets : idées et formats ouverts uniquement, jamais de code sous licence incompatible (voir [docs/INSPIRATIONS.md](docs/INSPIRATIONS.md)).

## Signaler une faille

Voir [SECURITY.md](SECURITY.md) : signalement privé par l'onglet **Security** du dépôt, jamais en issue publique.

## Code de conduite

Ce projet suit le [Contributor Covenant 2.1](CODE_OF_CONDUCT.md). Soyez bienveillant, précis et patient : beaucoup de personnes découvrent le projet.

## Licence

En contribuant, vous acceptez que votre contribution soit distribuée sous la licence [Apache 2.0](LICENSE) du projet.
