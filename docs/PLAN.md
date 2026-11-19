# JARVIS 2 — plan

> JARVIS 2 est un assistant personnel open source, local d'abord, que chacun peut installer : un **exocortex** qui garde la mémoire de son utilisateur, converse avec le modèle de son choix, agit sous son contrôle et se pilote depuis le PC comme depuis le téléphone. Le dépôt reste privé et sans remote tant que l'utilisateur n'a pas donné son accord explicite à la publication (phase 11). Licence pressentie : Apache-2.0, à confirmer à la publication.

Chaque phase est **utilisable seule** et se termine par des critères vérifiés. On ne passe à la suivante qu'avec l'accord de l'utilisateur.

## Principes

- **Code générique** : rien de personnel dans le dépôt. Chemins, adresses réseau, sujets exclus, données de tiers à écarter, noms de projets vivent dans la configuration locale de l'utilisateur (`%APPDATA%\JARVIS2\config.toml` ou `~/.config/jarvis2/config.toml`, modèle : `config.exemple.toml`) et dans `.env`, jamais versionnés.
- **Local d'abord** : l'API écoute sur 127.0.0.1 par défaut ; ouvrir l'accès est un choix explicite.
- **Rien d'irréversible ou d'externe sans validation humaine.** Contenu externe = donnée, jamais instruction.
- **Connecteurs d'IA interchangeables** : comptes par CLI officielle (Claude Code, OpenAI Codex, Google avec avertissement), clés d'API, modèles locaux (voir « Connecteurs d'IA »).
- Idées empruntées à d'autres projets : **idées et formats ouverts uniquement**, jamais de code sous licence incompatible.

## Claude par l'abonnement : cadre

- Le moteur `claude_code` appelle le binaire **Claude Code non modifié** de l'utilisateur, connecté par l'utilisateur lui-même (`claude /login`).
- JARVIS ne propose jamais de connexion Claude.ai, ne lit, ne stocke, ne relaie ni n'injecte aucun identifiant ou jeton d'abonnement, et ne modifie jamais le binaire. Il retire les clés d'API de l'environnement du sous-processus et refuse une réponse qui ne vient pas de l'abonnement.
- Accueil : détection de `claude --version` et de l'état de connexion, avertissement honnête (usage personnel et non commercial, lien vers les conditions, case cochée par l'utilisateur), alternatives proposées (clé API Anthropic, Ollama, fournisseurs compatibles OpenAI).
- Ni « Claude » ni son logo dans le nom du produit ; « fonctionne avec Claude Code » en texte simple est permis.

## Connecteurs d'IA : cadre

L'utilisateur branche les IA qu'il possède, comme des extensions : une page **Connecteurs**, une carte par fournisseur (état : détecté / connecté / disponible, bouton « Tester », modèles), bâtie sur le registre de moteurs existant. Trois familles :

1. **Comptes par CLI officielle** : le binaire officiel, installé et connecté par l'utilisateur lui-même, jamais modifié. JARVIS ne lit, ne copie ni ne stocke jamais les fichiers d'identifiants, ne propose jamais la connexion dans sa propre interface, n'exécute jamais ces CLI pour d'autres utilisateurs côté serveur. Chaque appel tourne dans un dossier de travail temporaire vide. L'accueil détecte le binaire et l'état de connexion, puis affiche un avertissement avec le lien vers les conditions d'utilisation.
   - **Claude Code** (abonnement Claude) : fait (`claude -p`, source d'authentification vérifiée).
   - **OpenAI Codex CLI** (compte ChatGPT) : `codex exec --json --sandbox read-only --skip-git-repo-check --ephemeral -m <modèle> "<prompt>"`, événements JSONL `thread.started`, `turn.*`, `item.*`, `error` ; le flux arrive élément par élément (pas jeton par jeton). Connexion par `codex login`, faite par l'utilisateur ; `~/.codex/auth.json` n'est jamais lu.
   - **Google (compte, Antigravity CLI)** — décision de l'utilisateur : « compte, avec avertissement ». **Désactivé par défaut** ; activable seulement après un avertissement explicite que l'utilisateur coche lui-même (rien de pré-coché) : les conditions d'Antigravity (section 6) interdisent « using third party software, tools, or services to access the Service », des comptes ont été suspendus (403 « ToS ») pour cet usage, l'utilisateur en porte le risque, et Google peut utiliser les échanges pour améliorer ses produits (désactivable dans ses réglages). Lien : https://antigravity.google/terms. La clé d'API Gemini est recommandée comme alternative sûre. Commande : `agy -p "<prompt>" --output-format stream-json --sandbox --model <slug>` dans un dossier temporaire vide ; jamais `--dangerously-skip-permissions`, aucune règle `permissions.allow` ; modèles par `agy models`. Connexion interactive unique par `agy`, faite par l'utilisateur ; les identifiants en cache ne sont jamais lus, copiés ni stockés. Badge « risque » permanent sur la carte tant qu'il est activé ; le routeur ne le choisit **jamais** automatiquement (sélection explicite, ou conseil si l'utilisateur l'y a ajouté).
   - Plus tard, après lecture de leurs conditions : GitHub Copilot CLI (`copilot -p … --output-format=json --no-ask-user`), Mistral Vibe.
2. **Clés d'API** : Anthropic, OpenAI, Google Gemini / Vertex, OpenRouter, et tout point d'accès compatible OpenAI. Clés dans le coffre local (hors dépôt, jamais dans les journaux), test en direct de la clé, coûts relevés par l'enveloppe de télémétrie.
3. **Modèles locaux** : Ollama (fait), serveurs compatibles OpenAI (LM Studio, serveur llama.cpp, vLLM), détection automatique, recommandation de modèles selon la RAM et la VRAM.

Le **routeur** choisit parmi les connecteurs disponibles (sauf ceux marqués « risque »), l'utilisateur peut imposer son choix par conversation ; le **conseil multi-IA** consulte tous les connecteurs que l'utilisateur y a mis. Le filtre secrets / données personnelles et l'exclusion des souvenirs privés s'appliquent à tout connecteur externe.

## Distribution (cible)

- Interface précompilée (`dist/`), servie par FastAPI : aucun Node à l'exécution, aucune compilation chez l'utilisateur.
- Python géré par uv (`requires-python >=3.12,<3.14`), jamais celui du PATH.
- Mode navigateur `jarvis serve --open` ; coque de bureau Tauri 2 (icône de notification, raccourcis globaux, mises à jour signées, backend embarqué construit en CI).
- Script d'installation en une ligne (`install.ps1` / `install.sh`) : uv puis `uv tool install`. Ollama détecté, jamais installé d'office ; modèles téléchargés en tâche de fond depuis l'interface (progression, annulation).
- Stockage derrière une seule interface : **SQLite + sqlite-vec** par défaut (zéro installation), **PostgreSQL + pgvector** en option, outil de migration entre les deux.
- `jarvis doctor --json` et assistant de premier lancement (vérifications avec boutons « Réparer », cerveau, mémoire, voix, téléphone).

## Téléphone (cible)

- PWA installable. Jumelage par QR affiché sur le PC : URL + jeton à usage unique (~5 min) échangé contre un jeton par appareil, révocable, liste des appareils.
- Accès à distance recommandé : Tailscale (`tailscale serve`, HTTPS). Cloudflare Tunnel + Access en option. Funnel désactivé par défaut.
- Clés d'accès (WebAuthn) pour approuver les actions sensibles. Application native (Capacitor) plus tard.

## Phases

### 1. Socle ✅
Structure, configuration (`.env.example`, jamais de secret dans git), PostgreSQL 16 + pgvector sous Docker, migrations, journalisation, tests.
**Terminé** : `docker compose up -d` sain, migrations idempotentes, rôle applicatif sans droit sur la structure (testé), pytest / ruff / mypy propres.

### 2. Parler à JARVIS ✅
Registre de moteurs (`generate` / `stream` / `list_models` / `health`), moteurs `claude_code` et `ollama`, télémétrie, dialogue en flux SSE avec historique, écran de chat HUD.
**Terminé** : réponse en flux depuis l'interface (abonnement vérifié), Ollama sélectionnable, un seul appel d'amorçage, console vide, 375 / 1280 / 1920 px sans débordement.

### 3. Souvenirs ✅
Importeur générique à sources (première source : `jarvis_v1`, depuis une sauvegarde `pg_dump`, lecture seule côté source), exclusions par la configuration locale, recherche hybride (vecteur + plein texte), noyau injecté, préparation du schéma de la mémoire v2 (modèle d'embedding par ligne, validité temporelle et remplacement sans DELETE, importance, accès, archivage, provenance, blocs éditables versionnés).
**Terminé** : chaque ligne de la source présente ou volontairement exclue (rapport), mêmes vecteurs et mêmes premiers résultats que la source sur des requêtes témoins, réponses appuyées sur les souvenirs, souvenirs privés jamais envoyés à un moteur externe.

### 4. Sécurité, appareils, approbations ✅
Permissions 🟢🟡🔴, file d'approbations, journal d'audit en ajout seul (rôle séparé du propriétaire), arrêt d'urgence, filtre secrets / données personnelles avant tout fournisseur externe, authentification, jetons par appareil, clés d'accès.
**Terminé quand** : une action 🔴 ne s'exécute qu'après approbation, le rôle applicatif ne peut ni modifier ni effacer l'audit (test), l'arrêt d'urgence coupe tout en moins d'une seconde, un secret factice n'atteint jamais un fournisseur externe (test).

### 5. Connecteurs d'IA ✅
Page Connecteurs et cartes par fournisseur ; connecteurs par CLI officielle (Claude Code fait, OpenAI Codex CLI, Google Antigravity CLI désactivé par défaut avec avertissement et badge « risque ») ; connecteurs par clé d'API (Anthropic, OpenAI, Gemini / Vertex, OpenRouter, compatible OpenAI) avec coffre local et coûts ; modèles locaux (Ollama, LM Studio, llama.cpp, vLLM) avec détection et recommandation selon le matériel ; routeur avec choix imposable par conversation ; conseil multi-IA sur les connecteurs choisis. Cadre : section « Connecteurs d'IA » ci-dessus.
**Terminé quand** : chaque famille a au moins un connecteur qui répond en flux depuis l'interface ; aucun fichier d'identifiants d'une CLI n'est lu (test) et aucune clé n'apparaît dans les journaux ni dans la base en clair (test) ; le connecteur Google ne s'active qu'après la case cochée par l'utilisateur et n'est jamais choisi par le routeur (test) ; un serveur local compatible OpenAI est détecté ; le conseil réunit au moins deux connecteurs et une synthèse.

### 6. Installation pour tous ✅ (reste à essayer par l'utilisateur : macOS, téléphone via Tailscale)
Mode navigateur (`jarvis2`), assistant de premier lancement, `jarvis2 docteur`, stockage SQLite + sqlite-vec par défaut et copie vers / depuis PostgreSQL, accueil du moteur Claude Code (avertissement coché, alternatives), jumelage du téléphone par QR (adresse Tailscale) + PWA, scripts `install.ps1` / `install.sh`.
**Terminé quand** : sur une machine vierge (Windows, macOS, Linux), le script d'installation mène à une conversation en moins de 10 minutes sans Docker ni Node, et un téléphone jumelé converse via Tailscale.
Fait : Windows (installation isolée depuis la roue, 7 min 30 s, conversation par Ollama dans l'interface), Linux (conteneur, 15 s, Core et interface servis). À faire par l'utilisateur : macOS ; `tailscale up` puis `tailscale serve --bg 8765` sur le PC, jumelage et conversation depuis le téléphone.

### 7. Agents ✅
Battement de cœur + planificateur + recettes YAML partageables (résultats livrés sur le canal choisi), compétences SKILL.md (format agentskills.io) créées après une tâche complexe, missions (recherche, brainstorm, revue), conseil multi-IA, client MCP (OAuth par utilisateur, interrupteur par outil) et serveur MCP (mémoire, missions), recherche web privée SearXNG avec sources citées, routeur local / externe.
**Terminé quand** : une recette planifiée livre son résultat, une mission produit un rapport sourcé rangé en mémoire, un sujet privé est routé vers un modèle local, un outil MCP est appelé sous approbation.
Fait : planificateur et recettes YAML (livraison conversation ou mémoire), missions recherche / brainstorm / revue rangées en mémoire (sources SearXNG citées, liste des sources construite par JARVIS), routeur local pour les sujets privés (motifs de la configuration ou souvenirs privés ; refus plutôt qu'une fuite si aucune IA locale), client MCP stdio (outil inactif par défaut, appel 🟡), vue Agents. Vérifié en vrai : recette livrée, mission rangée en mémoire, outil MCP appelé après approbation ; le rapport sourcé est testé avec un faux SearXNG (aucune instance ici). **Reporté** : compétences SKILL.md, serveur MCP de JARVIS, OAuth des serveurs MCP distants (seul le transport stdio est pris en charge), appel d'outils par le modèle lui-même.

### 8. Mémoire v2 ✅
Validité et remplacement exploités, blocs éditables (le noyau devient des blocs), consolidation nocturne sur un modèle local, entités légères, reclassement (bge-reranker-v2-m3) + RRF + récence et importance, oubli par archivage, faits / opinions avec confiance / épisodes, mémoire lisible en Markdown (SOUL.md, USER.md, MEMORY.md, journal du jour), banc d'évaluation de 50 à 100 questions, passage à `BAAI/bge-m3` (1024 dimensions, ré-encodage en tâche de fond, modèle stocké par ligne).
**Terminé quand** : le banc d'évaluation progresse face à la mémoire v1, la bascule de modèle d'embedding se fait sans interruption, aucun souvenir n'est effacé par la consolidation.
Fait : classement v2 (RRF + importance, récence) par défaut ; blocs éditables versionnés (privés possibles), conversion du noyau en blocs ; accès notés et oubli par archivage ; consolidation nocturne par une IA locale (doublons ignorés, rien d'effacé) ; export Markdown (MEMORY, USER, SOUL, journal) ; banc `jarvis2 memoire banc` (rappel@5, MRR, v1 contre v2) ; bascule de modèle sans interruption (`memoire_vecteurs`, la recherche change de modèle une fois tout encodé) ; section Mémoire de la vue Agents. Vérifié : banc synthétique (v2 > v1), bascule vers un modèle d'une autre dimension, consolidation sans effacement, export en vrai. Banc réel (50 questions écrites par un modèle local à partir de souvenirs tirés au hasard, hors dépôt), sur une copie de la base : modèle actuel rappel@5 = 0,48 (MRR 0,34) ; `BAAI/bge-m3` rappel@5 = 0,82 (MRR 0,68), ré-encodage de 1 408 souvenirs en 7 minutes sur le processeur. `BAAI/bge-m3` est ajouté par JARVIS au catalogue de fastembed (export ONNX officiel, 2,3 Go). Passage à `BAAI/bge-m3` fait sur l'installation réelle, après une sauvegarde vérifiée : bascule en tâche de fond en 6 minutes, sans interruption ; le Core passe d'environ 0,3 à 1,9 Go de mémoire vive. **Reporté** : reclasseur (cross-encoder), entités légères, types faits / opinions / épisodes avec confiance.

### 9. Ateliers Claude Code ✅
Sessions Claude Agent SDK sur les projets de l'utilisateur, **vraie isolation par worktree** git, approbations en ligne, pilotage (pause, reprise, arrêt), bac à sable Docker pour l'exécution de code.
**Terminé quand** : deux ateliers en parallèle sur un même projet travaillent chacun dans leur worktree, une écriture hors du worktree est refusée (test), la fusion passe par une approbation.
Fait : CLI `claude` officielle (abonnement vérifié, pas le SDK) dans un worktree par atelier (branche `jarvis/atelier-…`) ; chaque outil passe par l'outil d'autorisation de JARVIS (`--permission-prompt-tool`, serveur MCP `jarvis2 atelier-mcp`) : écriture hors du worktree refusée, commandes et accès extérieurs soumis en direct à l'utilisateur ; arrêt et reprise (session Claude Code) ; fusion 🟡 (commit puis `merge --no-ff`, projet propre exigé, conflit annulé) ; vue Ateliers. Vérifié : deux ateliers en parallèle et fusion approuvée (tests), et en vrai avec Claude Code — écriture dans l'atelier acceptée, écriture hors de l'atelier refusée. **Reporté** : pause sans arrêt (Claude Code n'en a pas : arrêt puis reprise), bac à sable Docker pour exécuter le code.

### 10. Voix, vision, créations ✅ (reste à essayer par l'utilisateur : l'échange vocal complet au micro)
Mot d'éveil, transcription (Whisper), synthèse vocale phrase par phrase pendant le flux, compatibilité Wyoming / Home Assistant, vision sur demande, créations en bac à sable, recommandation de modèles locaux selon le matériel.
**Terminé quand** : un échange vocal complet fonctionne mains libres, une capture d'écran n'est décrite que sur demande, une création s'ouvre dans un bac à sable isolé.
Fait : transcription locale faster-whisper (modèle « base » par défaut, `JARVIS2_MODELE_VOIX`) ; mot d'éveil « Jarvis » (variantes de transcription tolérées) ; mode mains libres (détection de la parole, « Jarvis » seul arme la phrase suivante, écoute coupée pendant que JARVIS parle) ; dictée ; lecture à voix haute phrase par phrase avec les voix locales du système ; « Écran » : capture choisie par l'utilisateur, décrite par un modèle de vision local (Ollama, `modele_vision`), rien de gardé ; créations HTML dans un bac à sable (CSP `sandbox`, aucune requête réseau, lien signé de 10 minutes, versions). Vérifié en vrai : « Jarvis, quelle heure est-il ? » (voix Windows) transcrit en 0,3 s avec éveil ; facture lue par qwen3.5:2b en 7 s ; création générée par Ollama, isolée (inaccessible depuis l'interface), affichée dans Chrome. **À essayer par l'utilisateur** : l'échange mains libres au micro (le navigateur intégré de l'application ne donne pas le micro). **Reporté** : Wyoming / Home Assistant ; affichage des créations dans le navigateur intégré de l'application Claude (il bloque les cadres isolés ; Chrome, Edge et le téléphone les affichent).

### 11. Application, installeurs, publication
Coque Tauri, installeurs .exe / .dmg / .deb / .AppImage par GitHub Actions, signature du code, documentation, licence. Publication du dépôt **uniquement avec l'accord explicite de l'utilisateur** (historique vérifié : aucune donnée personnelle).
**Terminé quand** : un installeur signé s'installe et se met à jour, la documentation permet une installation sans aide, l'utilisateur a validé la publication.
Fait : coque Tauri 2 (`app/`) : lance le Core s'il ne tourne pas, icône de notification, raccourci global (Ctrl+Maj+J, sinon Ctrl+Alt+J), instance unique, aucune API native pour l'interface ; `publication.yml` construit la roue et les installeurs Windows, macOS, Linux en version BROUILLON, signatures transmises seulement si configurées ; dépôt public validé par l'utilisateur. Vérifié en vrai : installeur Windows installé en silence, fenêtre « JARVIS 2 » reliée au Core. **À l'utilisateur** : certificats de signature (Windows, Apple) et clé de mise à jour Tauri dans les secrets du dépôt ; publication d'une version (étiquette `v*`) ; essai macOS.

### 12. Bascule de l'installation personnelle (outils prêts ; décisions à l'utilisateur)
Pour l'utilisateur qui vient de JARVIS v1 : sauvegarde hors site testée, rattrapage des souvenirs créés depuis l'import (`jarvis2 importer jarvis_v1`, rejouable), fonctionnement en parallèle, arrêt de JARVIS v1 **uniquement sur décision de l'utilisateur**.
**Terminé quand** : une restauration depuis la sauvegarde hors site a été testée, le rattrapage ne laisse aucun écart, l'utilisateur a décidé de la suite.
Fait : `jarvis2 sauvegarde creer --dossier <hors du PC>` (archive chiffrée AES-256-GCM, phrase de passe, base + configuration + recettes + manifeste, rotation des 7 dernières) et `jarvis2 sauvegarde verifier --fichier …` (restauration réelle dans une base temporaire, mêmes lignes, chaîne d'audit intacte). Vérifié sur l'installation réelle (PostgreSQL : 1 408 souvenirs, 151 conversations) : sauvegarde de 4,8 Mo restaurée et validée en 7 s. Rattrapage essayé sur une COPIE de la base réelle avec la dernière sauvegarde de JARVIS v1 : complet, aucun écart, rejouable sans doublon (aucun nouveau souvenir aujourd'hui : même sauvegarde que l'import du matin). **À l'utilisateur** : choisir le dossier hors site (disque externe, dossier synchronisé) et garder la phrase de passe ; lancer le rattrapage sur la vraie base quand JARVIS v1 a appris du nouveau ; décider de l'arrêt de JARVIS v1.

### 13. Tout JARVIS v1, en mieux
Reprendre chaque capacité de JARVIS v1 absente de la v2, en plus propre : mêmes garde-fous (🟢🟡🔴, arrêt d'urgence, audit), données personnelles dans la configuration locale, rien de propre à un utilisateur dans le dépôt. Lots, dans l'ordre :

- **A. Historique** : chercher, renommer, épingler, archiver, supprimer (🔴) ; titre écrit par l'IA après le premier échange ; résumé daté de chaque conversation en mémoire (privé : IA locale).
- **B. Mémoire visible** : vue Mémoire (recherche, filtres par origine, chronologie « Nouveautés »), « Nouveautés de ta mémoire » dans le contexte, notification « JARVIS a appris ».
- **C. Chantiers et activité** : tâches suivies avec progression, sans doublon, « C'est fait » ; panneau Activité en direct (missions, ateliers, chantiers).
- **D. Profil** : questionnaire guidé par sections, réponses en mémoire (privées : locales), entretien vocal.
- **E. Dialogue avancé** : images jointes (coller, glisser, trombone), palette Ctrl+K, commandes « / », raccourcis.
- **F. JARVIS pilote l'interface** : bloc d'actions validé par le Core (naviguer, ouvrir, proposer une mission…), lancements toujours proposés ; registre de règles de protection ; commandes rapides sans LLM éditables (motif avec jokers → action 🟢🟡🔴 seulement, jamais de shell, priorité réglable, phrase de test) ; « toujours autoriser » mémorisable pour une action 🟡 (jamais pour un clic à l'écran ou dans un navigateur), 🔴 jamais à distance sans clé d'accès.
- **G. Réglages** : vue Système par catégories, recherche, adresses directes.
- **H. Connaissances** : domaines (carte, fiches, questions de contrôle, score), extraction après les missions, révision ; sources scientifiques (OpenAlex, arXiv, PubMed, Europe PMC).
- **I. Ateliers** : pause / reprise, clôture avec notes, relance après échec, choix du modèle, conflits de fichiers entre ateliers, résumé de ce qui tourne dans le contexte ; veille des sessions Claude Code de l'utilisateur en LECTURE SEULE (état « vous attend / travaille / bloquée sur une permission », alerte voix ou téléphone ; format interne derrière une couche d'abstraction testée, désactivable ; jamais d'écriture dans ces sessions ni de lecture de leurs jetons).
- **J. Ressources et contrôle du PC** : CPU, RAM, GPU, VRAM ; Ollama démarré seulement sur demande, arrêt après inactivité, déchargement ; mode jeu (veille stricte) ; contrôle du PC sous 🟢🟡🔴 (volume, luminosité, fenêtres, média en cours, verrouillage, extinction annulable) avec modes qui changent vraiment Windows ; actions vérifiées en relisant l'état (sinon « non vérifiée ») ; vision : OCR d'abord, modèle de vision local seulement si peu de texte.
- **K. Voix** : voix de synthèse au choix (navigateur, ElevenLabs avec la clé de l'utilisateur), commandes vocales (silence, stop), « Dis Jarvis » en fond dans l'application de bureau, mémoire d'ambiance (désactivée par défaut). En plus :
  - éveil en deux étages : tampon horodaté, alias des erreurs de Whisper, correspondance floue, petit juge d'intention local seulement sur signal ; option openWakeWord avec notre propre modèle ;
  - relance sans mot d'éveil décidée sur les horodatages ; machine à états actif / veille ;
  - coupure quand on parle par-dessus : annulation d'écho (APM livekit, trames de 10 ms, délai mesuré), repli sans annulation d'écho (RMS micro contre haut-parleur, casque détecté) ; « stop » marche pendant la lecture ;
  - reconnaissance du propriétaire (ECAPA-TDNN, plusieurs empreintes, désactivée par défaut), fermée pour 🟡🔴 si indisponible ;
  - transcription robuste : small/medium int8, VAD Silero, préchauffage, filtres d'hallucinations (dont françaises), disjoncteur, CUDA / ROCm / processeur détectés (ROCm à mesurer sur les cartes AMD) ;
  - synthèse neuronale locale (Piper en processus séparé, voix FR), phrases générées en parallèle et lues dans l'ordre, voix du système en secours : JARVIS n'est jamais muet ; secrets masqués avant la lecture à voix haute ;
  - latence mesurée étape par étape dans `jarvis2 docteur` (Ollama par 127.0.0.1, keep_alive, préchauffage) ; fin de tour par un petit modèle et transcription anticipée ;
  - dictée globale Windows (raccourci maintenu, collage, dictionnaire de corrections, mise en forme selon l'application).
- **L. Accueil du matin** : salutation, météo Open-Meteo (ville privée), points d'attention ; préréglages proposés à l'installation (conversation, code, recherche, point du matin).
  Fait : `GET /v1/matin` au premier lancement du jour par appareil (`POST /v1/matin/vu`), jamais pendant l'arrêt d'urgence : date, heure, météo « à la maison » (Open-Meteo sans clé, cache 30 min ; lieu de `[matin]` ou des réglages, jamais dans le texte parlé ni l'audit), recettes du jour lancées ou en échec, au plus deux points d'attention ; carte en tête du dialogue, lue à voix haute en mode Parlé si la voix est active ; réglages Parlé / Texte seul / Désactivé, « Rejouer l'accueil », lieu par géocodage ou position de l'appareil ; étape « Préréglages » de l'assistant (`POST /v1/accueil/prereglages` : « Point du matin » crée la recette si absente et active l'accueil).
- **M. Bureau et téléphone** : protocole `jarvis://` (liste blanche), raccourcis globaux voix et écran, gadget de bureau ; téléphone (PWA via Tailscale) : notifications Web Push, « Partager vers JARVIS », liens de fichiers à usage unique, limite de tentatives au jumelage, appel de décision pour une action 🔴 (oui / non / plus tard, avec clé d'accès) ; jamais de déverrouillage à distance ; un contenu reçu reste non fiable.
- **N. Coûts et transparence** : suivi par connecteur et plafond de dépenses ; jauges d'abonnement 5 h / 7 jours lues dans nos propres appels (« inconnu » tant que rien n'est mesuré, périmé après 30 min) ; pied dépliable sous chaque réponse (moteur, modèle, durée, jetons, énergie si mesurable, estimations signalées).
  Fait : vue « Coûts » (`GET /v1/couts`, `couts.py`) : totaux du jour et du mois (heure locale), 30 derniers jours, détail par connecteur depuis `telemetrie` (équivalent API de l'abonnement pour information) ; plafond mensuel par connecteur payant (`PUT /v1/connecteurs/{id}/plafond`, migration 012) vérifié avant chaque appel par la garde de `MoteurInstrumente` (refus clair), routeur qui passe à une autre IA, alerte à 80 % sous la réponse ; jauges 5 h / 7 jours lues dans les `rate_limit_event` du flux stream-json de nos appels (en mémoire et dans `telemetrie.meta`) ; pied « Détails » sous chaque réponse. Énergie : non mesurable pour l'instant.
- **O. Amélioration continue** : suggestions, amélioration réalisée en atelier, aperçu, mise en service et retour arrière.
- **P. Thème « Présence »** : JARVIS en orbe de particules (mouvement dans un shader, voisins par grille spatiale, densité de pixels ≤ 2, réagit à la voix, 5 états : veille, écoute, réflexion, parole, compactage ; version fixe si l'utilisateur limite les animations) ; rendu séparé du fil audio ; niveau du micro visible ; option « HUD en fond d'écran ».

**Terminé quand** : chaque capacité de la liste de JARVIS v1 existe dans la v2 et a été vérifiée en vrai.

### 14. Le meilleur des autres
Les meilleures idées des autres assistants personnels (voir [INSPIRATIONS.md](INSPIRATIONS.md) : sources, licences, ce qui est repris en code ou seulement en idée). Aucun de ces projets n'est installé ni requis : tout est réimplémenté. Les outils tiers (Ollama, Piper, modèles) sont proposés, jamais installés sans l'accord de l'utilisateur. Dans l'ordre :

**A. Installation**
1. `install.ps1` / `install.sh` : winget / Homebrew pour ce qui manque, PATH relu depuis le registre, fichier d'état pour reprendre après une coupure, message final honnête ; Ollama et un premier modèle **proposés** (case à cocher, refus par défaut sans interaction).
2. Gros téléchargements en arrière-plan, marqueurs `.downloading` / `.ready` / `.failed` (renommage atomique), 3 essais, lus par `jarvis2 docteur`.
   Fait : `telechargements.py`, seul module des gros téléchargements (modèles d'embeddings fastembed, Whisper ; fichiers Hugging Face résolus par l'API du hub avec tailles et empreintes SHA-256 des fichiers LFS). Fichiers `.part` dans `<nom>.partiel/`, renommés un à un puis dossier renommé d'un bloc ; marqueurs à côté du dossier (`.downloading` avec progression et battement, périmé après 2 min = « interrompu » ; `.ready` ; `.failed` avec raison) ; 3 essais (attente 2 s puis 4 s), reprise par `Range`, refus des chemins hors du dossier. **Rien n'est téléchargé sans accord** : le démarrage du Core ne charge un modèle que s'il est déjà sur le disque (téléchargé ou ancien cache), les encodeurs n'utilisent plus que des fichiers locaux (`ModeleAbsent` sinon, 409 pour la dictée). Accord = bouton (diagnostic, page Mémoire), `POST /v1/telechargements/{embeddings|voix}` ou `jarvis2 docteur --reparer`. État : `GET /v1/telechargements`, diagnostic (« Mémoire » et « Dictée ») et `jarvis2 docteur`.
3. Une seule table matériel → modèle ; RAM Windows lue sans wmic ; un palier sous le maximum pour garder de la marge ; cartes AMD (ROCm) prises en compte.
4. Point d'entrée pipx `jarvis2` en plus des installeurs.
5. Signature du code (programme gratuit pour l'open source ou service de signature) et mises à jour signées ; paquets winget et Homebrew.

**B. Agents sûrs**
6. Barrière d'injection par tour : dès qu'un tour a lu du web, l'écran, un fichier externe ou une autre session, les outils qui agissent sont refusés jusqu'à la fin du tour.
7. Approbation liée à l'empreinte du plan exact (le plan change : l'approbation tombe), confirmation émise par l'interface et jamais par le modèle ; pile d'annulation pour les actions 🟡 réversibles (corbeille plutôt que suppression).
8. Détecteur d'« exécution inventée » : une réponse qui prétend avoir agi sans appel d'outil est signalée, vérifiée contre le journal réel des outils.
   Fait : `securite/invente.py` repère les affirmations d'action accomplie (français et anglais : « j'ai envoyé », « je viens de lancer », « a bien été supprimé », « I've sent »…) et les confronte aux entrées d'audit écrites pendant le tour et aux outils que le moteur déclare avoir exécutés ; sans action correspondante : meta `invente` du message, événement SSE `invente`, entrée d'audit 🟡 `dialogue.execution_inventee` (catégories et verbes, jamais le texte), avertissement discret sous la réponse. Dialogue, recettes et missions (résultat `invente`). La réponse n'est jamais modifiée.
9. Ateliers dans un vrai bac à sable sous Windows (conteneur sans réseau ou Windows Sandbox) ; refus si le bac à sable est indisponible.
10. Brainstorm → spec Markdown → plan à cases → exécution, avancement lu dans les cases ; missions en graphe de dépendances (étapes indépendantes en parallèle, raison du choix de modèle dans l'audit, repli sur la conversation simple).
11. Routeur par type de tâche (code, raisonnement, rapide, privé) par un petit classifieur local qui donne sa raison, rétrogradation d'une route dont le score baisse.
12. Skills SKILL.md importables : niveaux de confiance, capacités dangereuses (shell, réseau, écriture) bloquées sans revue, empreinte SHA-256 du dossier à l'approbation (un fichier modifié bloque le skill), exécution sans clés d'API dans l'environnement et confinée à son dossier ; MCP : sessions persistantes, une relance, outils choisis par le sens (et un outil de recherche d'outils), moins de 12 outils proposés au modèle local par tour.

**C. Confidentialité**
13. Masquage des secrets étendu (cartes avec contrôle de Luhn, clés AWS / Stripe / GitHub / OpenAI / Google, JWT, Bearer, codes à usage unique, identifiants dans les adresses ; empreintes git épargnées) avant le contexte et avant le journal.
14. Niveaux public / semi-privé / privé qui décident ce qui peut sortir vers le cloud ; porte de rappel sans LLM ; un fait mémorisé est **remplacé** quand l'utilisateur change d'avis (test dédié).
15. Page « Où partent mes données », générée depuis la configuration réelle (fonction, service contacté, ce qui part, local ou non) ; accord séparé avant d'envoyer une image à un service cloud.

**D. Maison et extensions**
16. Widgets générés à la demande dans le HUD (météo, minuteur, liste) : fragment filtré par DOMPurify avec liste fermée de balises, attributs, classes et adresses ; phrase d'attente dès qu'un outil long démarre.
17. Connecteurs facultatifs 🟡 : Philips Hue (API locale du pont), OBS (WebSocket).
18. Home Assistant, le PC restant le cerveau :
    - transcription et synthèse exposées en Wyoming ;
    - pilotage par le serveur MCP de Home Assistant (transport MCP HTTP + OAuth/PKCE ; repli : API REST avec jeton dans le coffre) ;
    - niveaux : 🟢 lecture, 🟡 lumières, prises, média, 🔴 serrures, alarme, portail (confirmation + voix du propriétaire) ;
    - satellites (Home Assistant Voice ou ESP32-S3 sous ESPHome) : seul l'audio après l'éveil part vers le PC, clé par appareil, présence par pièce, déblocage après 25 s, plafond de volume, minuteurs sur le satellite d'origine ;
    - profils par personne liés à la reconnaissance de voix.
19. Mode serveur sans écran (`jarvis2 --sans-ecran`) : micro du navigateur ou des satellites, contrôle d'écran désactivé.

**Terminé quand** : chaque point est en place et vérifié en vrai, et INSPIRATIONS.md dit d'où vient chaque idée.

### Objectif transversal : le meilleur dépôt GitHub du genre
À traiter au fil des phases, pas à la fin :
- **README** :
  - en haut, une ligne d'installation par système ;
  - un GIF de démonstration réel et des captures dans les 4 thèmes et sur téléphone ;
  - un tableau « ce qui tourne en local / ce qui sort » ;
  - le matériel requis, dit honnêtement (AMD compris) ;
  - une comparaison factuelle avec les autres projets, sans dénigrer.
- **Langues** : README en anglais avec `README.fr.md` ; interface traduisible (anglais en plus du français).
- **Documentation** : installation par système, dépannage, architecture (schéma), sécurité et permissions, écrire un skill, une commande ou une recette, FAQ.
- **Qualité visible** : badges (CI, licence, version), tests et banc mémoire publiés, CHANGELOG tenu, versions sémantiques, notes de version honnêtes ; une CI qui exécute les commandes du README.
- **Communauté** : CONTRIBUTING, CODE_OF_CONDUCT, modèles d'issues et de PR, Discussions, étiquettes « good first issue », feuille de route publique (ce plan).
- **Dépôt** : description, sujets et image de partage ; aucun fichier généré ni binaire versionné ; aucune donnée personnelle (historique vérifié avant chaque push).
- **Installeurs** : signés dès que l'utilisateur fournit les certificats ; en attendant, contournements expliqués honnêtement.

Ce qui demande une action sur le compte GitHub (Discussions, sujets, image de partage, rendre une version publique) est préparé, puis soumis à l'utilisateur avant d'être fait.


Plus tard, facultatif : passerelle de messagerie (Telegram / Signal, avec jumelage des expéditeurs inconnus), application mobile native.

## Corrections intégrées dès le départ (retours sur JARVIS v1)

| Problème constaté | Correction |
|---|---|
| Isolation des ateliers jamais active | Worktree obligatoire par atelier, testé (phase 9) |
| Tests manquants | Pytest + Vitest dès la phase 1 |
| Production sur des fichiers non commités | On ne lance que du code commité ; installeurs construits en CI |
| Aucune sauvegarde hors site | Sauvegarde hors site testée (phase 12) |
| Rôle propriétaire de la base qui contourne l'audit | Rôles séparés dès la phase 1, audit en ajout seul (phase 4) |
| Dizaines d'appels API en double au démarrage | Un seul appel d'amorçage, requêtes dédoublonnées (vérifié) |
| Mise en page cassée à 1280 px | Grille vérifiée à 375, 1280 et 1920 px à chaque phase d'interface |
