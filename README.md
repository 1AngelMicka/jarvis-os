# JARVIS 2

Refonte de JARVIS, l'assistant personnel de l'utilisateur. Plan : [docs/PLAN.md](docs/PLAN.md) · consignes : [CLAUDE.md](CLAUDE.md) · décisions : [docs/DECISIONS.md](docs/DECISIONS.md).

## Démarrer (Windows)

Prérequis : Docker Desktop, Python 3.13 (`C:\Python313\python.exe`), uv, Node 22+, Claude Code connecté à l'abonnement (`claude /login`).

```powershell
C:\Python313\python.exe infra\creer_env.py      # .env avec mots de passe générés (jamais versionné)
docker compose up -d                           # PostgreSQL 16 + pgvector (127.0.0.1:5433)
cd core; uv sync; .\.venv\Scripts\python -m jarvis2 migrer
.\.venv\Scripts\python -m jarvis2 serveur      # Core : http://127.0.0.1:8765
cd ..\interface; npm install; npm run dev      # interface : http://127.0.0.1:5174
```

Pour servir l'interface compilée par le Core : `npm run build` dans `interface`, puis ouvrir http://127.0.0.1:8765.

## Vérifier

```powershell
cd core; .\.venv\Scripts\python -m pytest; .\.venv\Scripts\ruff check .; .\.venv\Scripts\mypy
cd interface; npm run verifier
```
