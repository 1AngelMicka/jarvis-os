# JARVIS 2

Assistant personnel local d'abord : mémoire à long terme, conversation en flux avec les IA de votre choix, interface HUD. Connecteurs : vos comptes par les programmes officiels (Claude Code, OpenAI Codex, Google Antigravity avec avertissement), vos clés d'API (Anthropic, OpenAI, Gemini, OpenRouter, tout service compatible OpenAI), vos modèles locaux (Ollama, LM Studio, llama.cpp, vLLM) ; routeur automatique et conseil multi-IA.

Plan : [docs/PLAN.md](docs/PLAN.md) · décisions : [docs/DECISIONS.md](docs/DECISIONS.md) · design : [interface/DESIGN.md](interface/DESIGN.md).

> **Statut : en développement (0.8.0).** Les phases 1 à 10 du plan sont faites (socle, dialogue, mémoire, sécurité, connecteurs d'IA, installation, agents, mémoire v2, ateliers Claude Code, voix et vision). L'application de bureau et ses installeurs sont construits par GitHub Actions, pas encore signés ; la sauvegarde chiffrée est prête. Captures d'écran à venir.

## Installer (sans Docker ni Node)

Windows :

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 --source <jarvis2-x.y.z-py3-none-any.whl>
```

macOS, Linux :

```sh
sh install.sh --source <jarvis2-x.y.z-py3-none-any.whl>
```

Le script installe ce qui manque (uv, par winget sous Windows et Homebrew sous macOS s'ils sont là, sinon par le script officiel d'Astral, après confirmation), puis JARVIS 2 (`uv tool install`, Python 3.13 géré par uv), ajoute la commande `jarvis2` au PATH (sous Windows, le PATH de la session est relu depuis le registre : pas besoin de rouvrir le terminal), prépare la base SQLite et le modèle d'embeddings (environ 220 Mo, une seule fois), et lance `jarvis2` : l'interface s'ouvre dans le navigateur, sur `http://localhost:8765`.

- **Ollama et un premier modèle** sont seulement **proposés**, par une case à cocher décochée par défaut ; le modèle est choisi pour votre PC par la table matériel → modèle de JARVIS (`jarvis2 materiel`). Sans réponse possible (CI, `--oui`), rien n'est coché. Le script ne démarre jamais Ollama.
- **Reprise** : chaque étape est notée dans `installation.etat` (dossier de configuration) ; après une coupure, relancer le script reprend là où il s'était arrêté (`--recommencer` pour tout refaire).
- **Bilan honnête** à la fin : ce qui est fait, refusé, en échec, et ce qui reste à faire.
- Options communes aux deux scripts : `--oui` (ne rien demander), `--avec-ollama` / `--sans-ollama`, `--essai` (à blanc : affiche ce qui serait fait, n'exécute rien), `--sans-demarrer`, `--sans-modifier-path`, `--recommencer`. Codes de sortie : 0 installé, 1 une étape a échoué (relancer reprend), 2 option invalide, 3 outil indispensable refusé.

Avec [pipx](https://pipx.pypa.io) plutôt que les scripts (même roue, interface incluse) :

```sh
pipx install --python 3.13 jarvis2-x.y.z-py3-none-any.whl
jarvis2 docteur --reparer   # base SQLite et modèle d'embeddings, une seule fois
jarvis2
```

Au premier lancement, le navigateur du PC s'associe d'un clic, puis l'**assistant d'installation** vérifie tout (avec des boutons « Réparer »), aide à choisir une IA et à associer le téléphone. Il reste accessible depuis le panneau État (« Installation »).

Commandes utiles : `jarvis2` (démarrer et ouvrir l'interface), `jarvis2 docteur` (diagnostic ; `--json`, `--reparer`), `jarvis2 materiel` (matériel du PC et modèles conseillés, lecture seule), `jarvis2 jumeler` (lien d'association d'un appareil), `jarvis2 verifier-audit`, `jarvis2 lever-urgence` (secours si la clé d'accès est perdue), `jarvis2 serveur --sans-ecran` (serveur domestique sans écran : voir [docs/SERVEUR.md](docs/SERVEUR.md)).

Mettre à jour : `jarvis2 mettre-a-jour` (rien n'est installé sans votre accord) ; voir [docs/MISES_A_JOUR.md](docs/MISES_A_JOUR.md), aussi pour l'application de bureau.

Facultatif, détecté mais jamais installé par JARVIS :

- [Claude Code](https://code.claude.com), connecté à **votre** compte (`claude /login`), pour utiliser votre abonnement Claude. Un avertissement (usage personnel) est à lire et à cocher une fois.
- [Ollama](https://ollama.com) pour des modèles locaux (le script d'installation le propose, case décochée ; JARVIS lui-même ne l'installe ni ne le démarre jamais seul).
- [Tailscale](https://tailscale.com/download) pour le téléphone (voir ci-dessous).

## Application de bureau

Les installeurs (Windows `.exe`/`.msi`, macOS `.dmg`, Linux `.deb`/`.AppImage`) sont joints à chaque version publiée. L'application ouvre l'interface dans sa propre fenêtre, lance le Core s'il ne tourne pas, se range dans la zone de notification (Ctrl+Maj+J, ou Ctrl+Alt+J si le premier est déjà pris, la ramène). Elle s'appuie sur le Core installé par le script ci-dessus.

Les installeurs ne sont pas encore signés :

- **Windows** : SmartScreen affiche « Windows a protégé votre ordinateur ». Cliquez sur « Informations complémentaires » puis « Exécuter quand même ».
- **macOS** : Gatekeeper refuse d'ouvrir l'application. Après l'avoir copiée dans Applications, lancez une fois `xattr -dr com.apple.quarantine "/Applications/JARVIS 2.app"`.

Ne téléchargez les installeurs que depuis la page des versions de ce dépôt.

## Sauvegarde

```powershell
jarvis2 sauvegarde creer --dossier D:\Sauvegardes\JARVIS      # chiffrée par votre phrase de passe ; gardez-la hors du PC
jarvis2 sauvegarde verifier --fichier D:\Sauvegardes\JARVIS\jarvis2-AAAAMMJJ-HHMMSS.jarvis2
```

La vérification restaure la sauvegarde dans une base temporaire et contrôle les lignes et la chaîne d'audit. Sans la phrase de passe, la sauvegarde est illisible : notez-la ailleurs que sur ce PC.

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

Pour servir l'interface compilée par le Core : `npm run build` dans `interface`, puis ouvrir **http://localhost:8765** (le nom `localhost`, pas l'adresse IP : les clés d'accès l'exigent). Construire le paquet installable : `npm run build` puis `cd core; uv build --wheel` (l'interface est incluse dans la roue ; sans interface compilée, la roue est construite sans elle, avec un avertissement, et le Core affiche une page d'explication). Installer directement le dépôt : `pipx install --python 3.13 ./core` après `npm run build`.

## Importer des données

Depuis JARVIS v1 (sauvegarde `pg_dump -Fc`, stockage PostgreSQL) : voir [docs/DECISIONS.md](docs/DECISIONS.md#imports--sources-génériques-lecture-seule-exclusions-locales), puis `jarvis2 stockage copier --vers sqlite` si vous voulez passer à SQLite.

## Comptes d'IA et conditions des fournisseurs

JARVIS n'est affilié à aucun fournisseur d'IA. Avec un compte (plutôt qu'une clé d'API), il appelle le **programme officiel** du fournisseur, installé et connecté par vous, sans le modifier, et ne lit jamais vos identifiants. Votre usage reste soumis aux conditions de chaque fournisseur :

- **Claude Code** (abonnement Claude) : abonnement personnel, pour votre propre usage, pas d'usage commercial ni pour d'autres personnes. L'avertissement est à cocher une fois.
- **OpenAI Codex** (compte ChatGPT) : selon les conditions d'OpenAI.
- **Google Antigravity** : ses conditions interdisent l'accès par un logiciel tiers et des comptes ont été suspendus pour cet usage. Ce connecteur est désactivé par défaut, porte un badge « risque » permanent, n'est jamais choisi automatiquement, et la clé d'API Gemini est recommandée à la place.

En cas de doute, une clé d'API (facturée à l'usage) ou un modèle local est toujours possible.

## Licence

[Apache 2.0](LICENSE).

## Vérifier

```powershell
cd core; uv run pytest; uv run ruff check .; uv run mypy   # tests sur SQLite, et sur PostgreSQL si Docker tourne
cd interface; npm run verifier
```
