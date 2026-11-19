[English](README.md) | Français

# JARVIS 2

Assistant personnel local d'abord : mémoire à long terme, conversation en flux avec les IA de votre choix, interface HUD, et rien d'irréversible ni d'externe sans votre accord.

[![CI](https://github.com/1AngelMicka/jarvis-os/actions/workflows/ci.yml/badge.svg)](https://github.com/1AngelMicka/jarvis-os/actions/workflows/ci.yml)
[![Licence : Apache 2.0](https://img.shields.io/badge/licence-Apache%202.0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/github/v/tag/1AngelMicka/jarvis-os?sort=semver&label=version)](https://github.com/1AngelMicka/jarvis-os/tags)

## Installer

Windows (PowerShell) :

```powershell
irm https://raw.githubusercontent.com/1AngelMicka/jarvis-os/main/install.ps1 | iex
```

macOS, Linux :

```sh
curl -LsSf https://raw.githubusercontent.com/1AngelMicka/jarvis-os/main/install.sh | sh -s --
```

Sans Docker ni Node. Détails et options [plus bas](#détails-de-linstallation) et dans [docs/INSTALLATION.md](docs/INSTALLATION.md) ; en cas de problème : [docs/DEPANNAGE.md](docs/DEPANNAGE.md).

> **Statut : en développement (0.8.0).** Les phases 1 à 10 et 13 du plan sont faites (socle, dialogue, mémoire, sécurité, connecteurs d'IA, installation, agents, mémoire v2, ateliers Claude Code, voix et vision, toutes les capacités de JARVIS v1) ; la phase 14 est presque terminée. L'application de bureau et ses installeurs sont construits par GitHub Actions, pas encore signés ; la sauvegarde chiffrée est prête. L'interface existe en français et en anglais (écrans principaux ; quelques vues avancées restent en français).

## Captures

<!-- Images à fournir : docs/images/demo.gif, docs/images/theme-*.png (une par thème), docs/images/mobile.png. Elles ne sont pas encore dans le dépôt. -->

- [Démonstration (GIF)](docs/images/demo.gif)
- Thèmes : [JARVIS](docs/images/theme-jarvis.png) · [Studio nocturne](docs/images/theme-studio.png) · [Atelier clair](docs/images/theme-atelier.png) · [Console épurée](docs/images/theme-console.png) · [Présence](docs/images/theme-presence.png)
- [Sur téléphone](docs/images/mobile.png)

## Ce que fait JARVIS 2

**Conversation avec l'IA de votre choix**
- Réponses en flux, historique conservé, titre et résumé daté de chaque conversation.
- Connecteurs : vos comptes par les programmes officiels (Claude Code, OpenAI Codex, Google Antigravity avec avertissement), vos clés d'API (Anthropic, OpenAI, Gemini, OpenRouter, tout service compatible OpenAI), vos modèles locaux (Ollama, LM Studio, llama.cpp, vLLM).
- Routeur par type de tâche (code, raisonnement, rapide, privé) par un classifieur local, chaque route notée sur des mesures réelles et rétrogradée si elle échoue ; une route privée ne part jamais vers une IA externe.
- Routeur automatique et conseil multi-IA : plusieurs connecteurs répondent en parallèle, puis l'un d'eux fait la synthèse.
- Coûts par connecteur (jour, mois), plafonds, jauges d'abonnement Claude Code ; chaque réponse indique le moteur qui l'a donnée.

**Mémoire**
- Mémoire à long terme avec recherche hybride, blocs de mémoire éditables toujours donnés au modèle, et trois niveaux de confidentialité (public, semi-privé, privé).
- Consolidation nocturne par une IA **locale**, oubli par archivage, détection déterministe d'un changement d'avis (l'ancien fait est remplacé), versions et export.
- Une porte de rappel sans LLM décide si un message a besoin de la mémoire.
- Connaissances par domaine (carte conceptuelle, fiches, questions de contrôle), profil guidé par questionnaire, chantiers suivis sans doublon.
- Import depuis JARVIS v1 (lecture seule).

**Agents et ateliers**
- Recettes planifiées, missions de fond (recherche avec sources web et scientifiques citées, brainstorm, revue) dont le rapport va en mémoire.
- Outils MCP (sessions persistantes) et skills `SKILL.md` importés : inutilisables tant que vous ne les avez pas revus, capacités dangereuses (shell, réseau, écriture) bloquées tant qu'elles ne sont pas cochées, empreinte du dossier vérifiée à chaque usage. À chaque tour, moins de 12 outils sont proposés au modèle, choisis par le sens.
- Ateliers Claude Code : chacun travaille dans son propre worktree git et sa branche, et JARVIS décide de chaque outil demandé ; pause, reprise, clôture.
- Veille en lecture seule de vos propres sessions Claude Code.
- Amélioration continue : une suggestion devient un atelier, puis un aperçu testé, puis une demande de mise en service que vous validez, avec retour possible.

**Voix et vision**
- Transcription locale (Whisper int8, VAD Silero, filtres d'hallucinations, disjoncteur), éveil « Dis Jarvis » en deux étages (le second est un juge d'intention local), coupure quand on parle par-dessus, détection de fin de tour, dictée globale par raccourci maintenu dans l'application de bureau.
- Reconnaissance du propriétaire à la voix (désactivée par défaut).
- Lecture à voix haute : voix du navigateur, Piper (voix neuronale locale) ou ElevenLabs (en ligne, avec votre clé).
- Écran ou image décrits seulement sur demande, OCR d'abord.

**Votre PC et la maison**
- Contrôle du PC sous Windows : volume, luminosité, fenêtres, média, verrouillage, extinction, plan d'alimentation, bannières de notification et thème sombre, mode jeu ; CPU, RAM, GPU et VRAM en direct.
- Connecteurs maison facultatifs, désactivés par défaut : Philips Hue (API locale du pont), OBS Studio, et Home Assistant sur votre réseau local (🟡 lumières, prises, média ; 🔴 serrures, alarme, portail, qui demandent votre clé d'accès et votre voix reconnue). Voir [docs/HOME_ASSISTANT.md](docs/HOME_ASSISTANT.md).
- Serveur Wyoming : la transcription et la voix de JARVIS offertes à Home Assistant et à des satellites vocaux dans les pièces (une clé par appareil, seul l'audio après le mot d'éveil, présence par pièce, plafonds de volume, profils par personne).
- Commandes rapides sans IA : une phrase reconnue déclenche une action déclarée, modifiable par vous.

**Sécurité**
- Niveaux de permission : 🟢 lecture (libre), 🟡 modification (vous validez ; « toujours autoriser » possible), 🔴 destruction, argent, publication, envoi (confirmation explicite, par clé d'accès).
- Approbation liée au plan exact affiché (empreinte SHA-256, revérifiée juste avant d'exécuter) et pile d'annulation : une action réversible reste annulable 24 heures.
- Journal d'audit en ajout seul, chaîné par empreintes SHA-256, arrêt d'urgence, coffre local des clés d'API, filtre des secrets et données personnelles sur tout ce qui part vers un fournisseur externe.
- Barrière d'injection par tour (après une lecture de contenu non fiable, plus aucune action dans ce tour) et détecteur de réponses qui affirment une action jamais faite.
- Une page « Où partent mes données » générée depuis votre configuration réelle (voir plus bas).

**Partout**
- Téléphone : application web installable, notifications Web Push, « Partager vers JARVIS », accès par Tailscale.
- Application de bureau (fenêtre propre, zone de notification, liens `jarvis://`), mode serveur sans écran, accueil du matin avec la météo, pages générées ouvertes dans un bac à sable, cinq thèmes, widgets du HUD générés à la demande (météo, minuteur, liste…) validés par listes fermées, jamais affichés bruts, et épinglables.
- Sauvegarde chiffrée vérifiée par une vraie restauration ; SQLite par défaut, PostgreSQL + pgvector au choix.

## Ce qui tourne en local / ce qui sort

La page « Où partent mes données » de l'interface construit cette carte depuis **votre** configuration et montre ce qui est actif. Résumé des règles du code :

| Fonction | Où | Ce qui part | Quand |
|---|---|---|---|
| Mémoire (stockage, embeddings, recherche) | 🟢 Votre PC | Rien | Toujours en local |
| Dictée, mains libres, éveil | 🟢 Votre PC | Rien (Whisper et le juge d'intention tournent en local) | Toujours en local |
| Lecture à voix haute | 🟢 Votre PC | Rien (voix du navigateur ou Piper) | Par défaut |
| Interface | 🟢 Votre PC | Rien : aucune police, aucun script, aucune image externes | Toujours |
| IA locale (Ollama, LM Studio, llama.cpp, vLLM) | 🟢 Votre PC, ou 🟡 votre réseau, selon l'adresse déclarée | Vos messages, seulement quand vous lui écrivez | Quand vous l'utilisez |
| Écran décrit | Modèle de vision Ollama (votre PC par défaut) | Une capture de l'écran à chaque demande | Seulement par le bouton « Écran » |
| Connecteurs d'IA en ligne (Claude Code, Codex, Antigravity, Anthropic, OpenAI, Gemini, OpenRouter, points d'accès déclarés) | 🔴 Internet | Vos messages et l'historique récent, les consignes de JARVIS et la mémoire utile au message, titres, résumés, conseil et missions qui passent par cette IA ; images jointes (accord séparé demandé d'abord pour certains connecteurs) ; pour les ateliers Claude Code, le code des projets ouverts aux ateliers | Seulement les connecteurs activés, installés et munis de leur clé (s'il en faut une). **Jamais** : les souvenirs privés et les réponses bâties dessus ; secrets et données personnelles masqués avant l'envoi |
| Recherche web (votre instance SearXNG) | 🔴 Internet, par les moteurs qu'elle interroge | Les requêtes des missions, jamais pour un sujet privé | Seulement si vous avez déclaré une instance |
| Sources scientifiques (OpenAlex, arXiv, PubMed, Europe PMC) | 🔴 Internet | Les requêtes des missions, jamais pour un sujet privé | Missions de recherche ; `scientifique = false` les coupe |
| Météo du matin (Open-Meteo, sans compte) | 🔴 Internet | Coordonnées de la maison arrondies à environ 1 km ; le nom de la ville une seule fois, pour les trouver | Seulement si vous avez choisi un lieu |
| Voix ElevenLabs | 🔴 Internet | Le texte de chaque phrase lue, secrets et données personnelles masqués ; une phrase sur un sujet privé est lue par une voix locale | Seulement avec votre clé et si vous avez choisi cette voix |
| Téléchargement des modèles (Hugging Face, fichiers publics) | 🔴 Internet | Seulement la demande des fichiers (votre adresse IP, comme pour tout téléchargement) | Seulement sur votre clic « Télécharger » |
| Téléphone par Tailscale | 🟡 Votre réseau privé | Tout l'échange téléphone–PC, chiffré de bout en bout ; Tailscale ne voit que la liste de vos appareils | Seulement si vous avez lancé `tailscale serve` |
| Core ouvert au réseau local | 🟡 Votre réseau | Les échanges des appareils jumelés (un jeton par appareil) | Seulement avec `JARVIS2_OUVERTURE_RESEAU` |
| Outils MCP | Selon le programme (il peut lui-même contacter Internet) | Les paramètres de chaque appel d'outil, après votre accord 🟡 | Seulement les serveurs déclarés et activés |
| Home Assistant | 🟡 Votre réseau (une adresse Internet est refusée) | Les commandes que vous approuvez (entité visée et service) et les lectures d'état ; jamais vos conversations, votre mémoire ni vos fichiers, ni le code de l'alarme sauf pour la désarmer | Seulement si vous l'avez activé et configuré |
| Serveur Wyoming (Home Assistant, satellites vocaux) | 🟢 Votre PC, ou 🟡 votre réseau si vous choisissez une autre adresse | Le texte transcrit et la voix de JARVIS, renvoyés seulement à l'appareil qui a parlé ; l'audio d'avant le mot d'éveil est jeté sans être lu, audio et texte jamais gardés | Seulement si vous l'avez activé |

Niveaux des souvenirs, vers une IA externe :

| Niveau | Envoyé à une IA externe |
|---|---|
| Public | Partout : noyau, blocs, nouveautés, souvenirs trouvés pertinents |
| Semi-privé | Seulement s'il est trouvé pertinent pour le message |
| Privé (`local_uniquement`) | Jamais : reste sur votre PC |

Dans tous les cas, les sujets exclus sont retirés et les secrets masqués d'abord. Les mesures de chaque appel (latence, jetons, coût) restent dans votre base locale ; il n'y a pas de télémétrie.

## Matériel

JARVIS 2 fonctionne sous Windows, macOS et Linux (le contrôle du PC est réservé à Windows). `jarvis2 materiel` montre ce qui est détecté et les modèles conseillés ; la commande est en lecture seule et n'installe, ne télécharge ni ne démarre rien.

**Sans carte graphique, ou sans aucun modèle local** : tout fonctionne avec un connecteur en ligne ou votre abonnement Claude Code. La mémoire (embeddings) tourne de toute façon sur le processeur, et la transcription s'y replie ; les modèles locaux de conversation tournent alors aussi sur le processeur, lentement, plafonnés au palier 7 à 9 milliards de paramètres.

**Détection** : RAM par le système ; NVIDIA par `nvidia-smi` ; AMD par `rocm-smi`, sinon le registre Windows ou `/sys/class/drm` sous Linux ; Apple Silicon (mémoire unifiée, Metal) ; cartes Intel par Vulkan. Sous 4 Go de VRAM (cartes intégrées), la carte est ignorée et le processeur est utilisé.

**AMD** : les cartes prises en charge par ROCm (Radeon RX 6800 et plus, RX 7000, RX 9000, Radeon Pro W6800 / W7000, Instinct) passent par ROCm ; les autres cartes AMD passent par Vulkan, expérimental dans Ollama. Pour la transcription, une carte AMD est utilisée si la version installée de CTranslate2 prend ROCm en charge ; sinon Whisper tourne sur le processeur. Rien ne suppose une carte NVIDIA.

**Comment un modèle est conseillé** : la mémoire utile est la VRAM de la carte (avec accélération et au moins 4 Go), 70 % de la mémoire unifiée sur Apple Silicon, ou à défaut la moitié de la RAM. JARVIS prend le plus gros palier qui tient, puis descend **d'un palier** pour garder de la marge (contexte long, autres programmes) ; le maximum est donné à titre indicatif.

| Usage | Mémoire nécessaire (quantification 4 bits, contexte compris) → taille, modèle conseillé |
|---|---|
| Conversation (Ollama) | 3 Go → 1 à 2 milliards `qwen3.5:2b` · 5 Go → 3 à 4 milliards `qwen3.5:4b` · 8 Go → 7 à 9 milliards `qwen3.5:9b` · 11 Go → 12 à 14 milliards `gemma4:12b` · 21 Go → 24 à 32 milliards `qwen3.5:27b` · 44 Go → 70 milliards `llama3.3:70b` |
| Vision (Ollama) | 3 Go → 2 milliards `qwen3.5:2b` · 8 Go → 7 milliards `qwen2.5vl:7b` · 22 Go → 32 milliards `qwen2.5vl:32b` (sur processeur : 2 milliards au plus) |
| Mémoire, embeddings (RAM, processeur) | 2 Go → MiniLM multilingue, 384 dimensions (par défaut, environ 220 Mo téléchargés une fois) · 8 Go → `BAAI/bge-m3` |
| Transcription, Whisper (RAM) | 2 Go → tiny · 4 Go → base · 8 Go → small · 16 Go → medium · 32 Go → large-v3 |

Les noms de modèles sont des exemples à vérifier dans le catalogue d'Ollama. Ollama n'est jamais démarré automatiquement : le script d'installation le propose seulement (case décochée par défaut), et JARVIS ne le lance que sur votre demande explicite et n'arrête que l'Ollama qu'il a lancé.

## Comparaison

JARVIS 2 s'inspire de plusieurs projets d'assistants personnels. **Aucun n'est installé ni requis** : chaque idée retenue est réimplémentée, et du code n'est repris que de projets sous licence permissive, signalé dans [NOTICE](NOTICE). Le tableau dit ce que JARVIS 2 reprend de chacun et si c'est en place dans le code aujourd'hui ; ce qui ne l'est pas encore est au [plan](docs/PLAN.md). Liste complète et licences : [docs/INSPIRATIONS.md](docs/INSPIRATIONS.md).

| Projet | Licence | Ce que JARVIS 2 en reprend | État |
|---|---|---|---|
| OpenJarvis | Apache-2.0 | Reprise de l'installation après coupure et une seule table matériel → modèle ; jauges d'abonnement et pied de réponse ; skills avec confiance et confinement ; masquage étendu des secrets, niveaux de confidentialité, porte de rappel (idées, réimplémentées) ; préréglages à l'installation | En place |
| TopMyster/jarvis | MIT | Point d'entrée pipx | En place |
| ASDprogrammer521/jarvis | MIT | Barrière d'injection par tour, approbation liée au plan exact, pile d'annulation ; contrôle du PC et modes qui changent vraiment Windows | En place |
| lancejames221b/jarvis | MIT | Relance sans mot d'éveil, états actif / veille ; reconnaissance du propriétaire, fermée pour 🟡🔴 si indisponible | En place |
| akshayaggarwal99/jarvis | MIT | Transcription robuste ; dictée globale sous Windows | En place |
| sosoj92/jarvis | MIT | Filtre des hallucinations françaises ; « toujours autoriser » pour 🟡, jamais de 🔴 à distance sans clé | En place |
| b1-loop | MIT | Coupure quand on parle par-dessus ; latence mesurée étape par étape | En place |
| microsoft/JARVIS (HuggingGPT) | MIT | Brainstorm → spec → plan → exécution ; missions en graphe | En partie : missions brainstorm ; spec → plan → exécution et graphe de missions prévus |
| DonJyde/jarvis | MIT | Widgets générés filtrés | En place |
| livekit-rtc | Apache-2.0 | Annulation d'écho (dépendance possible) | En place, si le paquet facultatif `livekit` est installé |
| Dodaios | Apache-2.0 | Fin de tour, transcription anticipée (idée) | En place |
| isair/jarvis | Non commerciale | Éveil en deux étages (idée seulement) | En place |
| NeyorDEV/jarvis | GPL | MCP persistant, outils choisis par sens (idée seulement) | En place |
| amanimran786/jarvis-ai | AGPL | Ateliers en bac à sable réel (repris à l'inverse : refus si indisponible) | Fait (conteneur sans réseau, Windows Sandbox, bubblewrap, sandbox-exec ; pas encore essayé en vrai) |
| Jarvis.sh | Sans licence claire | Commandes rapides sans LLM (idée seulement, sans `eval`) | En place |
| jarvis799 | Sans licence claire | Actions vérifiées en relisant l'état (idée seulement) | En place (réglages du PC relus) |
| hasibjaan | Sans licence claire | HUD séparé du fil audio (idée seulement) | En place (thème Présence) |

Ce sur quoi JARVIS 2 met l'accent : le local d'abord, vos propres comptes par les programmes officiels des fournisseurs, les permissions et l'audit construits avant de donner des accès, et une carte des flux générée depuis la configuration réelle.

## Détails de l'installation

Les commandes d'une ligne ci-dessus récupèrent le script de ce dépôt ; par défaut, il installe la dernière version publiée. Avec une roue locale :

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 --source <jarvis2-x.y.z-py3-none-any.whl>
```

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
- [Tailscale](https://tailscale.com/download) pour le téléphone (voir plus bas).

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

## Importer des données

Depuis JARVIS v1 (sauvegarde `pg_dump -Fc`, stockage PostgreSQL) : voir [docs/DECISIONS.md](docs/DECISIONS.md#imports--sources-génériques-lecture-seule-exclusions-locales), puis `jarvis2 stockage copier --vers sqlite` si vous voulez passer à SQLite.

## Comptes d'IA et conditions des fournisseurs

JARVIS n'est affilié à aucun fournisseur d'IA. Avec un compte (plutôt qu'une clé d'API), il appelle le **programme officiel** du fournisseur, installé et connecté par vous, sans le modifier, et ne lit jamais vos identifiants. Votre usage reste soumis aux conditions de chaque fournisseur :

- **Claude Code** (abonnement Claude) : abonnement personnel, pour votre propre usage, pas d'usage commercial ni pour d'autres personnes. L'avertissement est à cocher une fois.
- **OpenAI Codex** (compte ChatGPT) : selon les conditions d'OpenAI.
- **Google Antigravity** : ses conditions interdisent l'accès par un logiciel tiers et des comptes ont été suspendus pour cet usage. Ce connecteur est désactivé par défaut, porte un badge « risque » permanent, n'est jamais choisi automatiquement, et la clé d'API Gemini est recommandée à la place.

En cas de doute, une clé d'API (facturée à l'usage) ou un modèle local est toujours possible.

## Développement

Prérequis : [uv](https://docs.astral.sh/uv/), Node 22+ (interface). Docker seulement pour PostgreSQL.

```powershell
cd core; uv sync; uv run python -m jarvis2 serveur   # Core (SQLite par défaut) : http://127.0.0.1:8765
cd interface; npm install; npm run dev                # interface de développement : http://127.0.0.1:5174
```

Avec PostgreSQL : `uv run --python 3.13 infra/creer_env.py` (`.env` avec mots de passe générés), `docker compose up -d`, `cd core; uv run python -m jarvis2 migrer`.

Pour servir l'interface compilée par le Core : `npm run build` dans `interface`, puis ouvrir **http://localhost:8765** (le nom `localhost`, pas l'adresse IP : les clés d'accès l'exigent). Construire le paquet installable : `npm run build` puis `cd core; uv build --wheel` (l'interface est incluse dans la roue ; sans interface compilée, la roue est construite sans elle, avec un avertissement, et le Core affiche une page d'explication). Installer directement le dépôt : `pipx install --python 3.13 ./core` après `npm run build`.

Vérifier :

```powershell
cd core; uv run pytest; uv run ruff check .; uv run mypy   # tests sur SQLite, et sur PostgreSQL si Docker tourne
cd interface; npm run verifier
```

Commentaires de code, documentation et messages de commit sont en français. Contribuer : [CONTRIBUTING.md](CONTRIBUTING.md) · [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Documentation

- [Installation](docs/INSTALLATION.md) · [Dépannage](docs/DEPANNAGE.md) · [FAQ](docs/FAQ.md)
- [Architecture](docs/ARCHITECTURE.md) · [Sécurité et permissions](docs/SECURITE.md) · [Écrire un skill, une commande ou une recette](docs/EXTENSIONS.md) · [Serveur domestique](docs/SERVEUR.md) · [Home Assistant et satellites](docs/HOME_ASSISTANT.md)
- [Feuille de route](docs/FEUILLE_DE_ROUTE.md) · [Plan](docs/PLAN.md) · [Décisions](docs/DECISIONS.md) · [Inspirations](docs/INSPIRATIONS.md) · [Design de l'interface](interface/DESIGN.md)
- [Journal des versions](CHANGELOG.md) · [Signaler une vulnérabilité](SECURITY.md)

## Licence

[Apache 2.0](LICENSE). Mentions des tiers : [NOTICE](NOTICE).
