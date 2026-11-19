# Décisions techniques

## Connecteurs maison Hue et OBS (phase 14 · D, point 17, migration 013)

- **Désactivés par défaut**, activés à la main dans Connecteurs → Maison (table `connecteurs_maison` : état et adresse). La clé du pont Hue et le mot de passe d'OBS vivent dans le coffre local (`maison.hue`, `maison.obs`), jamais en base, dans les réponses ni dans l'audit. « Oublier » retire le secret et désactive.
- **Commandes = actions du registre** (`hue.*`, `obs.*`) : 🟢 `hue.etat`, `obs.etat` ; 🟡 allumer, éteindre, luminosité, couleur, scène Hue, scène OBS, enregistrement, arrêt du direct ; 🔴 `obs.direct.demarrer` (publication : clé d'accès). Elles passent par la file d'approbations et l'audit chaîné, et refusent d'agir pendant l'arrêt d'urgence, même approuvées. Une action porte désormais un prédicat `disponible` : celles d'un connecteur désactivé n'apparaissent pas dans `/v1/actions` ni dans `outils_actifs` de `/v1/maison` (la liste à proposer au dialogue), et une demande créée avant la désactivation échoue à l'approbation.
- **Hue** : API v1 locale du pont en HTTPS. Le certificat du pont est signé par l'autorité de Signify, absente des magasins du système : il n'est pas vérifié ; en contrepartie seules les adresses privées sont acceptées, la clé ne part donc jamais sur Internet. Découverte par mDNS (`_hue._tcp.local`, TTL 1) ; le service en ligne `discovery.meethue.com` seulement si l'utilisateur coche l'accord (entrée d'audit 🟡), adresses publiques écartées. Appairage : bouton du pont puis `POST /api` (clé « username »).
- **OBS** : WebSocket v5 (OBS 28+), une connexion courte par commande, sans abonnement aux événements ; mot de passe jamais envoyé en clair (empreinte SHA-256 sel + défi). Client WebSocket minimal écrit dans `maison/websocket.py` plutôt qu'une dépendance (texte seulement, réponses aux ping). Adresse : bouclage ou réseau local.
- Le dialogue n'a pas encore d'appel d'outils natif : les commandes se déclenchent par `/v1/actions` ; `outils_actifs` est la liste à brancher quand il en aura un.

## Détecteur d'« exécution inventée » (phase 14 · B, point 8)

- **Signaler, jamais corriger** : la réponse reste telle que le modèle l'a écrite ; le signalement va dans la meta du message (`invente`), un événement SSE `invente` après `fin`, et l'audit (🟡 `dialogue.execution_inventee`, cible = message ou mission, détails = catégories et verbes seulement, le texte pouvant être privé).
- **Journal réel du tour** = entrées d'audit écrites entre le début et la fin de la réponse (repère : dernier identifiant d'audit), plus les outils que le moteur déclare dans `meta["outils"]`. Ne comptent pas : une action en échec, une simple demande (`demande.*`), un signalement précédent. Une action d'une autre catégorie n'appuie pas l'affirmation (supprimer ≠ envoyer), sauf un outil au sens inconnu (MCP, action enregistrée au nom non reconnu) qui appuie tout : mieux vaut rater une invention que crier au loup.
- **Règles plutôt que modèle** : expressions régulières sur des verbes d'action (envoyer, supprimer, lancer, installer, payer, programmer…), sans appel à une IA (rapide, déterministe, local). Faux positifs écartés : futur, conditionnel, négation, questions, hypothèses (« si », « par exemple »), citations et code ; les verbes qui servent aussi à travailler le texte (créer, ajouter, modifier, supprimer…) n'entrent en compte qu'avec un objet concret (fichier, rappel, agenda…) et jamais quand la phrase montre le résultat (« voici », « ci-dessous ») ou que la réponse contient du code. Lire et chercher ne sont pas des actions à vérifier ; « j'ai bien enregistré votre demande » non plus (politesse), mais « j'ai enregistré votre préférence dans ma mémoire » oui (aucune écriture en mémoire pendant le tour).
- Le détecteur ne bloque jamais une réponse : audit illisible ou erreur = pas de vérification pour ce tour (journalisé).

## Matériel → modèle (phase 14 · A, point 3)

- **Une seule table** (`materiel.TABLE`) : pour chaque usage (conversation et vision par Ollama, embeddings, transcription Whisper), des paliers « mémoire nécessaire → modèle ». Le conseil prend le plus gros palier qui tient puis **descend d'un palier** pour garder de la marge (contexte long, autres programmes) ; le maximum est montré à titre indicatif. Exception : les embeddings (taille fixe, chargés une fois) ne descendent pas.
- **Mémoire utile** : VRAM de la carte si elle accélère (CUDA, ROCm, Vulkan) et dépasse 4 Go ; Apple Silicon : 70 % de la mémoire unifiée ; sinon la moitié de la RAM, avec un plafond de 7 à 9 milliards de paramètres (lenteur du processeur). Whisper et les embeddings tournent sur le processeur : leur budget est la RAM.
- **Détection** sans dépendance ni wmic : RAM par `GlobalMemoryStatusEx` (Windows), `/proc/meminfo`, `sysctl hw.memsize` (macOS) ; `nvidia-smi` puis `rocm-smi` s'ils existent ; sinon le registre des cartes graphiques (Windows, toutes marques, valeur 64 bits) ou `/sys/class/drm` (pilote amdgpu). Une carte AMD RX 6800 et plus, RX 7000, RX 9000 est comptée ROCm (Ollama embarque ses bibliothèques), les autres Vulkan. Une seule détection par lancement du Core.
- Exposé par `GET /v1/materiel`, `jarvis2 docteur` (ligne « Matériel et modèles locaux ») et la famille « locale » de la page Connecteurs. Rien n'est jamais téléchargé ni démarré : les noms sont des conseils.

## Application de bureau et publication (phase 11)

- **Coque Tauri 2** (`app/`) : une fenêtre sur l'interface du Core local ; le Core n'est pas embarqué (installé par le script, `uv tool install`) : l'application le lance s'il ne tourne pas (sans console) et n'arrête que celui qu'elle a lancé. L'interface est une page distante pour l'application : aucune permission native (`capabilities/default.json` vide). Icône de notification (Ouvrir, Quitter), fermer = cacher, Ctrl+Maj+J, une seule instance.
- **Construction** sur GitHub Actions (`publication.yml`) : à une étiquette `v*`, roue du Core + installeurs Windows (NSIS, MSI), macOS (DMG), Linux (DEB, AppImage), déposés dans une version **en brouillon** (rien de public avant que le propriétaire la publie). Signatures par secrets du dépôt, facultatifs : clé de mise à jour Tauri, certificat Windows, certificats et notarisation Apple.
- **Installation en une ligne** : sans `-Source` et hors d'un dépôt, les scripts prennent la roue de la dernière version publiée (`releases/latest`).
- Construction locale impossible sur un disque exFAT (Cargo ne peut pas y fixer les dates des fichiers) : elle se fait sur GitHub.

## Sauvegarde et bascule (phase 12)

- **Archive** (`sauvegarde.py`) : `JARVIS2S1` + sel scrypt (n = 2¹⁵) + nonce + AES-256-GCM d'un tar.gz (base, `config.toml`, recettes, manifeste). SQLite : copie cohérente par l'API de sauvegarde de SQLite ; PostgreSQL : `pg_dump -Fc` dans le conteneur. Le coffre des clés d'API n'est pas inclus (chiffré par Windows pour ce compte et ce PC). Écriture atomique (`.partiel` puis renommage), rotation des 7 dernières.
- **Vérification** : déchiffrement, restauration dans une base temporaire (fichier temporaire ou base `jarvis2_verification_sauvegarde`, effacée ensuite), comparaison au manifeste (lignes des tables principales, chaîne d'audit et dernière empreinte).
- **Rattrapage** : l'import `jarvis_v1` est rejouable (aucun doublon) ; à lancer avec la dernière sauvegarde quotidienne de JARVIS v1, copiée en lecture seule.

## Voix, vision, créations (phase 10)

- **Transcription locale** (`voix.py`) : faster-whisper sur le CPU (int8), modèle téléchargé une fois dans `<données>/modeles/whisper` ; l'audio (webm/opus du navigateur, wav…) est décodé par PyAV puis rééchantillonné à 16 kHz par JARVIS (l'appel de PyAV dans faster-whisper n'est plus compatible avec PyAV ≥ 15). Invite initiale « Jarvis » pour l'orthographe du nom ; mot d'éveil tolérant (« j'arvi », « djarvis »…).
- **Synthèse vocale** dans l'interface : `speechSynthesis` avec une voix française **locale** seulement (`localService`) ; sans voix locale, rien n'est lu (jamais de voix en ligne). Lecture phrase par phrase pendant le flux.
- **Mains libres** : détection de la parole par le niveau sonore (phrase = parole puis 0,9 s de silence, 15 s au plus) ; chaque phrase est transcrite sur le PC et ignorée sauf si elle commence par « Jarvis » (ou suit un « Jarvis » seul dans les 8 s). L'écoute est suspendue pendant que JARVIS parle ou répond.
- **Vision** (`vision.py`) : seulement sur demande, à partir d'une capture que l'utilisateur déclenche et choisit (`getDisplayMedia`) ; décrite par le modèle local `[connecteurs.ollama] modele_vision` ; l'image n'est ni gardée ni envoyée ailleurs.
- **Créations** (`creations.py`) : page HTML générée par le routeur (IA locale pour un sujet privé), servie par `/creations/<id>?v=&j=` avec un jeton HMAC de 10 minutes (secret propre au démarrage) et la CSP `sandbox allow-scripts …; default-src 'none'; connect-src 'none'; frame-ancestors <origine de l'interface>` : origine unique (aucun accès à l'interface, aux jetons ni au stockage), aucune requête réseau. `frame-ancestors 'self'` ne convient pas : sous `sandbox`, il désignerait l'origine opaque de la page.

## Dialogue avancé (phase 13, lot E)

- **Images jointes** : préparées dans le navigateur (`interface/src/images.ts`) : JPEG, PNG, WebP, GIF ; 5 par message ; au-delà de 1 600 px ou 1 Mo, réduites et recompressées (JPEG reste JPEG, PNG et WebP en WebP, ou JPEG si le navigateur n'écrit pas le WebP ; 85 %) ; GIF jamais redimensionné, refusé au-delà de 3 Mo. Le Core revérifie tout (`vision.decoder_jointe` : type lu dans les premiers octets, jamais l'en-tête annoncé ; SVG refusé ; 3 Mo au plus).
- **Rien n'est gardé** : les images vivent en mémoire le temps de la réponse ; l'historique ne garde que leur nombre, leur type et leur poids (`meta.images`), et les messages suivants disent seulement au modèle qu'il y en avait. Seule exception, Claude Code (CLI) : les images sont écrites dans un dossier temporaire du système (`jarvis2-images-*`), dossier de travail de la CLI avec l'outil `Read` pour seul outil (lecture dans ce dossier seulement), effacé dès la fin de la réponse, même en cas d'erreur ou d'annulation. L'interface garde les miniatures dans la page tant qu'elle reste ouverte.
- **Moteurs** : API Anthropic (blocs `image` en base64), compatibles OpenAI (parties `image_url`), Ollama (`images` ; si le modèle choisi n'a pas la capacité « vision » annoncée par `/api/show`, le `modele_vision` de la configuration locale prend le relais, sinon message clair). Codex et Antigravity : pas de vision, refus clair avant tout envoi. Le routeur ne choisit qu'un connecteur qui lit les images ; un sujet privé reste sur une IA locale. Le filtre des secrets ne s'applique pas au contenu d'une image : l'utilisateur la joint lui-même.
- **Palette et commandes** : une seule liste (`interface/src/commandes.ts`) pour la palette Ctrl+K, les commandes « / » de la saisie (« // » envoie un texte qui commence par « / ») et l'aide (`?` ou `/aide`). Raccourcis Ctrl+K, Ctrl+H, Ctrl+M ; l'arrêt d'urgence demande toujours une confirmation. Fenêtres en `<dialog>` modal (focus piégé puis rendu, Échap ferme sans arrêter la réponse en cours).

## Ateliers Claude Code (phase 9, migration 009)

- **Binaire officiel plutôt que le SDK** : `claude -p --output-format stream-json` dans le worktree, environnement sans clés d'API, réponse refusée si `apiKeySource` ≠ `none` (même règle que le connecteur). Les ateliers exigent l'avertissement Claude Code accepté.
- **Isolation** : `git worktree add -b jarvis/atelier-<id>` dans `<données>/ateliers/<projet>/`, depuis le HEAD du projet ; le projet n'est touché qu'à la fusion.
- **Autorisations** (`ateliers/autorisation.py`) : Claude Code appelle avant chaque outil `mcp__jarvis__autoriser` (`--permission-prompt-tool`), servi par `jarvis2 atelier-mcp` (stdio) qui relaie au Core (`POST /v1/ateliers-autorisation`, boucle locale seulement, jeton aléatoire propre à chaque exécution). Écriture : autorisée dans le worktree (chemins résolus), refusée ailleurs, ainsi que dans `.git` et les `.env` ; lecture hors du worktree, commandes, réseau, autres outils : décision de l'utilisateur en direct (refus au bout de 10 minutes). Chaque décision est notée dans le fil de l'atelier.
- **Fusion** : action 🟡 `atelier.fusionner` — JARVIS commite le worktree (auteur « JARVIS »), puis `merge --no-ff` dans le projet s'il est propre ; en cas de conflit, `merge --abort` (projet inchangé). Abandon : le worktree est retiré, la branche reste.
- **Projets** : `[[ateliers.projets]]` (id, nom, chemin) de la configuration locale. Limite connue : git refuse un dépôt sur un disque sans propriétaires (exFAT) tant que `safe.directory` ne l'autorise pas.

## Mémoire v2 (phase 8, migration 008)

- **Classement v2** (`memoire_v2.classer_v2`, défaut ; `ReglagesRecherche.classement = "v1"` pour l'ancien) : par sous-question, score = (0,6 × hybride + 0,4 × RRF normalisé, k = 60) × (0,85 + 0,3 × importance). La recherche renvoie les deux composantes (cosinus, plein texte) pour cela. La récence reste dans la fusion.
- **Blocs** (`blocs.py`, `memory_blocks`) : courts textes toujours injectés avant le noyau, chaque écriture est une version (`memory_block_versions`) ; `local_uniquement` = jamais vers une IA externe. Le noyau peut devenir les blocs « noyau » et « noyau-prive » : les souvenirs restent, leur tag devient `noyau-converti` (réversible).
- **Oubli** : un souvenir injecté dans une réponse voit `access_count` et `last_accessed_at` mis à jour ; chaque nuit, les souvenirs jamais consultés, peu importants (≤ 0,3), vieux de plus de 180 jours sont **archivés** — jamais ceux dits par l'utilisateur, du profil ou du noyau. Rien n'est effacé.
- **Consolidation** (`consolidation.py`, 3 h 30) : une IA **locale** seulement (sinon ignorée) lit les échanges depuis la dernière consolidation et propose des faits durables (JSON) ; un fait déjà connu (cosinus ≥ 0,92) est ignoré ; un fait sur un sujet privé est rangé privé.
- **Bascule de modèle** : `memoire_vecteurs (memoire_id, modele, vecteur)` garde les vecteurs d'un autre modèle (dimension libre). Changer `JARVIS2_MODELE_EMBEDDINGS` lance au démarrage le calcul en tâche de fond ; la recherche garde l'ancien modèle (`etat_systeme.memoire_modele`) et ne bascule qu'à 100 %. Avant toute bascule, le modèle actif est celui de la majorité des souvenirs.
- **Export** (4 h, ou `jarvis2 memoire exporter`) : `memoire-md/` dans le dossier des données (MEMORY.md, USER.md, SOUL.md, journal/AAAA-MM-JJ.md), en lecture seule.
- **Banc** (`jarvis2 memoire banc --fichier questions.yaml`) : liste de `{question, attendus}` (identifiants ou fragments de contenu) ; rappel@5 et MRR en v1 et en v2. Le fichier reste chez l'utilisateur (données personnelles).
- Les tâches de nuit passent par le planificateur des recettes (`TacheSysteme`, historique `executions_recettes` sous `systeme:<id>`), jamais pendant l'arrêt d'urgence.

## Agents (phase 7, migration 007)

- **Recettes** (`agents/recettes.py`) : fichiers YAML (`nom`, `planification` cron à l'heure de Paris, `consigne`, `connecteur`, `livraison` conversation ou mémoire, `active`) dans `recettes/` à côté de la configuration locale ; relus à chaque battement (30 s), donc modifiables sans redémarrer. Une recette jamais exécutée attend sa première heure après le démarrage (pas de rattrapage en rafale). Historique dans `executions_recettes`. Une recette ne fait que demander une réponse : elle ne déclenche aucune action 🟡 ni 🔴, et rien ne tourne pendant l'arrêt d'urgence.
- **Missions** (`agents/missions.py`, table `missions`) : recherche (plan de requêtes → SearXNG → rapport), brainstorm, revue ; tâche de fond, étapes et progression en base, rapport rangé en mémoire (origine `mission`, privé si le sujet l'est). Les pages web sont transmises entre balises `<donnees>`, déclarées comme données ; la liste des sources est ajoutée par JARVIS, pas par le modèle. Sans SearXNG, le rapport le dit en première ligne.
- **Sujets privés** : `[confidentialite] sujets_prives` (motifs) ou un souvenir `local_uniquement` qui répond au message → le routeur ne propose que des IA locales ; s'il n'y en a aucune, il refuse (le choix explicite d'une IA reste possible). Distinct de `sujets_exclus`, qui retire le sujet de la mémoire injectée.
- **MCP** (`agents/mcp.py`) : client stdio (JSON-RPC 2.0, une ligne par message, protocole 2025-06-18), processus lancé à la demande sans les clés d'API de l'environnement. Chaque outil est inactif par défaut (`outils_mcp`) ; un appel est l'action 🟡 `mcp.appeler` (file d'approbations, audit) ; le résultat est une donnée. Limite connue : l'appel s'exécute dans la transaction de la décision, ce qui tient la base SQLite le temps de l'outil (30 s au plus).

## Stockage : SQLite par défaut, PostgreSQL en option (phase 6)

- **Une interface, deux moteurs** (`db.py`) : le Core n'utilise que `fetch`, `fetchrow`, `fetchval`, `execute`, `acquire` et `transaction` (le sous-ensemble d'asyncpg). `db_postgres.py` enveloppe asyncpg ; `db_sqlite.py` tient **une** connexion sur un fil d'exécution dédié (une requête à la fois, `BEGIN IMMEDIATE` pour les transactions, points de sauvegarde pour les transactions imbriquées, annulation = retour arrière).
- **Requêtes écrites une fois** (style PostgreSQL) et traduites pour SQLite : `$1` → `?1`, conversions `::type` et `FOR UPDATE` retirés ; `now()`, `gen_random_uuid()` et `regexp` ajoutés à chaque connexion. Les durées sont calculées en Python (`datetime.now(UTC) + délai`), jamais par `interval`. Seules la recherche mémoire, le tag noyau et l'audit ont une version par moteur.
- **Types** par les types déclarés du schéma SQLite (`migrations/sqlite/`) : UUID, TIMESTAMPTZ (texte UTC à largeur fixe : l'ordre du texte est l'ordre chronologique), BOOLEAN, JSONB, TEXTLIST et UUIDLIST (tableaux JSON), VECTOR (float32).
- **Recherche** : même score (0,75 × cosinus + 0,25 × plein texte). Cosinus par sqlite-vec (`vec_distance_cosine`), à défaut la même fonction en Python ; plein texte par FTS5 (`unicode61 remove_diacritics 2`, accents et casse ignorés, **sans racinisation française**, mots vides retirés), tenu à jour par déclencheurs.
- **Audit** : SQLite n'a pas de rôles. La chaîne est calculée en Python avec le texte canonique d'`audit_canonique()` (JSON écrit comme `jsonb`) ; des déclencheurs refusent UPDATE et DELETE. Qui a accès au fichier peut retirer un déclencheur, mais toute altération est détectée par `jarvis2 verifier-audit`. Pour une séparation forte (rôle d'audit distinct), utiliser PostgreSQL.
- **Migrations alignées** : chaque migration PostgreSQL a sa jumelle SQLite (même nom). Le schéma SQLite initial (001) contient l'état à la migration 005 ; 002 à 005 sont des marqueurs. SQLite se migre seul au démarrage du serveur.
- **Choix** : `JARVIS2_STOCKAGE` ; vide = PostgreSQL si son mot de passe applicatif est configuré (installation existante), sinon SQLite. L'import `jarvis_v1` passe par une base d'attente PostgreSQL.
- **Copie** `jarvis2 stockage copier --vers sqlite|postgres` (`stockage_copie.py`) : vers une cible vide, tout tel quel (identifiants, dates, vecteurs, empreintes d'audit), plein texte recalculé, contrôles suspendus le temps de la copie ; vérifiée (nombres de lignes, chaîne d'audit, clés étrangères). Testé par aller-retour PostgreSQL → SQLite → PostgreSQL.
- Tous les tests de base tournent sur les deux moteurs (fixture `pool` paramétrée) ; ceux qui portent sur les rôles PostgreSQL restent sur PostgreSQL (`pool_pg`).

## Installation pour tous (phase 6)

- **Paquet** : `uv build --wheel` dans `core` après `npm run build` ; l'interface compilée est livrée dans la roue (`jarvis2/web`), aucun Node à l'exécution. Commande `jarvis2` ; seule, elle migre SQLite, démarre le Core et ouvre l'interface.
- **Scripts** `install.ps1` / `install.sh` : uv (script officiel d'Astral, après confirmation), `uv tool install --python 3.13`, `jarvis2 docteur --reparer`, puis `jarvis2`. Essais : Windows (dossiers isolés, depuis la roue) en 7 min 30 s, dont le téléchargement du modèle ; Linux (conteneur `python:3-slim`) en 15 s. macOS non essayé.
- **Configuration sans fichier** : SQLite, 127.0.0.1:8765. Réglages facultatifs dans `jarvis2.env` du dossier de configuration (installation) ou `.env` du dépôt (développement).
- **Diagnostic** (`diagnostic.py`, `jarvis2 docteur [--json] [--reparer]`, `GET /v1/diagnostic`) : Python, dossier des données, stockage et schéma, interface, modèle d'embeddings, cerveaux, Claude Code, réseau, téléphone, audit, arrêt d'urgence. Réparations automatiques seulement si elles sont sûres : créer ou mettre à jour le schéma SQLite, télécharger le modèle. Le reste donne une commande ou un lien.
- **Assistant de premier lancement** : état dans `etat_systeme` (`accueil`, migration 006) ; une installation existante le voit une fois. Étapes : vérifications, cerveau (page Connecteurs), téléphone, prêt.
- **Accueil de Claude Code** : comme Antigravity, le connecteur ne s'active qu'après un avertissement coché par l'utilisateur (`CONDITIONS["claude_code"]`, versionné) : programme officiel non modifié, abonnement personnel, usage personnel et non commercial, aucun identifiant lu, alternatives (clé d'API Anthropic, Ollama, compatible OpenAI). Il n'est pas « à risque » : le routeur le choisit une fois accepté. Une installation existante doit cocher l'avertissement une fois.
- **Téléphone** : Tailscale, en lecture seule (`tailscale status`, `tailscale serve status`) ; JARVIS ne lance jamais `tailscale up` ni `tailscale serve`, il les propose. Quand le Core est publié (`tailscale serve --bg <port>`), l'adresse `https://<pc>.<réseau>.ts.net` devient une origine autorisée et l'adresse du QR de jumelage. Le premier appareil reste réservé au navigateur du PC (`localhost`).
- **PWA** : manifeste, icônes (192, 512, 180 pour iOS), service worker (pages : réseau d'abord ; fichiers compilés : cache ; `/v1/` jamais en cache). Le navigateur intégré de l'application Claude refuse l'enregistrement du service worker ; Chrome l'accepte (vérifié).

## Stockage PostgreSQL dans un volume Docker

PostgreSQL exige des droits Unix (0700) sur son dossier de données. Un dossier monté depuis un système de fichiers qui ne les gère pas (exFAT, montages Windows via Docker Desktop) est refusé (`initdb: could not change permissions … Operation not permitted`). `docker-compose.yml` utilise donc un volume Docker nommé (`jarvis2_pg`). Pour placer les données sur un autre disque, déplacer le disque virtuel de Docker Desktop (Settings › Resources › Advanced › Disk image location). Le stockage SQLite par défaut (phase 6) supprimera ce besoin pour la plupart des installations.

## asyncpg plutôt que psycopg

Sous Windows, les sous-processus asyncio (CLI `claude`) exigent la boucle Proactor, que le mode asynchrone de psycopg ne prend pas en charge. asyncpg fonctionne avec elle.

## Le prompt de la CLI `claude` passe par l'entrée standard

Windows limite une ligne de commande à 32 767 caractères alors que le prompt peut atteindre 100 000 : il est écrit sur l'entrée standard de la CLI.

## Toujours `stream-json`, et contrôle de la source d'authentification

Seule la sortie `stream-json` émet l'événement `system/init` et son champ `apiKeySource`. JARVIS 2 lit toujours le flux (`generate` le consomme jusqu'au bout) et **refuse** toute réponse dont la source n'est pas `none` (abonnement de l'utilisateur) : une clé API configurée ailleurs ne peut pas basculer JARVIS sur la facturation à l'appel. JARVIS ne lit ni ne transmet jamais de jeton d'abonnement.

## Rôles de base séparés dès la phase 1

`jarvis2_proprio` (migrations) et `jarvis2_app` (Core : données seulement, télémétrie et journal des imports en ajout seul). Le rôle d'audit en ajout seul arrive en phase 4.

## Imports : sources génériques, lecture seule, exclusions locales

`jarvis2/importeurs/` contient une source par outil d'origine. La première, `jarvis_v1`, part d'une **sauvegarde** `pg_dump -Fc` fournie par l'utilisateur (la base vivante de la source n'est jamais interrogée) :
1. restauration dans une base d'attente isolée (`import_jarvis_v1`, refusée au rôle applicatif ; la table des jetons d'accès n'est jamais restaurée) ;
2. copie des tables utiles par le rôle applicatif, en une transaction, identifiants et vecteurs compris, en écartant ce que la configuration locale exclut (`[import.jarvis_v1]` : `exclure_sources`, `exclure_contenus`) ;
3. rapport source / présents / exclus / nouveaux / mis à jour dans la table `imports`.

```powershell
cd core
.\.venv\Scripts\python -m jarvis2 importer jarvis_v1 --sauvegarde <chemin\vers\sauvegarde.dump>
.\.venv\Scripts\python -m jarvis2 verifier-import jarvis_v1
```

L'import est rejouable (rattrapage) : une ligne n'est mise à jour que si elle a changé, un message n'est jamais doublé. La vérification ré-encode un échantillon de souvenirs (même modèle = cosinus 1) et compare les 5 premiers résultats de recherche sur la base d'attente et dans JARVIS 2 pour des requêtes témoins (configuration locale, ou une liste générique).

## Recherche mémoire

`jarvis2/memoire.py` reprend l'algorithme de JARVIS v1 : sous-questions, score 0,75 cosinus + 0,25 plein texte français, fusion, diversité, budgets (10 souvenirs, seuil 0,2, 7 000 caractères, 3 par source), noyau (souvenirs tagués `noyau`, 4 000 caractères). Les souvenirs `local_uniquement` ne partent jamais vers un moteur externe. Les **sujets exclus** de l'utilisateur (`[confidentialite] sujets_exclus` de la configuration locale) sont retirés de tout texte de mémoire injecté au modèle.

## Sécurité (phase 4, migration 004)

- **Appareils** : chaque appareil a son jeton (32 octets aléatoires, `Authorization: Bearer`), dont seule l'empreinte SHA-256 est stockée ; liste et révocation dans l'onglet Sécurité. Toute route `/v1/` l'exige, sauf la santé et le jumelage.
- **Premier appareil** : tant qu'aucun appareil n'a jamais été enregistré, le navigateur du PC (boucle locale, hôte `localhost`) s'enregistre d'un clic. Ensuite : jumelage seulement (code à usage unique valable 5 minutes, montré en QR depuis un appareil autorisé, ou `jarvis2 jumeler` sur le PC).
- **Permissions** : 🟢 exécuté (lecture, retrait d'un accès, arrêt d'urgence) ; 🟡 demande approuvée d'un clic ; 🔴 demande approuvée **uniquement** par une clé d'accès WebAuthn (vérification de l'utilisateur exigée, défi lié à la demande, à usage unique, 5 minutes). Les clés d'accès exigent un nom d'hôte (`localhost`, nom Tailscale…), jamais une adresse IP.
- **Audit** : table en ajout seul, propriété du rôle `jarvis2_audit` (sans connexion), alimentée par `audit_ajouter()` (SECURITY DEFINER) ; déclencheurs contre UPDATE / DELETE / TRUNCATE ; chaîne d'empreintes SHA-256 vérifiable par `jarvis2 verifier-audit` (détecte même une modification faite par un super-utilisateur).
- **Arrêt d'urgence** : annule tout de suite les réponses en cours (la CLI est tuée), puis refuse toute écriture par HTTP 423, sauf ce qui sert à le lever ou à retirer un accès ; l'état survit au redémarrage. Le lever est une action 🔴. Secours de l'administrateur du PC (clé perdue) : `jarvis2 lever-urgence`, qui exige les identifiants du propriétaire de la base et est journalisé 🔴.
- **Filtre** : avant tout moteur externe, chaque texte (consignes, mémoire, historique, message) passe par `securite/filtre.py` (clés d'API, jetons, clés privées, mots de passe, IBAN et cartes vérifiés, n° de sécurité sociale, e-mails, téléphones) ; les réponses d'un modèle local bâties sur des souvenirs privés sont masquées pour les moteurs externes. La conversation stockée et les modèles locaux gardent le texte d'origine.
- **Réseau** : le Core n'écoute que sur 127.0.0.1 ; écouter ailleurs exige `JARVIS2_OUVERTURE_RESEAU=true`, et toute autre origine web doit être déclarée (`JARVIS2_ORIGINES`, liste JSON).

## Connecteurs d'IA (phase 5, migration 005)

- **Une classe, plusieurs connecteurs** : l'identité d'un moteur (id, nom, famille `cli` / `api` / `local`, externe, risque, liens) est portée par l'instance. Le catalogue (`connecteurs.construire_catalogue`) assemble les connecteurs de l'installation à partir de `.env`, de la configuration locale et du coffre.
- **Comptes par CLI** (`moteurs/sousprocessus.py`) : binaire officiel installé et connecté par l'utilisateur ; dossier temporaire vide par appel, effacé ensuite ; environnement sans clés ; prompt sur l'entrée standard ; arbre de processus tué en cas de délai, d'annulation ou d'arrêt d'urgence. Les fichiers d'identifiants ne sont jamais ouverts (test qui surveille toutes les ouvertures de fichiers). Codex : `codex exec --json --sandbox read-only --skip-git-repo-check --ephemeral -`, état de connexion par `codex login status`. Antigravity : `agy -p … --output-format stream-json --sandbox` ; format du flux supposé identique à Gemini CLI, **à confirmer** sur une sortie réelle.
- **Google (compte)** : désactivé par défaut ; activable seulement si la requête porte `accepte: true` et la version courante de l'avertissement (case cochée par l'utilisateur, jamais pré-cochée) ; date et version de l'acceptation gardées en base, audit 🟡 ; une nouvelle version de l'avertissement désactive le connecteur jusqu'à nouvelle acceptation. Le routeur ne le choisit jamais.
- **Clés d'API** : coffre local `coffre.json` à côté de la configuration locale, valeurs chiffrées par DPAPI sous Windows (fichier 0600 ailleurs) ; l'interface ne reçoit que « enregistrée » et les 4 derniers caractères ; aucune clé dans la base ni dans les journaux (test). Coût : celui du fournisseur (OpenRouter), sinon les tarifs de la configuration locale, sinon `cout_inconnu`.
- **Locaux** : Ollama, et serveurs compatibles OpenAI sur leurs ports habituels (LM Studio 1234, llama.cpp 8080, vLLM 8000). Un port peut être occupé par n'importe quel programme : la carte dit ce qu'elle voit (« serveur compatible OpenAI détecté sur… »), et ces serveurs détectés **démarrent désactivés**.
- **Routeur** : choix explicite > choix imposé pour la conversation (`conversations.connecteur`, posé dès que l'utilisateur choisit un connecteur, effacé par « Auto ») > connecteur préféré (`JARVIS2_MOTEUR_DEFAUT`) > compte, puis clé d'API, puis local. Seuls les connecteurs actifs sont sondés au démarrage et par le routeur.
- **Conseil** : experts choisis dans Connecteurs (« Dans le conseil »), sinon jusqu'à 4 connecteurs utilisables non risqués ; avis en parallèle, chacun préparé pour son connecteur (filtre, souvenirs privés) ; synthèse par le routeur, avis transmis comme données ; avis local privé masqué pour une synthèse externe.

## Mémoire v2 préparée sans rien recalculer (migration 003)

- **Modèle d'embedding stocké par ligne** (`embedding_model`) : aucune dimension n'est supposée dans le code ; la recherche ne compare que les vecteurs produits par le modèle de l'encodeur actif. Passer à un autre modèle (ex. `BAAI/bge-m3`, 1024 dimensions) = ajouter une colonne de vecteurs (index HNSW halfvec), la remplir en tâche de fond, basculer.
- **Validité temporelle sans DELETE** : `valid_from`, `valid_to`, `superseded_by`, `observed_at` ; la recherche et le noyau ne voient que `valid_to IS NULL AND NOT archived`.
- **Oubli et consolidation** : `importance` (0 à 1), `last_accessed_at`, `access_count`, `archived`, `derived_from`.
- **Blocs éditables** (`memory_blocks`, historique `memory_block_versions`) : créés mais vides ; le noyau reste pour l'instant le tag `noyau` et deviendra des blocs en phase 8.
