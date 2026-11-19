# Questions fréquentes

## Généralités

### Qu'est-ce que JARVIS 2 ?

Un assistant personnel open source, **local d'abord** : il garde votre mémoire à long terme sur votre PC, converse avec l'IA de votre choix (votre abonnement Claude par Claude Code, une clé d'API, ou un modèle local) et agit seulement sous votre contrôle. Il se pilote depuis le navigateur du PC, l'application de bureau ou le téléphone. Architecture : [ARCHITECTURE.md](ARCHITECTURE.md).

### Sur quels systèmes fonctionne-t-il ?

Windows, macOS et Linux, avec les scripts [`install.ps1`](../install.ps1) et [`install.sh`](../install.sh) : voir [INSTALLATION.md](INSTALLATION.md). Le **contrôle du PC** (volume, luminosité, fenêtres, modes, verrouillage, extinction) n'est implémenté que pour Windows. Un serveur domestique sans écran est aussi possible : [SERVEUR.md](SERVEUR.md).

### Faut-il Docker, Node ou un Python particulier ?

Non. Le stockage par défaut est un fichier SQLite, l'interface est précompilée dans le paquet, et uv fournit Python 3.13. Docker ne sert qu'au stockage PostgreSQL (option) ; Node seulement pour développer l'interface.

### Est-ce gratuit ?

JARVIS est distribué sous licence **Apache 2.0** ([LICENSE](../LICENSE), [NOTICE](../NOTICE)). Seuls les services d'IA que vous choisissez peuvent coûter : votre abonnement Claude, ou les clés d'API facturées à l'usage. La vue **Coûts** suit les dépenses par connecteur, et chaque connecteur payant peut recevoir un plafond mensuel ; Ollama et les serveurs locaux ne coûtent rien.

### JARVIS est-il lié à un fournisseur d'IA ?

Non. Il n'est affilié à aucun fournisseur. Avec un compte, il appelle le programme officiel du fournisseur, installé et connecté par vous ; votre usage reste soumis aux conditions de chaque fournisseur.

## Local d'abord et vie privée

### Qu'est-ce qui tourne sur mon PC ?

Le Core et son API (qui n'écoute que sur `127.0.0.1`), la base (SQLite ou PostgreSQL local), la mémoire et sa recherche (embeddings calculés localement), la transcription de la voix (Whisper), la description des captures d'écran (OCR puis modèle de vision local), la consolidation nocturne de la mémoire (IA locale uniquement), et les modèles locaux si vous en utilisez (Ollama, LM Studio, llama.cpp, vLLM).

### Quelles données sortent de mon PC ?

Seulement ce que vous activez :

- le contexte d'un message envoyé à une **IA externe** (Claude Code, Codex, API Anthropic, OpenAI, Gemini, OpenRouter…), après filtrage : souvenirs privés exclus, secrets et données personnelles masqués ;
- les requêtes de recherche des missions vers votre instance **SearXNG** et, sauf `scientifique = false`, vers OpenAlex, arXiv, PubMed et Europe PMC (jamais pour un sujet privé) ;
- la météo de l'accueil du matin (Open-Meteo), si vous indiquez un lieu ;
- les **téléchargements de modèles** (embeddings, Whisper, voix Piper), toujours sur votre accord ;
- la voix ElevenLabs, si vous y mettez votre clé (une phrase privée est lue par une voix locale) ;
- les notifications vers le téléphone, chiffrées de bout en bout, au contenu générique.

La page **Où partent mes données** (Réglages › Sécurité) est générée depuis votre configuration réelle et dit, pour chaque fonction, ce qui part, ce qui ne part jamais et où la désactiver. Détails : [SECURITE.md](SECURITE.md#ce-qui-ne-part-jamais-vers-un-moteur-externe).

### Comment garder un souvenir uniquement sur mon PC ?

Passez-le au niveau **Privé** dans la vue Mémoire : un souvenir privé (`local_uniquement`) ne part jamais vers une IA externe. Pour un thème entier, listez-le dans `[confidentialite] sujets_prives` de `config.toml` : un message qui le nomme n'est confié qu'à une IA locale, et refusé s'il n'y en a aucune. `sujets_exclus` retire en plus ces sujets de toute mémoire injectée, quelle que soit l'IA.

### JARVIS est-il accessible depuis Internet ?

Non, par défaut. Le Core n'écoute que sur le PC ; pour le téléphone, l'accès passe par votre réseau privé Tailscale (`tailscale serve`, jamais `tailscale funnel`), et chaque appareil doit être jumelé.

## Les IA

### Puis-je utiliser mon abonnement Claude ?

Oui, par **Claude Code**, que vous installez et connectez **vous-même** à votre compte (`claude`, puis `/login`). JARVIS appelle ce programme officiel sans le modifier, ne propose jamais de connexion Claude.ai, ne lit ni ne stocke aucun identifiant, retire les clés d'API de l'environnement et refuse toute réponse qui ne vient pas de l'abonnement. Un avertissement est à lire et à cocher une fois : abonnement personnel, pour votre propre usage, pas d'usage commercial ni pour d'autres personnes. Si vous préférez une facturation à l'usage, utilisez le connecteur API Anthropic.

### Puis-je utiliser JARVIS sans aucun service en ligne ?

Oui, avec un modèle local : Ollama, ou un serveur compatible OpenAI (LM Studio, llama.cpp, vLLM). `jarvis2 materiel` conseille un modèle selon votre matériel ; vous le téléchargez vous-même (`ollama pull <modèle>`).

### Pourquoi JARVIS ne démarre-t-il pas Ollama ?

C'est une règle : **Ollama n'est jamais démarré automatiquement**. S'il est arrêté, il est signalé indisponible. Vous le lancez vous-même, ou vous demandez à JARVIS de le faire (Réglages › PC & mode jeu, action 🟡 approuvée par vous, jamais « toujours autorisée »). JARVIS n'arrête que l'Ollama qu'il a lui-même lancé.

### Et Google Antigravity ?

Le connecteur existe mais il est **désactivé par défaut**, porte un badge « risque » permanent et n'est jamais choisi par le routeur : les conditions d'Antigravity interdisent l'accès par un logiciel tiers, et des comptes ont été suspendus pour cet usage. La clé d'API Gemini est l'alternative recommandée.

### Qui choisit l'IA qui répond ?

Vous, si vous la choisissez (pour un message ou pour toute la conversation). Sinon le routeur, parmi les connecteurs actifs : jamais un connecteur « à risque », une IA locale seulement pour un sujet privé, une autre IA si un plafond de dépenses est atteint. Le **conseil multi-IA** peut aussi réunir plusieurs avis et en faire la synthèse.

## Matériel

### Quel matériel faut-il ?

Aucune carte graphique n'est nécessaire pour JARVIS lui-même : la mémoire et la transcription tournent sur le processeur. Il faut environ 220 Mo pour le modèle de la mémoire. Pour un modèle local, tout dépend de la mémoire disponible : `jarvis2 materiel` (lecture seule, rien n'est installé) donne le modèle conseillé par usage — conversation, vision, mémoire, transcription — en prenant un palier sous le maximum pour garder de la marge. Sans carte graphique utile, la conversation locale est plafonnée aux modèles de 7 à 9 milliards de paramètres.

### Les cartes graphiques AMD sont-elles prises en charge ?

Oui, dans la mesure de ce que permettent les outils sous-jacents :

- **Détection** : par `rocm-smi` s'il existe, sinon par le registre Windows ou `/sys/class/drm` sous Linux. Le suivi d'utilisation et de mémoire vidéo passe, sous Windows, par les compteurs du système (ceux du Gestionnaire des tâches), toutes marques comprises.
- **Modèles locaux (Ollama)** : les cartes prises en charge par ROCm (Radeon RX 6800 et plus, RX 7000, RX 9000, Radeon Pro W6800 / W7000, Instinct) sont comptées comme accélérées ; les autres cartes AMD passent par Vulkan, signalé « expérimental ».
- **Transcription (Whisper)** : ROCm n'est utilisé que si la version installée de CTranslate2 voit la carte ; sinon la transcription passe sur le processeur, avec la raison affichée.

NVIDIA (CUDA) et Apple Silicon (mémoire unifiée) sont aussi détectés.

## Utilisation

### JARVIS peut-il agir sans me demander ?

Seulement pour les actions 🟢 (lecture, protection). Une action 🟡 attend votre clic, une action 🔴 (suppression, extinction du PC, démarrer un direct…) votre **clé d'accès**. Après une lecture de contenu externe (page web, fichier, capture…), plus aucune action n'est possible jusqu'à la fin du tour. Le bouton **Arrêt d'urgence** coupe tout, tout de suite. Voir [SECURITE.md](SECURITE.md).

### Puis-je automatiser des choses ?

Oui : les **commandes rapides** (une phrase reconnue sans IA déclenche une action) et les **recettes** (une consigne planifiée, livrée dans une conversation ou rangée en mémoire). Format exact : [EXTENSIONS.md](EXTENSIONS.md).

### Y a-t-il des skills ou des plugins ?

Pas encore : les skills (format SKILL.md) sont prévus par le plan mais ne sont pas implémentés. Les serveurs MCP (stdio) sont déjà utilisables, outil par outil, chaque appel soumis à votre accord. Voir [EXTENSIONS.md](EXTENSIONS.md#skills) et la [feuille de route](FEUILLE_DE_ROUTE.md).

### Comment utiliser JARVIS depuis mon téléphone ?

Installez Tailscale sur le PC et le téléphone (même compte), lancez une fois `tailscale serve --bg 8765` sur le PC, puis associez le téléphone par le QR (assistant d'installation ou Réglages › Appareils). « Ajouter à l'écran d'accueil » l'installe comme une application.

### Où sont mes données, et comment les sauvegarder ?

La base, les journaux et les modèles sont dans le dossier des données (`%LOCALAPPDATA%\JARVIS2` ou `~/.local/share/jarvis2`) ; la configuration, le coffre des clés et les recettes dans le dossier de configuration (`%APPDATA%\JARVIS2` ou `~/.config/jarvis2`). `jarvis2 sauvegarde creer --dossier <hors du PC>` crée une sauvegarde chiffrée par votre phrase de passe ; `jarvis2 sauvegarde verifier` la restaure réellement dans une base temporaire pour la contrôler.

### Puis-je importer mes données d'une autre installation ?

Une seule source d'import existe aujourd'hui : **JARVIS v1** (`jarvis2 importer jarvis_v1 --sauvegarde <pg_dump>`), lue en lecture seule, avec des exclusions réglables dans `[import.jarvis_v1]` de `config.toml`. Elle passe par PostgreSQL (`JARVIS2_STOCKAGE=postgres`) ; vous pouvez ensuite copier vers SQLite (`jarvis2 stockage copier --vers sqlite`).

## Langue

### En quelle langue est JARVIS ?

L'interface, les messages, la documentation et le code sont **en français**. Le README existe en anglais ([README.md](../README.md)) et en français ([README.fr.md](../README.fr.md)). Une interface traduisible (anglais en plus du français) est prévue mais pas encore faite : voir la [feuille de route](FEUILLE_DE_ROUTE.md). Le mot d'éveil est « Jarvis » (« Dis Jarvis »), et la transcription filtre notamment les phrases parasites françaises de Whisper.

## Contribuer et signaler

### Comment contribuer ?

Voir [CONTRIBUTING.md](../CONTRIBUTING.md) et le [code de conduite](../CODE_OF_CONDUCT.md). Les changements sont listés dans [CHANGELOG.md](../CHANGELOG.md).

### J'ai trouvé une faille de sécurité

N'ouvrez pas d'issue publique : suivez [SECURITY.md](../SECURITY.md) (signalement privé).

### Ça ne marche pas

Commencez par `jarvis2 docteur`, puis [DEPANNAGE.md](DEPANNAGE.md).
