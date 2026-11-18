# Contribuer à JARVIS 2

Merci de votre intérêt ! Le projet est en développement actif ; le [plan](docs/PLAN.md) dit ce qui vient et dans quel ordre, les [décisions](docs/DECISIONS.md) expliquent pourquoi le code est ainsi.

## Langue

Le projet est **en français** : documentation, commentaires, messages de commit, textes de l'interface. Les identifiants de code peuvent rester en anglais.

## Préparer l'environnement

Prérequis : [uv](https://docs.astral.sh/uv/), Node 22+. Docker seulement pour les tests PostgreSQL.

```sh
cd core && uv sync
cd interface && npm install
docker compose up -d        # facultatif : PostgreSQL pour les tests sur les deux stockages (voir .env.example)
```

## Avant d'ouvrir une demande de fusion

```sh
cd core && uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy
cd interface && npm run verifier && npm run build
```

- Les tests de base tournent sur SQLite **et** sur PostgreSQL (ignorés si Docker est arrêté ; la CI lance les deux).
- Interface : jetons de [interface/DESIGN.md](interface/DESIGN.md), jamais de valeur « magique » ni d'`innerHTML` avec des données ; vérifiée à 375, 1280 et 1920 px, console vide.
- Une modification du schéma = deux migrations jumelles (`core/jarvis2/migrations/` et `migrations/sqlite/`, même nom).
- Petits incréments, commits courts et explicites.

## Règles non négociables

- **Rien de personnel ni de secret dans git** : ni `.env`, ni `config.toml`, ni clé, jeton, mot de passe, chemin ou nom propre à une personne. Tout ce qui est propre à un utilisateur vit dans sa configuration locale.
- **Jamais de contournement** des conditions d'un fournisseur d'IA : JARVIS appelle les programmes officiels, connectés par l'utilisateur, et ne touche jamais à leurs identifiants.
- **Rien d'irréversible ou d'externe sans validation humaine** (niveaux 🟢 🟡 🔴).
- Idées empruntées à d'autres projets : idées et formats ouverts uniquement, jamais de code sous licence incompatible.

## Licence

En contribuant, vous acceptez que votre contribution soit distribuée sous la licence [Apache 2.0](LICENSE) du projet.
