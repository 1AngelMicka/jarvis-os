# Décisions techniques

## Stockage PostgreSQL dans un volume Docker

PostgreSQL exige des droits Unix (0700) sur son dossier de données. Un dossier monté depuis un système de fichiers qui ne les gère pas (exFAT, montages Windows via Docker Desktop) est refusé (`initdb: could not change permissions … Operation not permitted`). `docker-compose.yml` utilise donc un volume Docker nommé (`jarvis2_pg`). Pour placer les données sur un autre disque, déplacer le disque virtuel de Docker Desktop (Settings › Resources › Advanced › Disk image location). Le stockage SQLite par défaut (phase 5) supprimera ce besoin pour la plupart des installations.

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

## Mémoire v2 préparée sans rien recalculer (migration 003)

- **Modèle d'embedding stocké par ligne** (`embedding_model`) : aucune dimension n'est supposée dans le code ; la recherche ne compare que les vecteurs produits par le modèle de l'encodeur actif. Passer à un autre modèle (ex. `BAAI/bge-m3`, 1024 dimensions) = ajouter une colonne de vecteurs (index HNSW halfvec), la remplir en tâche de fond, basculer.
- **Validité temporelle sans DELETE** : `valid_from`, `valid_to`, `superseded_by`, `observed_at` ; la recherche et le noyau ne voient que `valid_to IS NULL AND NOT archived`.
- **Oubli et consolidation** : `importance` (0 à 1), `last_accessed_at`, `access_count`, `archived`, `derived_from`.
- **Blocs éditables** (`memory_blocks`, historique `memory_block_versions`) : créés mais vides ; le noyau reste pour l'instant le tag `noyau` et deviendra des blocs en phase 7.
