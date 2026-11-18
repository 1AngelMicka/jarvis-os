# JARVIS 2

Assistant personnel local d'abord : mémoire à long terme, conversation en flux avec le modèle de votre choix (Claude Code avec votre propre abonnement, modèles locaux via Ollama), interface HUD.

Plan : [docs/PLAN.md](docs/PLAN.md) · décisions : [docs/DECISIONS.md](docs/DECISIONS.md) · design : [interface/DESIGN.md](interface/DESIGN.md).

> Projet en construction. L'installation simplifiée (sans Docker ni Node) arrive en phase 6.

## Démarrer (développement)

Prérequis : [uv](https://docs.astral.sh/uv/), Docker, Node 22+ (pour compiler l'interface). Facultatif : [Claude Code](https://code.claude.com) connecté à **votre** compte (`claude /login`), [Ollama](https://ollama.com).

```powershell
uv run --python 3.13 infra/creer_env.py        # .env avec mots de passe générés (jamais versionné)
docker compose up -d                           # PostgreSQL 16 + pgvector (127.0.0.1:5433)
cd core; uv sync; uv run python -m jarvis2 migrer
uv run python -m jarvis2 serveur               # Core : http://127.0.0.1:8765
cd ../interface; npm install; npm run dev      # interface de développement : http://127.0.0.1:5174
```

Pour servir l'interface compilée par le Core : `npm run build` dans `interface`, puis ouvrir **http://localhost:8765** (le nom `localhost`, pas l'adresse IP : les clés d'accès l'exigent).

Premier lancement : le navigateur du PC s'associe d'un clic (« premier appareil »). Ensuite, chaque appareil se jumelle par un QR à usage unique (onglet Sécurité) ou par `uv run python -m jarvis2 jumeler`. Enregistrez une clé d'accès (empreinte, visage, code de l'appareil) pour approuver les actions 🔴.

Sécurité : `uv run python -m jarvis2 verifier-audit` (chaîne du journal d'audit), `uv run python -m jarvis2 lever-urgence` (secours si la clé d'accès est perdue).

Configuration personnelle (sujets exclus, exclusions d'import, requêtes témoins) : copier `config.exemple.toml` vers `%APPDATA%\JARVIS2\config.toml` (Windows) ou `~/.config/jarvis2/config.toml`.

## Importer des données

Depuis JARVIS v1 (sauvegarde `pg_dump -Fc`) : voir [docs/DECISIONS.md](docs/DECISIONS.md#imports--sources-génériques-lecture-seule-exclusions-locales).

## Vérifier

```powershell
cd core; uv run pytest; uv run ruff check .; uv run mypy
cd interface; npm run verifier
```
