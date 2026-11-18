# Décisions techniques

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
