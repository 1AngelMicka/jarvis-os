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

### 6. Installation pour tous
Mode navigateur, assistant de premier lancement, `jarvis doctor`, stockage SQLite + sqlite-vec et migration vers / depuis PostgreSQL, accueil du moteur Claude Code (avertissement, alternatives), jumelage du téléphone par QR + PWA.
**Terminé quand** : sur une machine vierge (Windows, macOS, Linux), le script d'installation mène à une conversation en moins de 10 minutes sans Docker ni Node, et un téléphone jumelé converse via Tailscale.

### 7. Agents
Battement de cœur + planificateur + recettes YAML partageables (résultats livrés sur le canal choisi), compétences SKILL.md (format agentskills.io) créées après une tâche complexe, missions (recherche, brainstorm, revue), conseil multi-IA, client MCP (OAuth par utilisateur, interrupteur par outil) et serveur MCP (mémoire, missions), recherche web privée SearXNG avec sources citées, routeur local / externe.
**Terminé quand** : une recette planifiée livre son résultat, une mission produit un rapport sourcé rangé en mémoire, un sujet privé est routé vers un modèle local, un outil MCP est appelé sous approbation.

### 8. Mémoire v2
Validité et remplacement exploités, blocs éditables (le noyau devient des blocs), consolidation nocturne sur un modèle local, entités légères, reclassement (bge-reranker-v2-m3) + RRF + récence et importance, oubli par archivage, faits / opinions avec confiance / épisodes, mémoire lisible en Markdown (SOUL.md, USER.md, MEMORY.md, journal du jour), banc d'évaluation de 50 à 100 questions, passage à `BAAI/bge-m3` (1024 dimensions, ré-encodage en tâche de fond, modèle stocké par ligne).
**Terminé quand** : le banc d'évaluation progresse face à la mémoire v1, la bascule de modèle d'embedding se fait sans interruption, aucun souvenir n'est effacé par la consolidation.

### 9. Ateliers Claude Code
Sessions Claude Agent SDK sur les projets de l'utilisateur, **vraie isolation par worktree** git, approbations en ligne, pilotage (pause, reprise, arrêt), bac à sable Docker pour l'exécution de code.
**Terminé quand** : deux ateliers en parallèle sur un même projet travaillent chacun dans leur worktree, une écriture hors du worktree est refusée (test), la fusion passe par une approbation.

### 10. Voix, vision, créations
Mot d'éveil, transcription (Whisper), synthèse vocale phrase par phrase pendant le flux, compatibilité Wyoming / Home Assistant, vision sur demande, créations en bac à sable, recommandation de modèles locaux selon le matériel.
**Terminé quand** : un échange vocal complet fonctionne mains libres, une capture d'écran n'est décrite que sur demande, une création s'ouvre dans un bac à sable isolé.

### 11. Application, installeurs, publication
Coque Tauri, installeurs .exe / .dmg / .deb / .AppImage par GitHub Actions, signature du code, documentation, licence. Publication du dépôt **uniquement avec l'accord explicite de l'utilisateur** (historique vérifié : aucune donnée personnelle).
**Terminé quand** : un installeur signé s'installe et se met à jour, la documentation permet une installation sans aide, l'utilisateur a validé la publication.

### 12. Bascule de l'installation personnelle
Pour l'utilisateur qui vient de JARVIS v1 : sauvegarde hors site testée, rattrapage des souvenirs créés depuis l'import (`jarvis2 importer jarvis_v1`, rejouable), fonctionnement en parallèle, arrêt de JARVIS v1 **uniquement sur décision de l'utilisateur**.
**Terminé quand** : une restauration depuis la sauvegarde hors site a été testée, le rattrapage ne laisse aucun écart, l'utilisateur a décidé de la suite.

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
