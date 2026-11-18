# Décisions techniques

## 2026-11-18 — Données PostgreSQL dans un volume Docker (provisoire)

**Constat.** Le disque de données est en **exFAT**. PostgreSQL exige des droits Unix (0700) sur son dossier de données : un dossier de ce disque monté dans le conteneur est refusé (`initdb: could not change permissions … Operation not permitted`, essai du 18 nov.). Le disque virtuel de Docker Desktop est aujourd'hui sur C: (`<dossier de Docker Desktop>`).

**Décision provisoire.** Volume Docker nommé `jarvis2_pg` (dans le disque virtuel de Docker Desktop). Après l'import de la phase 3 : base `jarvis2` 25 Mo, base d'attente `ancien_jarvis` 30 Mo.

**À décider par l'utilisateur** (avant la phase 3, qui importe les souvenirs) :
1. *(recommandé)* Déplacer le disque virtuel de Docker Desktop sur le disque de données (Docker Desktop › Settings › Resources › Advanced › Disk image location). Un fichier `.vhdx` fonctionne sur exFAT (c'est déjà le cas de la distribution WSL de l'ancien JARVIS). Ce réglage déplace **tous** les conteneurs et volumes Docker du PC, dont la pile multimédia.
2. Garder le volume sur C: et sauvegarder la base sur le disque de données (`pg_dump` quotidien, puis hors site en phase 9).

## 2026-11-18 — Import de l'héritage depuis une sauvegarde, jamais depuis la base vivante

L'ancien Core n'est jamais interrogé : on copie (lecture seule) sa sauvegarde quotidienne `pg_dump -Fc` de `<sauvegardes de la source>` vers `<dossier des données>\import\` (empreinte SHA-256 vérifiée des deux côtés), puis on la restaure dans une base d'attente isolée `ancien_jarvis` du PostgreSQL de JARVIS 2 (accès refusé au rôle applicatif ; la table `jetons` n'est jamais restaurée). L'import copie ensuite les tables utiles avec le rôle `jarvis2_app`, en une transaction, identifiants et vecteurs compris, et range le rapport dans `imports`.

Commandes :
```powershell
cd core; .\.venv\Scripts\python -m jarvis2 importer-ancien --sauvegarde <dossier des données>\import\<fichier>.dump
.\.venv\Scripts\python -m jarvis2 verifier-heritage
```
L'import est rejouable : c'est aussi l'outil du rattrapage de la phase 9 (une ligne n'est mise à jour que si elle a changé, un message n'est jamais doublé). Les fichiers de connaissances (hors `pg_dump`) sont copiés dans `<dossier des données>\heritage\connaissances` ; leur contenu est aussi dans les souvenirs d'origine `connaissances`.

## 2026-11-18 — Recherche mémoire portée à l'identique

`jarvis2/memoire.py` reprend l'algorithme de l'ancien `memoire.py` (sous-questions, 0,75 cosinus + 0,25 plein texte, fusion, diversité, budgets, noyau, expurgation du sujet exclu) avec les mêmes réglages (10 souvenirs, seuil 0,2, 7 000 caractères, 3 par source, noyau 4 000 caractères). Vérifié le 18 nov. : cosinus 1,000000 entre vecteurs importés et recalculés, et 5 premiers résultats identiques sur les données de l'ancien JARVIS et dans JARVIS 2 pour 8 requêtes témoins, avec et sans souvenirs privés. Pas encore repris : la détection de domaine de connaissance, les « nouveautés » et les résumés de conversation (à prévoir avec les agents, phase 5).

## 2026-11-18 — asyncpg plutôt que psycopg

Sous Windows, les sous-processus asyncio (CLI `claude`) exigent la boucle Proactor, que le mode asynchrone de psycopg ne prend pas en charge. asyncpg fonctionne avec elle.

## 2026-11-18 — Le prompt de la CLI `claude` passe par l'entrée standard

L'ancien JARVIS (Linux) passait le prompt en argument de `-p`. Windows limite une ligne de commande à 32 767 caractères alors que le prompt peut atteindre 100 000 : JARVIS 2 l'écrit sur l'entrée standard de la CLI.

## 2026-11-18 — Toujours `stream-json`, et contrôle de la source d'authentification

Les deux formes (`json`, `stream-json`) existent dans la CLI, mais seule `stream-json` émet l'événement `system/init` et son champ `apiKeySource`. JARVIS 2 lit toujours le flux (`generate` le consomme jusqu'au bout) et **refuse** toute réponse dont la source n'est pas `none` (abonnement) : une clé API configurée ailleurs ne peut pas basculer JARVIS sur la facturation à l'appel.

## 2026-11-18 — Rôles de base séparés dès la phase 1

`jarvis2_proprio` (migrations) et `jarvis2_app` (Core : données seulement, télémétrie en ajout seul). Le rôle d'audit en ajout seul arrive en phase 4 sur la même base.
