# Installer JARVIS 2

Ce guide décrit l'installation telle que les scripts [`install.ps1`](../install.ps1) et [`install.sh`](../install.sh) la font réellement, puis l'installation manuelle (développement, PostgreSQL), la configuration locale et le branchement des IA. En cas de souci : [DEPANNAGE.md](DEPANNAGE.md).

## Ce qu'il faut

- **Aucun Docker ni Node pour utiliser JARVIS** : l'interface est précompilée et livrée dans le paquet Python (la « roue » `.whl`), le stockage par défaut est un fichier SQLite.
- **uv**, le gestionnaire Python d'Astral : installé par le script s'il manque (après confirmation). Il fournit Python 3.13 ; le Python du PATH n'est jamais utilisé.
- **Environ 220 Mo** pour le modèle d'embeddings de la mémoire, téléchargé une seule fois pendant la préparation. `jarvis2 docteur` signale un dossier des données avec trop peu d'espace libre.
- **Facultatif** : une IA. Claude Code (votre abonnement), une clé d'API, ou un modèle local (Ollama, LM Studio, llama.cpp, vLLM). Sans aucune IA, JARVIS démarre mais ne peut pas répondre.
- **Pour développer** (compiler l'interface, PostgreSQL) : Node 22 ou plus, Docker pour PostgreSQL.

## Installation par script

Les deux scripts suivent le même contrat : mêmes étapes, mêmes options, même fichier d'état, mêmes codes de sortie.

### Windows

Depuis le dossier du dépôt (interface compilée), ou avec une roue téléchargée depuis la page des versions :

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 --source <jarvis2-x.y.z-py3-none-any.whl>
```

En une ligne, sans cloner le dépôt (le script cherche alors la dernière version publiée sur GitHub) :

```powershell
irm https://raw.githubusercontent.com/1AngelMicka/jarvis-os/main/install.ps1 | iex
```

uv est installé par **winget** s'il est présent, sinon par le script officiel d'Astral (`irm https://astral.sh/uv/install.ps1 | iex`). Après chaque installation, le PATH de la session est relu depuis le registre : inutile de rouvrir le terminal. Les options s'écrivent à la manière de `install.sh` (`--oui`) ou de PowerShell (`-Oui`).

### macOS et Linux

```sh
sh install.sh --source <jarvis2-x.y.z-py3-none-any.whl>
```

En une ligne :

```sh
curl -LsSf https://raw.githubusercontent.com/1AngelMicka/jarvis-os/main/install.sh | sh -s -- [options]
```

uv est installé par **Homebrew** sous macOS s'il est présent, sinon par `curl -LsSf https://astral.sh/uv/install.sh | sh`. Sous macOS et Linux, la commande `jarvis2` n'est connue des terminaux qu'après en avoir ouvert un nouveau (le script le rappelle dans « Reste à faire »).

### Étapes, dans l'ordre

| Étape | Ce qui est fait |
|---|---|
| `uv` | uv installé s'il manque (winget, Homebrew ou script officiel), après confirmation |
| `jarvis2` | `uv tool install --force --python 3.13 <source>` : environnement isolé, commande `jarvis2` |
| `path` | dossier des commandes de uv ajouté au PATH (`uv tool update-shell`) |
| `ollama` | **facultatif**, case **décochée** par défaut : Ollama par winget (Windows), Homebrew (macOS) ou `curl -fsSL https://ollama.com/install.sh \| sh` (Linux) |
| `modele` | **facultatif**, même case : premier modèle choisi pour votre PC par `jarvis2 materiel --modele conversation`, puis `ollama pull` |
| `preparation` | base SQLite et modèle d'embeddings : `jarvis2 docteur --reparer` |
| `demarrage` | `jarvis2` démarre le Core et ouvre l'interface dans le navigateur (sauf `--sans-demarrer`) |

Le script **ne démarre jamais Ollama** : si vous cochez le modèle et qu'Ollama ne répond pas, l'étape reste « en attente : Ollama ne répond pas » et le bilan indique `lancer Ollama (ce script ne le démarre jamais), puis : ollama pull <modèle>`.

Claude Code et Tailscale ne sont **jamais installés** par ces scripts : JARVIS les détecte et l'assistant de premier lancement les propose.

### Options

| Option | Effet |
|---|---|
| `--source <s>` | roue `.whl`, dossier `core` du dépôt ou URL (défaut : ce dépôt, sinon la dernière version publiée) |
| `--oui` | ne rien demander : uv est installé s'il manque ; les cases facultatives (Ollama, modèle) restent **décochées** |
| `--avec-ollama` | cocher d'avance Ollama et le premier modèle |
| `--sans-ollama` | ne proposer ni Ollama ni le modèle |
| `--essai` | à blanc : n'exécute rien, n'écrit rien, affiche ce qui serait fait |
| `--sans-demarrer` | installer et préparer sans lancer JARVIS |
| `--sans-modifier-path` | ne pas toucher au PATH |
| `--recommencer` | ignorer le fichier d'état et tout refaire |

Sans console pour répondre (CI, tâche planifiée), rien n'est demandé, les cases facultatives restent décochées, et uv n'est installé qu'avec `--oui`.

### Reprise et bilan

Chaque étape est notée dans le fichier d'état `installation.etat` : `JARVIS2_ETAT_INSTALLATION` s'il est défini, sinon le dossier de configuration (`%APPDATA%\JARVIS2\installation.etat` sous Windows, `~/.config/jarvis2/installation.etat` ailleurs). Une étape « fait » est sautée à la relance ; une source différente réinstalle JARVIS. Le script finit par un bilan par étape et une liste « Reste à faire ».

| Code de sortie | Sens |
|---|---|
| 0 | installé (ce qui reste à faire est listé) |
| 1 | une étape a échoué : relancer reprend là où ça s'est arrêté |
| 2 | option invalide |
| 3 | outil indispensable refusé, ou impossible à installer sans réponse |

### Avec pipx plutôt que les scripts

```sh
pipx install --python 3.13 jarvis2-x.y.z-py3-none-any.whl
jarvis2 docteur --reparer   # base SQLite et modèle d'embeddings, une seule fois
jarvis2
```

## Premier lancement

`jarvis2` seul migre la base SQLite, démarre le Core sur `127.0.0.1:8765` et ouvre `http://localhost:8765/`. Ouvrez l'interface par **`localhost`**, pas par l'adresse IP : les clés d'accès (WebAuthn) exigent un nom d'hôte.

1. Le navigateur du PC s'enregistre d'un clic comme **premier appareil** (possible seulement depuis le PC, tant qu'aucun appareil n'a été enregistré).
2. L'**assistant d'installation** vérifie tout (boutons « Réparer »), aide à choisir une IA et à associer le téléphone. Il reste accessible depuis le panneau État (« Installation »), ou par `/installation` dans la saisie.
3. Ajoutez une **clé d'accès** (Réglages › Sécurité › Clés d'accès) : elle seule permet d'approuver les actions 🔴.

Commandes utiles :

```sh
jarvis2                      # démarrer le Core et ouvrir l'interface
jarvis2 docteur              # diagnostic (--json, --reparer, --latence)
jarvis2 materiel             # matériel du PC et modèles locaux conseillés (lecture seule)
jarvis2 jumeler              # lien d'association à usage unique (5 minutes) pour un appareil
jarvis2 verifier-audit       # vérifier la chaîne d'empreintes du journal d'audit
jarvis2 lever-urgence        # secours si la clé d'accès est perdue
jarvis2 serveur --sans-ecran # serveur domestique sans écran (voir SERVEUR.md)
jarvis2 --help               # toutes les commandes
```

Serveur domestique sans écran (mini-PC, NAS) : [SERVEUR.md](SERVEUR.md).

### Application de bureau

Les installeurs (Windows `.exe`/`.msi`, macOS `.dmg`, Linux `.deb`/`.AppImage`) sont joints aux versions publiées. L'application ouvre l'interface dans sa fenêtre et lance le Core s'il ne tourne pas : elle **s'appuie sur le Core installé** par l'un des moyens ci-dessus. Elle se range dans la zone de notification ; Ctrl+Maj+J (ou Ctrl+Alt+J si le premier est déjà pris) la ramène.

Les installeurs ne sont pas encore signés :

- **Windows** : SmartScreen affiche « Windows a protégé votre ordinateur ». Cliquez sur « Informations complémentaires » puis « Exécuter quand même ».
- **macOS** : Gatekeeper refuse d'ouvrir l'application. Après l'avoir copiée dans Applications, lancez une fois `xattr -dr com.apple.quarantine "/Applications/JARVIS 2.app"`.

Ne téléchargez les installeurs que depuis la page des versions du dépôt.

### Téléphone

Le Core n'écoute que sur le PC. Pour le joindre depuis le téléphone : Tailscale sur les deux appareils (même compte), puis une fois sur le PC `tailscale serve --bg 8765` ; associez ensuite le téléphone depuis l'assistant (étape Téléphone) ou Réglages › Appareils › Téléphone. JARVIS lit l'état de Tailscale mais ne lance jamais `tailscale up` ni `tailscale serve` lui-même.

## Installation manuelle (développement)

Prérequis : [uv](https://docs.astral.sh/uv/), Node 22+, Docker seulement pour PostgreSQL.

```sh
cd core
uv sync
uv run python -m jarvis2 serveur      # Core (SQLite par défaut) sur http://127.0.0.1:8765
```

```sh
cd interface
npm install
npm run dev                            # interface de développement sur http://127.0.0.1:5174
```

Pour que le Core serve lui-même l'interface : `npm run build` dans `interface`, puis ouvrez `http://localhost:8765`. Sans interface compilée, le Core affiche une page « JARVIS 2 fonctionne, mais son interface n'est pas installée ».

Construire la roue installable : `npm run build` dans `interface`, puis `cd core; uv build --wheel` (l'interface est incluse). Installer directement le dépôt : `pipx install --python 3.13 ./core` après `npm run build`.

### Avec PostgreSQL + pgvector (option)

```sh
uv run --python 3.13 infra/creer_env.py   # crée .env avec des mots de passe aléatoires, sans les afficher
docker compose up -d                      # PostgreSQL 16 + pgvector, publié sur 127.0.0.1:5433 seulement
cd core
uv run python -m jarvis2 migrer           # migrations (rôle propriétaire)
uv run python -m jarvis2 serveur
```

`creer_env.py` ne remplace jamais un `.env` existant. Le choix du stockage se fait par `JARVIS2_STOCKAGE` (`sqlite` ou `postgres`) ; vide, JARVIS prend PostgreSQL si `JARVIS2_APP_MOT_DE_PASSE` est rempli, sinon SQLite. Les données PostgreSQL vivent dans le volume Docker nommé `jarvis2_pg`.

Passer d'un stockage à l'autre, vers un stockage **vide** (la source est seulement lue, la copie est vérifiée) :

```sh
jarvis2 stockage copier --vers sqlite      # ou --vers postgres
```

### Vérifier

```sh
cd core; uv run pytest; uv run ruff check .; uv run mypy
cd interface; npm run verifier             # lint + typecheck + tests
```

## Configuration locale

Rien de personnel ne va dans le dépôt. Deux fichiers, tous deux **facultatifs** et jamais versionnés :

| Fichier | Emplacement | Contenu |
|---|---|---|
| `config.toml` | `%APPDATA%\JARVIS2\config.toml` (Windows), `~/.config/jarvis2/config.toml` (macOS, Linux, ou `$XDG_CONFIG_HOME/jarvis2/`), ou le chemin donné par `JARVIS2_CONFIG` | ce qui vous est personnel : sujets exclus et privés, projets des ateliers, serveurs MCP, SearXNG, lieu de l'accueil du matin, connecteurs compatibles OpenAI, tarifs, exclusions d'import, réglages du PC |
| `jarvis2.env` | même dossier que `config.toml` (en développement : `.env` à la racine du dépôt) | réglages du Core : port, stockage, dossier des données, moteur par défaut, modèle Whisper… |

Modèles commentés : [`config.exemple.toml`](../config.exemple.toml) et [`.env.example`](../.env.example). `config.toml` est lu **au démarrage du Core** : redémarrez-le après une modification.

À côté de `config.toml` vivent aussi :

- `coffre.json` : le coffre des clés d'API (chiffré par DPAPI sous Windows, fichier en droits 0600 ailleurs) ;
- `recettes/` : les recettes planifiées (voir [EXTENSIONS.md](EXTENSIONS.md)) ;
- `installation.etat` : le fichier d'état des scripts d'installation.

Les données lourdes (base SQLite `jarvis2.db`, journaux, modèles) vont dans le **dossier des données** : `%LOCALAPPDATA%\JARVIS2` sous Windows, `~/.local/share/jarvis2` ailleurs (ou `$XDG_DATA_HOME/jarvis2`), déplaçable par `JARVIS2_DOSSIER_DONNEES`.

Réglages courants de `jarvis2.env` :

| Variable | Défaut | Rôle |
|---|---|---|
| `JARVIS2_PORT` | `8765` | port du Core |
| `JARVIS2_HOTE` | `127.0.0.1` | adresse d'écoute ; toute autre valeur est refusée sans `JARVIS2_OUVERTURE_RESEAU=true` |
| `JARVIS2_STOCKAGE` | vide | `sqlite` ou `postgres` |
| `JARVIS2_SQLITE` | `<données>/jarvis2.db` | fichier SQLite |
| `JARVIS2_DOSSIER_DONNEES` | voir ci-dessus | dossier des données lourdes |
| `JARVIS2_MOTEUR_DEFAUT` | `claude_code` | connecteur préféré du routeur |
| `JARVIS2_CLAUDE_COMMANDE` | vide (PATH) | chemin de la CLI `claude` |
| `JARVIS2_OLLAMA_URL` | `http://127.0.0.1:11434` | adresse d'Ollama |
| `JARVIS2_MODELE_VOIX` | `base` | modèle Whisper (tiny, base, small, medium…) |
| `JARVIS2_SANS_ECRAN` | `false` | mode serveur sans écran |
| `JARVIS2_ORIGINES` | vide | origines web supplémentaires, en liste JSON |

## Brancher une IA

Toutes les IA se gèrent dans la vue **Connecteurs** (une carte par fournisseur, bouton « Tester »). Le routeur choisit parmi les connecteurs actifs ; vous pouvez imposer votre choix par conversation.

### Claude Code, avec votre abonnement Claude

1. Installez Claude Code vous-même ([code.claude.com](https://code.claude.com)) et connectez-le **vous-même** à votre compte : `claude`, puis `/login`.
2. Dans Connecteurs, lisez et cochez l'avertissement de la carte Claude Code (usage personnel, non commercial). Le connecteur reste inactif tant qu'il n'est pas coché.

JARVIS appelle le binaire officiel, non modifié (`claude -p`, sortie `stream-json`), dans un dossier de travail vide. Il ne propose jamais de connexion Claude.ai, ne lit ni ne stocke aucun identifiant, retire les clés d'API (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`…) de l'environnement du sous-processus, et **refuse toute réponse dont la source d'authentification n'est pas l'abonnement**. Si la CLI n'est pas dans le PATH, indiquez son chemin dans `JARVIS2_CLAUDE_COMMANDE`.

### API Anthropic (clé, facturée à l'usage)

Carte « Anthropic » de Connecteurs : collez la clé. Elle va dans le coffre local ; l'interface n'en reçoit jamais que l'état « enregistrée » et les 4 derniers caractères. Les coûts sont suivis dans la vue Coûts, avec un plafond mensuel réglable par connecteur payant. Le modèle par défaut se règle par `[connecteurs.anthropic_api] modele = "…"` dans `config.toml`.

### Ollama (modèles locaux)

- Installez Ollama ([ollama.com](https://ollama.com)), ou cochez-le dans le script d'installation.
- Téléchargez un modèle à la main : `ollama pull <modèle>`. `jarvis2 materiel` conseille un modèle adapté à votre mémoire vive et à votre carte graphique.
- **JARVIS ne démarre jamais Ollama de lui-même.** S'il est arrêté, le connecteur est affiché « Ollama arrêté (jamais démarré automatiquement) ». Vous pouvez le lancer vous-même, ou demander à JARVIS de le faire depuis Réglages › PC & mode jeu (action 🟡 `ollama.demarrer`, jamais « toujours autorisée »). JARVIS n'arrête que l'Ollama qu'il a lui-même lancé, après 20 minutes sans modèle chargé par défaut (`[pc] ollama_inactivite_min`).
- Modèle par défaut et modèle de vision : `[connecteurs.ollama] modele = "…"` et `modele_vision = "…"`.

### Serveurs compatibles OpenAI

- **Locaux** : LM Studio (`127.0.0.1:1234`), serveur llama.cpp (`127.0.0.1:8080`), vLLM (`127.0.0.1:8000`) sont détectés sur leurs ports habituels et **démarrent désactivés** : activez-les dans Connecteurs.
- **Avec clé** : OpenAI, Google Gemini (point d'accès compatible OpenAI), OpenRouter.
- **Tout autre point d'accès** : déclarez-le dans `config.toml` :

```toml
[[connecteurs.compatibles]]
id = "monserveur"
nom = "Mon serveur"
url = "http://127.0.0.1:8000/v1"
local = true   # serveur du PC : les données ne le quittent pas
```

### Autres comptes par programme officiel

OpenAI Codex (compte ChatGPT, `codex login` fait par vous) et Google Antigravity. Antigravity est **désactivé par défaut**, porte un badge « risque » permanent et n'est jamais choisi par le routeur : ses conditions interdisent l'accès par un logiciel tiers. La clé d'API Gemini est l'alternative recommandée.

## Sauvegarde

```sh
jarvis2 sauvegarde creer --dossier <dossier hors du PC>     # chiffrée par une phrase de passe (12 caractères au moins)
jarvis2 sauvegarde verifier --fichier <fichier .jarvis2>   # restauration réelle dans une base temporaire
```

Les 7 dernières sauvegardes sont gardées (`--garder`). Sans la phrase de passe, une sauvegarde est illisible.

## Désinstaller

JARVIS ne fournit **pas** de commande de désinstallation. Avec les outils utilisés pour l'installer :

1. Arrêtez JARVIS (Ctrl+C dans son terminal, ou quittez l'application de bureau).
2. Retirez le programme : `uv tool uninstall jarvis2` (ou `pipx uninstall jarvis2`).
3. Pour effacer aussi vos données, **après une sauvegarde si vous voulez les garder** (c'est irréversible) : supprimez le dossier de configuration (`%APPDATA%\JARVIS2` ou `~/.config/jarvis2`, avec le coffre et les recettes) et le dossier des données (`%LOCALAPPDATA%\JARVIS2` ou `~/.local/share/jarvis2`, avec la base SQLite, les journaux et les modèles).
4. Avec PostgreSQL : `docker compose down` arrête le conteneur ; les données restent dans le volume `jarvis2_pg` tant que vous ne le supprimez pas vous-même.

Ollama, Claude Code et Tailscale sont des programmes indépendants : désinstallez-les par leurs propres moyens si vous le souhaitez.
