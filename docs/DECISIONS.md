# Décisions techniques

## 2026-11-18 — Données PostgreSQL dans un volume Docker (provisoire)

**Constat.** Le disque de données est en **exFAT**. PostgreSQL exige des droits Unix (0700) sur son dossier de données : un dossier de ce disque monté dans le conteneur est refusé (`initdb: could not change permissions … Operation not permitted`, essai du 18 nov.). Le disque virtuel de Docker Desktop est aujourd'hui sur C: (`<dossier de Docker Desktop>`).

**Décision provisoire.** Volume Docker nommé `jarvis2_pg` (dans le disque virtuel de Docker Desktop). La base de la phase 2 pèse quelques Mo.

**À décider par l'utilisateur** (avant la phase 3, qui importe les souvenirs) :
1. *(recommandé)* Déplacer le disque virtuel de Docker Desktop sur le disque de données (Docker Desktop › Settings › Resources › Advanced › Disk image location). Un fichier `.vhdx` fonctionne sur exFAT (c'est déjà le cas de la distribution WSL de l'ancien JARVIS). Ce réglage déplace **tous** les conteneurs et volumes Docker du PC, dont la pile multimédia.
2. Garder le volume sur C: et sauvegarder la base sur le disque de données (`pg_dump` quotidien, puis hors site en phase 9).

## 2026-11-18 — asyncpg plutôt que psycopg

Sous Windows, les sous-processus asyncio (CLI `claude`) exigent la boucle Proactor, que le mode asynchrone de psycopg ne prend pas en charge. asyncpg fonctionne avec elle.

## 2026-11-18 — Le prompt de la CLI `claude` passe par l'entrée standard

L'ancien JARVIS (Linux) passait le prompt en argument de `-p`. Windows limite une ligne de commande à 32 767 caractères alors que le prompt peut atteindre 100 000 : JARVIS 2 l'écrit sur l'entrée standard de la CLI.

## 2026-11-18 — Toujours `stream-json`, et contrôle de la source d'authentification

Les deux formes (`json`, `stream-json`) existent dans la CLI, mais seule `stream-json` émet l'événement `system/init` et son champ `apiKeySource`. JARVIS 2 lit toujours le flux (`generate` le consomme jusqu'au bout) et **refuse** toute réponse dont la source n'est pas `none` (abonnement) : une clé API configurée ailleurs ne peut pas basculer JARVIS sur la facturation à l'appel.

## 2026-11-18 — Rôles de base séparés dès la phase 1

`jarvis2_proprio` (migrations) et `jarvis2_app` (Core : données seulement, télémétrie en ajout seul). Le rôle d'audit en ajout seul arrive en phase 4 sur la même base.
