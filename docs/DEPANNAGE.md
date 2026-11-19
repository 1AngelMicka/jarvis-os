# Dépannage

Les messages cités ici sont ceux que JARVIS affiche réellement. Premier réflexe, toujours :

```sh
jarvis2 docteur            # diagnostic lisible ; --json pour le joindre à un signalement
jarvis2 docteur --reparer  # réparations sûres : schéma SQLite, modèle d'embeddings
```

Le diagnostic vérifie Python, le dossier des données, le stockage et son schéma, l'interface, le modèle de la mémoire, la dictée, les IA (« Cerveau »), Claude Code, le réseau, le téléphone, l'écran, le journal d'audit, le matériel, le Core lui-même et la latence de la voix. Il rend un code non nul tant qu'une vérification est en erreur. Les journaux du Core sont dans `<dossier des données>/journaux` (`%LOCALAPPDATA%\JARVIS2\journaux` ou `~/.local/share/jarvis2/journaux`), secrets masqués.

Avant d'ouvrir une issue, relisez votre sortie : elle contient des chemins de votre PC. Pour une faille de sécurité, n'ouvrez pas d'issue : voir [SECURITY.md](../SECURITY.md).

## Installation

### La commande `jarvis2` est introuvable

- **Windows** : le script relit le PATH depuis le registre ; si uv vient d'être installé et reste introuvable, il s'arrête sur « uv installé mais introuvable : ouvrez un nouveau terminal et relancez ce script ».
- **macOS, Linux** : le PATH n'est mis à jour que pour les **nouveaux** terminaux (« ouvrir un nouveau terminal pour que la commande jarvis2 y soit connue »).
- Avec `--sans-modifier-path`, le PATH n'est pas touché : lancez le programme par son chemin complet (dossier donné par `uv tool dir --bin`), ou ajoutez ce dossier au PATH (`uv tool update-shell`).

### Le script s'arrête avec le code 3

- « installer uv (…), ou relancer avec --oui » : aucune console pour confirmer l'installation de uv. Relancez dans un terminal, ou avec `--oui`.
- « compiler l'interface (cd interface ; npm install ; npm run build), ou --source <roue .whl> » : le script est lancé depuis un clone du dépôt dont l'interface n'est pas compilée. Compilez-la (Node 22+), ou passez une roue publiée par `--source`.
- « indiquer --source <fichier .whl> (aucune version publiée trouvée) » : la ligne `irm … | iex` ou `curl … | sh` n'a trouvé aucune roue dans les versions publiées. Téléchargez une roue et passez-la par `--source`.

### L'installation s'est interrompue (code 1)

Relancez le même script : il reprend à l'étape en échec grâce au fichier d'état `installation.etat`. `--recommencer` ignore ce fichier et refait tout ; `--essai` montre ce qui serait fait sans rien exécuter.

### « Préparation : faite, points signalés ci-dessus »

Ce n'est pas un échec : la base et le modèle sont prêts, mais `jarvis2 docteur` signale encore des points (souvent : aucune IA branchée, téléphone non associé). L'assistant de premier lancement aide à les régler.

### « Python 3.x : versions prises en charge 3.12 et 3.13 »

JARVIS a été installé avec un Python non pris en charge. Réinstallez-le avec le script d'installation ou `pipx install --python 3.13 …` : uv fournit le bon Python.

### La page affiche « JARVIS 2 fonctionne, mais son interface n'est pas installée »

Le paquet a été construit sans interface compilée (le diagnostic l'indique : « interface compilée absente »). Installez une roue publiée, ou, depuis le dépôt : `cd interface ; npm install ; npm run build`, puis réinstallez.

### Windows ou macOS refuse d'ouvrir l'application de bureau

Les installeurs ne sont pas encore signés : voir les contournements (SmartScreen, Gatekeeper) dans [INSTALLATION.md](INSTALLATION.md#application-de-bureau). Ne téléchargez les installeurs que depuis la page des versions du dépôt.

## Démarrage du Core

### Le port 8765 est déjà occupé

JARVIS ne traite pas ce cas lui-même : le serveur web s'arrête au démarrage avec l'erreur du système (« adresse déjà utilisée »).

1. Vérifiez d'abord que ce n'est pas JARVIS lui-même, déjà lancé (terminal ouvert, application de bureau) : `jarvis2 docteur` affiche alors la ligne « Core : en marche sur http://localhost:8765 ».
2. Sinon, choisissez un autre port : `JARVIS2_PORT=8766` dans `jarvis2.env` (à côté de `config.toml`), puis ouvrez `http://localhost:8766`.
3. Avec un autre port, publiez ce port-là pour le téléphone (`tailscale serve --bg 8766`). L'application de bureau lit le port dans la **variable d'environnement** `JARVIS2_PORT` (pas dans `jarvis2.env`) : définissez-la aussi pour elle.

### « Refusé : le Core n'écoute que sur 127.0.0.1, sauf JARVIS2_OUVERTURE_RESEAU=true »

`JARVIS2_HOTE` vaut autre chose que `127.0.0.1`, `localhost` ou `::1`. Remettez `127.0.0.1` et utilisez Tailscale pour l'accès à distance (voir [SERVEUR.md](SERVEUR.md)). Ouvrir le Core au réseau local reste possible avec `JARVIS2_OUVERTURE_RESEAU=true`, mais tout appareil du réseau peut alors le joindre (le diagnostic le signale en « attention »).

### Le Core ne démarre plus après une modification de `config.toml`

Le fichier est lu au démarrage ; un TOML mal formé ou une valeur du mauvais type l'en empêche. Exemple de message : « confidentialite.sujets_exclus : liste d'expressions régulières attendue ». Corrigez le fichier (modèle : [`config.exemple.toml`](../config.exemple.toml)) ou renommez-le le temps de redémarrer.

### « Dossier des données : … écriture impossible » ou « … Go libres seulement »

Le dossier des données n'est pas accessible en écriture, ou le disque est presque plein. Libérez de la place ou déplacez les données avec `JARVIS2_DOSSIER_DONNEES`.

## Accès depuis le navigateur ou le téléphone

### « Appareil non autorisé : jumelez cet appareil » / « Cet appareil n'est pas (ou plus) autorisé. »

Chaque appareil doit être associé ; son jeton a pu être révoqué ou effacé (navigation privée, stockage du navigateur vidé). Associez-le de nouveau : QR depuis un appareil déjà autorisé (Réglages › Appareils), ou `jarvis2 jumeler` sur le PC (lien valable 5 minutes, une seule fois).

### « Le premier appareil s'enregistre depuis le PC (http://localhost) »

Le tout premier appareil ne peut s'enregistrer que depuis le navigateur du PC, par `http://localhost:8765`. Sur un serveur sans écran : `jarvis2 jumeler --adresse <adresse Tailscale>` en SSH, ou un tunnel SSH (voir [SERVEUR.md](SERVEUR.md)).

### Le jumelage est bloqué (HTTP 429)

Après 5 échecs depuis une même source, ou 20 au total en 15 minutes, l'échange de code est bloqué, même avec un bon code. Créez un nouveau code depuis un appareil autorisé : cela lève le blocage.

### « Origine non autorisée »

L'interface est ouverte depuis une adresse que le Core ne connaît pas (adresse IP, autre port, autre nom). Utilisez `http://localhost:<port>`, ou l'adresse Tailscale une fois `tailscale serve` actif (elle est ajoutée automatiquement). Une autre origine se déclare dans `JARVIS2_ORIGINES` (liste JSON).

### Impossible d'enregistrer une clé d'accès

Les clés d'accès (WebAuthn) exigent un **nom d'hôte** : elles ne fonctionnent pas sur une adresse IP. Ouvrez l'interface par `localhost` ou par le nom Tailscale.

### Le téléphone ne joint pas JARVIS

Le diagnostic, ligne « Téléphone (accès à distance) », dit où vous en êtes : « Tailscale non installé », « Tailscale installé mais non connecté sur ce PC » (`tailscale up`), ou « le Core n'est pas encore publié » (il donne la commande `tailscale serve` à lancer). JARVIS ne lance jamais ces commandes lui-même.

### Le micro ne marche pas depuis le téléphone

Le navigateur n'ouvre le micro que sur une page sécurisée : utilisez l'adresse HTTPS de Tailscale (ou `localhost` par un tunnel SSH), pas une adresse IP en HTTP.

## Les IA (connecteurs)

### « Aucun connecteur d'IA disponible : ouvrez l'onglet Connecteurs »

Aucune IA n'est utilisable (diagnostic : « Aucun connecteur d'IA utilisable »). Branchez Claude Code, ajoutez une clé d'API ou lancez Ollama : voir [INSTALLATION.md](INSTALLATION.md#brancher-une-ia).

### Ollama : « Ollama arrêté (jamais démarré automatiquement) »

C'est voulu : JARVIS ne démarre jamais Ollama de lui-même, il le signale indisponible. Lancez Ollama vous-même, ou demandez-le à JARVIS dans Réglages › PC & mode jeu (action 🟡 `ollama.demarrer`, à approuver). Messages possibles à ce moment-là : « Ollama n'est pas installé sur ce PC (https://ollama.com/download) », « Ollama s'est arrêté aussitôt après son lancement (voir son journal) ».

L'Ollama lancé par JARVIS est arrêté après 20 minutes sans modèle chargé (`[pc] ollama_inactivite_min`), en mode jeu et à l'arrêt du Core ; un Ollama que vous avez lancé vous-même n'est jamais arrêté.

### « Sujet privé : aucune IA locale n'est disponible, et ce message ne quitte pas le PC. »

Le message nomme un de vos sujets privés (`[confidentialite] sujets_prives`), ou des souvenirs privés y répondent : le routeur ne le confie qu'à une IA locale, et refuse plutôt que de le laisser sortir. Lancez Ollama ou un autre modèle local, ou choisissez une IA à la main pour ce message.

### Claude Code : « CLI claude introuvable : installer Claude Code puis « claude /login » »

La CLI `claude` n'est pas dans le PATH du Core. Installez Claude Code ([code.claude.com](https://code.claude.com)), ou indiquez son chemin dans `JARVIS2_CLAUDE_COMMANDE`.

### Claude Code : « Claude Code n'est pas connecté : lancer « claude » puis /login »

Connectez Claude Code **vous-même** à votre compte : `claude`, puis `/login`. JARVIS ne propose jamais cette connexion et ne lit aucun identifiant.

### Claude Code : « La CLI claude s'authentifie par une clé API (source : …) : refusé, JARVIS n'utilise que l'abonnement Claude »

Le moteur `claude_code` refuse toute réponse dont la source d'authentification n'est pas l'abonnement. JARVIS retire déjà les clés d'API de l'environnement du sous-processus : si le refus persiste, c'est Claude Code lui-même qui est configuré pour une clé d'API. Reconnectez-le avec votre compte d'abonnement (`/login`), ou utilisez plutôt le connecteur « API Anthropic » si vous voulez une facturation à l'usage.

Variante : « Source d'authentification de la CLI claude inconnue : réponse refusée » — la CLI n'a pas annoncé sa source d'authentification ; mettez Claude Code à jour.

### Claude Code : « avertissement à lire et accepter avant le premier usage »

Le connecteur ne s'active qu'après l'avertissement coché par vous (carte Claude Code de la vue Connecteurs).

### Claude Code : « La CLI claude n'a pas répondu en … s »

La réponse a dépassé le délai (120 s, 600 s pour les efforts `xhigh` et `max`). Réessayez, ou baissez l'effort (`JARVIS2_CLAUDE_EFFORT`).

### « Connecteur « … » désactivé : activez-le dans Connecteurs »

Le connecteur choisi (ou imposé à la conversation) a été désactivé. Réactivez-le, ou repassez la conversation en « Auto ».

### Plafond de dépenses atteint

Un connecteur payant a atteint son plafond mensuel : le routeur passe à une autre IA s'il en trouve une, sinon la demande est refusée avec un message clair. Réglez le plafond dans Réglages › Cerveau & coûts.

### « « … » ne lit pas les images »

Le connecteur choisi ne sait pas lire les images jointes : choisissez Claude, une API (Anthropic, OpenAI, Gemini…) ou Ollama avec un modèle de vision (`[connecteurs.ollama] modele_vision`).

## Stockage, Docker, PostgreSQL

### Docker n'est pas installé

Ce n'est pas nécessaire : le stockage par défaut est un fichier SQLite. Docker ne sert qu'à PostgreSQL (option) et à ce qui s'appuie dessus :

- le stockage `JARVIS2_STOCKAGE=postgres` (`docker compose up -d`) ;
- `jarvis2 sauvegarde` avec PostgreSQL, qui passe par `docker exec` dans le conteneur `jarvis2-postgres` (sinon : « pg_dump impossible : … ») ;
- l'import depuis JARVIS v1 : « L'import jarvis_v1 passe par une base d'attente PostgreSQL : lancez-le avec JARVIS2_STOCKAGE=postgres, puis copiez les données vers SQLite avec `jarvis2 stockage copier` si vous le souhaitez. »

### « Mot de passe de la base absent : créer .env (python infra/creer_env.py) »

PostgreSQL est demandé mais `.env` n'a pas de mot de passe. Créez-le : `uv run --python 3.13 infra/creer_env.py` (mots de passe aléatoires, jamais affichés ; un `.env` existant n'est jamais remplacé). `docker compose` s'arrête de même sur « POSTGRES_USER manquant dans .env ».

### PostgreSQL refuse de démarrer (`initdb: could not change permissions`)

PostgreSQL exige des droits Unix sur son dossier de données, qu'un dossier monté depuis exFAT ou Windows ne fournit pas. Gardez le volume Docker nommé `jarvis2_pg` de `docker-compose.yml` ; pour changer de disque, déplacez le disque virtuel de Docker Desktop.

### « schéma …, … attendu »

La base n'est pas à jour. SQLite se migre seul au démarrage (ou `jarvis2 docteur --reparer`) ; PostgreSQL : `jarvis2 migrer`.

## Mémoire et modèles

### « Mémoire (modèle d'embeddings) : à télécharger »

Rien n'est téléchargé sans votre accord. Lancez `jarvis2 docteur --reparer`, ou le bouton du diagnostic. Un téléchargement interrompu reprend où il en était (« téléchargement interrompu à … (reprise possible) »).

### La dictée ne transcrit pas

Le modèle Whisper est facultatif et n'est téléchargé que sur accord (diagnostic, ligne « Dictée (modèle Whisper) »). Le choix du modèle se fait par `JARVIS2_MODELE_VOIX` ; `jarvis2 materiel` en conseille un selon votre mémoire vive. Pour mesurer chaque étape de la voix : `jarvis2 docteur --latence`.

## Sécurité

### « Arrêt d'urgence actif : aucune écriture n'est acceptée » (HTTP 423)

Quelqu'un a déclenché l'arrêt d'urgence : toute écriture est refusée, sauf ce qui sert à le lever ou à retirer un accès. Le lever est une action 🔴 : il faut approuver la demande avec une clé d'accès.

Clé d'accès perdue : sur le PC, `jarvis2 lever-urgence` (avec PostgreSQL, il exige les identifiants du propriétaire de la base du `.env` ; avec SQLite, l'accès au fichier de la base). C'est journalisé 🔴. Il répond « Arrêt d'urgence levé (journalisé). Redémarrez le Core pour qu'il le prenne en compte. » : redémarrez le Core.

### « ALTÉRATION du journal d'audit détectée à l'entrée … »

`jarvis2 verifier-audit` (ou le diagnostic, ligne « Journal d'audit ») a trouvé une entrée dont l'empreinte ne correspond plus : le journal a été modifié en dehors de JARVIS. JARVIS détecte, il ne répare pas : conservez la base telle quelle, comparez avec une sauvegarde vérifiée, et considérez le PC comme compromis tant que la cause n'est pas connue.

### Une action est refusée par la « Barrière d'injection »

Pendant ce tour, JARVIS a lu du contenu externe (page web, capture, fichier, partage reçu, outil MCP…) : les actions qui agissent sont refusées jusqu'à la fin du tour. Relancez l'action vous-même depuis l'interface : un clic de l'utilisateur n'est jamais bloqué. Voir [SECURITE.md](SECURITE.md#barrière-dinjection-par-tour).

### Mode sans écran : « Indisponible en mode sans écran : ce Core tourne sur un serveur sans écran »

Le Core a été lancé avec `--sans-ecran` (ou `JARVIS2_SANS_ECRAN=true`) : capture, clics et contrôle de l'écran sont refusés par le Core. À l'inverse, sur un serveur Linux sans session graphique lancé sans ce mode, le diagnostic signale « Aucune session graphique détectée (ni DISPLAY ni WAYLAND_DISPLAY) ».

## Sauvegarde

- « Indiquez --dossier (disque externe, dossier synchronisé hors du PC…) » : `jarvis2 sauvegarde creer` exige un dossier de destination.
- « Phrase de passe trop courte (12 caractères au moins) ».
- « Phrase de passe incorrecte ou sauvegarde altérée » : sans la bonne phrase, la sauvegarde est illisible ; personne ne peut la retrouver pour vous.
