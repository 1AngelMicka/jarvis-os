# JARVIS 2

Assistant personnel local d'abord : mémoire à long terme, conversation en flux avec les IA de votre choix, interface HUD. Connecteurs : vos comptes par les programmes officiels (Claude Code, OpenAI Codex, Google Antigravity avec avertissement), vos clés d'API (Anthropic, OpenAI, Gemini, OpenRouter, tout service compatible OpenAI), vos modèles locaux (Ollama, LM Studio, llama.cpp, vLLM) ; routeur automatique et conseil multi-IA.

Plan : [docs/PLAN.md](docs/PLAN.md) · décisions : [docs/DECISIONS.md](docs/DECISIONS.md) · design : [interface/DESIGN.md](interface/DESIGN.md).

> Projet en construction. Les installeurs (.exe, .dmg…) et la publication arrivent en phase 11.

## Installer (sans Docker ni Node)

Windows :

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 -Source <jarvis2-x.y.z-py3-none-any.whl>
```

macOS, Linux :

```sh
sh install.sh --source <jarvis2-x.y.z-py3-none-any.whl>
```

Le script installe [uv](https://docs.astral.sh/uv/) s'il manque (après confirmation), puis JARVIS 2 (`uv tool install`, Python 3.13 géré par uv), prépare la base SQLite et le modèle d'embeddings (environ 220 Mo, une seule fois), et lance `jarvis2` : l'interface s'ouvre dans le navigateur, sur `http://localhost:8765`.

Au premier lancement, le navigateur du PC s'associe d'un clic, puis l'**assistant d'installation** vérifie tout (avec des boutons « Réparer »), aide à choisir une IA et à associer le téléphone. Il reste accessible depuis le panneau État (« Installation »).

Commandes utiles : `jarvis2` (démarrer et ouvrir l'interface), `jarvis2 docteur` (diagnostic ; `--json`, `--reparer`), `jarvis2 jumeler` (lien d'association d'un appareil), `jarvis2 verifier-audit`, `jarvis2 lever-urgence` (secours si la clé d'accès est perdue).

Facultatif, détecté mais jamais installé par JARVIS :

- [Claude Code](https://code.claude.com), connecté à **votre** compte (`claude /login`), pour utiliser votre abonnement Claude. Un avertissement (usage personnel) est à lire et à cocher une fois.
- [Ollama](https://ollama.com) pour des modèles locaux.
- [Tailscale](https://tailscale.com/download) pour le téléphone (voir ci-dessous).

## Téléphone

JARVIS n'écoute que sur le PC. Pour le joindre depuis le téléphone, même hors de chez vous :

1. Installez Tailscale sur le PC et sur le téléphone, avec le même compte.
2. Sur le PC, une seule fois : `tailscale serve --bg 8765`. JARVIS est alors joignable à `https://<nom-du-pc>.<réseau>.ts.net`, sur votre réseau privé seulement.
3. Dans l'assistant (étape Téléphone) ou l'onglet Sécurité : « Associer un téléphone », puis scannez le QR. Sur le téléphone, « Ajouter à l'écran d'accueil » installe JARVIS comme une application.

## Stockage

Par défaut, un fichier SQLite dans le dossier des données (`%LOCALAPPDATA%\JARVIS2` ou `~/.local/share/jarvis2`, déplaçable par `JARVIS2_DOSSIER_DONNEES`). PostgreSQL + pgvector reste possible (`JARVIS2_STOCKAGE=postgres`, voir `docker-compose.yml`). Passer de l'un à l'autre : `jarvis2 stockage copier --vers sqlite` (ou `--vers postgres`), vers un stockage vide ; la copie est vérifiée (nombres de lignes, chaîne d'audit).

Configuration personnelle (sujets exclus, exclusions d'import, connecteurs, tarifs) : copier `config.exemple.toml` vers `%APPDATA%\JARVIS2\config.toml` (Windows) ou `~/.config/jarvis2/config.toml`. Réglages du Core (port, stockage…) : `.env.example`.

## Développement

Prérequis : [uv](https://docs.astral.sh/uv/), Node 22+ (interface). Docker seulement pour PostgreSQL.

```powershell
cd core; uv sync; uv run python -m jarvis2 serveur   # Core (SQLite par défaut) : http://127.0.0.1:8765
cd interface; npm install; npm run dev                # interface de développement : http://127.0.0.1:5174
```

Avec PostgreSQL : `uv run --python 3.13 infra/creer_env.py` (`.env` avec mots de passe générés), `docker compose up -d`, `cd core; uv run python -m jarvis2 migrer`.

Pour servir l'interface compilée par le Core : `npm run build` dans `interface`, puis ouvrir **http://localhost:8765** (le nom `localhost`, pas l'adresse IP : les clés d'accès l'exigent). Construire le paquet installable : `npm run build` puis `cd core; uv build --wheel` (l'interface est incluse dans la roue).

## Importer des données

Depuis JARVIS v1 (sauvegarde `pg_dump -Fc`, stockage PostgreSQL) : voir [docs/DECISIONS.md](docs/DECISIONS.md#imports--sources-génériques-lecture-seule-exclusions-locales), puis `jarvis2 stockage copier --vers sqlite` si vous voulez passer à SQLite.

## Vérifier

```powershell
cd core; uv run pytest; uv run ruff check .; uv run mypy   # tests sur SQLite, et sur PostgreSQL si Docker tourne
cd interface; npm run verifier
```
