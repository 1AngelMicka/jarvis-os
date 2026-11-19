# Étendre JARVIS : commandes rapides, recettes, skills

Ce guide décrit les formats que le code attend réellement. Trois extensions existent : les **commandes rapides**, les **recettes** et les **skills** au format `SKILL.md`, plus les serveurs MCP.

## Commandes rapides

Code : `core/jarvis2/commandes_rapides.py` et `core/jarvis2/securite/jokers.py`.

Une commande rapide associe une **phrase reconnue sans IA** à une **action**. L'interface soumet chaque message au Core avant l'IA : si une commande active correspond, l'action est appliquée (ou demandée) et la phrase ne part pas à l'IA. Une commande ne donne **aucun droit en plus** : jamais de shell, jamais d'expression régulière, jamais d'évaluation ; une action du Core passe par la file d'approbations comme si vous l'aviez demandée à la main.

### Où les écrire

Dans l'interface : Réglages › Interface & apparence › **Commandes rapides** (adresse directe `#reglages/commandes-rapides`). L'éditeur vérifie la phrase de test, montre l'action résolue et son niveau, et signale les autres commandes qui captent la même phrase.

### Champs

| Champ | Contraintes |
|---|---|
| `motif` | 2 à 200 caractères ; voir ci-dessous |
| `cible` | `interface` ou `core` |
| `action` | une action d'interface, ou le nom d'une action déclarée du Core |
| `parametres` | objet JSON de 2 000 caractères au plus ; `{nom}` y est remplacé par la capture du même nom |
| `priorite` | entier de -100 à 100 (défaut 0) |
| `phrase_test` | phrase qui **doit** correspondre au motif : vérifiée à l'enregistrement |
| `actif` | `true` ou `false` |

200 commandes au plus. Une phrase de plus de 300 caractères n'est jamais traitée comme une commande.

### Le motif

Le motif est comparé à la phrase **entière**, sans accents, sans majuscules ni ponctuation : « Ouvre les Réglages ! » se lit « ouvre les reglages ».

- `*` : n'importe quel texte, même vide. Les espaces autour sont facultatifs : `ouvre * missions` accepte « ouvre missions ».
- `{nom}` : un morceau de texte capturé (au moins un caractère), réutilisable dans les paramètres. Nom en minuscules, chiffres et `_`, 31 caractères au plus, sans doublon ; 5 captures au plus. La capture garde le texte d'origine (accents, majuscules), ponctuation de bord retirée.
- Le motif doit contenir au moins deux lettres ou chiffres : `*` seul capterait tout et est refusé (« Motif trop large »).

Quand plusieurs commandes captent la phrase : la priorité la plus haute l'emporte, puis le motif le plus précis (le plus de caractères littéraux), puis la plus ancienne.

### Actions d'interface (`cible: interface`)

Niveau 🟢, appliquées par l'interface selon le même contrôle que les actions proposées par JARVIS :

| Action | Paramètres |
|---|---|
| `naviguer` | `vue` parmi `dialogue`, `historique`, `activite`, `demandes`, `securite`, `memoire`, `connaissances`, `agents`, `ateliers`, `ameliorations`, `connecteurs`, `couts`, `reglages`, `accueil` ; pour `reglages`, `ancre` facultative (identifiant de section, ex. `commandes-rapides`) |
| `rechercher_memoire` | `requete` : texte de 1 à 200 caractères |
| `regler` | `cle` = `theme` (`jarvis`, `studio`, `atelier`, `console`) ou `animations` (`systeme`, `normales`, `reduites`) ; `valeur` |

Lancer une mission ou un atelier n'est pas une action d'interface : JARVIS peut seulement les proposer.

### Actions du Core (`cible: core`)

N'importe quelle action déclarée du registre, avec son niveau : 🟢 exécutée, 🟡 demandée (un clic), 🔴 demandée et approuvée seulement par une clé d'accès. Les règles de protection s'appliquent. La liste des actions de votre installation est donnée par `GET /v1/actions` ; les principales sont dans [SECURITE.md](SECURITE.md#actions-déclarées). Une action inconnue est refusée : « Action inconnue : « … » (seules les actions déclarées, jamais de shell) ».

### Exemples

Ouvrir une vue :

```json
{
  "motif": "ouvre les reglages",
  "cible": "interface",
  "action": "naviguer",
  "parametres": { "vue": "reglages" },
  "priorite": 0,
  "phrase_test": "Ouvre les réglages !",
  "actif": true
}
```

Chercher dans la mémoire, avec une capture :

```json
{
  "motif": "cherche {sujet} dans ma memoire",
  "cible": "interface",
  "action": "rechercher_memoire",
  "parametres": { "requete": "{sujet}" },
  "priorite": 0,
  "phrase_test": "Cherche les vacances dans ma mémoire",
  "actif": true
}
```

Changer de thème :

```json
{
  "motif": "theme console",
  "cible": "interface",
  "action": "regler",
  "parametres": { "cle": "theme", "valeur": "console" },
  "priorite": 0,
  "phrase_test": "Thème console",
  "actif": true
}
```

Régler le volume du PC (action du Core 🟡, Windows seulement : une demande est créée, à approuver d'un clic) :

```json
{
  "motif": "volume a {n}",
  "cible": "core",
  "action": "pc.volume",
  "parametres": { "niveau": "{n}" },
  "priorite": 10,
  "phrase_test": "Volume à 30",
  "actif": true
}
```

### Par l'API

Les mêmes objets se manipulent par l'API, avec le jeton d'un appareil autorisé (`Authorization: Bearer …`) :

| Route | Effet |
|---|---|
| `GET /v1/commandes-rapides` | liste, avec le niveau de chaque action |
| `POST /v1/commandes-rapides/verifier` | vérifie sans rien enregistrer : `valide`, `erreur`, action résolue pour la phrase de test, `conflits` |
| `POST /v1/commandes-rapides` | crée (422 avec le message d'erreur si la commande est invalide) |
| `PUT /v1/commandes-rapides/{id}` | modifie |
| `DELETE /v1/commandes-rapides/{id}` | supprime |
| `POST /v1/commandes-rapides/executer` | `{"phrase": "…"}` : la commande qui la capte, ou `{"trouvee": false}` |

Création, modification, suppression et chaque utilisation sont inscrites au journal d'audit.

## Recettes

Code : `core/jarvis2/agents/recettes.py`. Exemple : [docs/recettes/point-du-matin.yaml](recettes/point-du-matin.yaml).

Une recette est une **consigne envoyée à JARVIS selon une planification** ; le résultat est livré dans une conversation ou rangé dans la mémoire. Une recette **n'agit pas** : elle demande seulement une réponse, sans aucune action 🟡 ni 🔴.

### Où les mettre

Un fichier YAML par recette, dans le dossier `recettes` **à côté de votre `config.toml`** :

- Windows : `%APPDATA%\JARVIS2\recettes\`
- macOS, Linux : `~/.config/jarvis2/recettes/`

Le dossier exact est affiché dans la vue Agents, section « Recettes planifiées ». Le planificateur relit le dossier à chaque battement (toutes les 30 secondes) : pas besoin de redémarrer le Core.

### Format

Le **nom du fichier** (sans `.yaml` ou `.yml`) est l'identifiant : minuscules, chiffres, `-` et `_`, 64 caractères au plus, commençant par une lettre ou un chiffre.

| Champ | Obligatoire | Valeurs |
|---|---|---|
| `nom` | oui | texte (120 caractères gardés) |
| `planification` | oui | expression cron à 5 champs : minute heure jour-du-mois mois jour-de-semaine, **heure de Paris** |
| `consigne` | oui | le texte envoyé à JARVIS (20 000 caractères gardés) |
| `connecteur` | non | `auto` (défaut : le routeur choisit) ou l'identifiant d'un connecteur : `claude_code`, `anthropic_api`, `codex`, `ollama`, `openai`, `gemini`, `openrouter`, `lmstudio`, `llamacpp`, `vllm`, ou l'`id` d'un `[[connecteurs.compatibles]]` |
| `livraison` | non | `conversation` (défaut : une conversation par exécution) ou `memoire` (rangé dans la mémoire) |
| `active` | non | `true` (défaut) ou `false` |

Exemple, une veille hebdomadaire confiée à une IA locale et rangée en mémoire (`~/.config/jarvis2/recettes/bilan-du-vendredi.yaml`) :

```yaml
nom: Bilan du vendredi
# 18 h 00 chaque vendredi (heure de Paris)
planification: "0 18 * * 5"
consigne: |
  Fais le bilan de ma semaine en cinq points : ce qui est fait, ce qui reste,
  et ce que je devrais préparer pour lundi.
connecteur: ollama
livraison: memoire
active: true
```

### Fonctionnement

- Chaque recette est lancée à son heure, une seule fois. Une recette jamais exécutée attend sa première heure après le démarrage du Core ; une heure manquée pendant que le Core était arrêté est rattrapée une fois au redémarrage.
- Jamais pendant l'**arrêt d'urgence** (l'exécution est notée « ignorée ») ; mise en attente pendant le **mode jeu**.
- Le routage s'applique comme pour un message : avec `auto`, une consigne qui touche un sujet privé n'est confiée qu'à une IA locale. La barrière d'injection et le détecteur d'exécution inventée s'appliquent aussi.
- Vue Agents : liste des recettes, dernière exécution, bouton « Lancer maintenant » (`POST /v1/recettes/{id}/lancer`).
- L'étape « Préréglages » de l'assistant de premier lancement peut créer la recette « Point du matin ».

### Erreurs de lecture

Un fichier invalide est ignoré et son erreur est affichée dans la vue Agents, par exemple :

- « bilan : champs manquants (planification) »
- « bilan : planification cron invalide « 99 * * * » »
- « Mauvais Nom : nom de fichier invalide (minuscules, chiffres, - et _) »
- « bilan : livraison « conversation » ou « memoire » attendue »

## Skills

Un skill est un **dossier** qui contient un fichier `SKILL.md` (format agentskills.io) et, parfois, des scripts. Il vient d'ailleurs : JARVIS le traite comme une **donnée**, jamais comme une consigne. Code : `core/jarvis2/agents/skills.py`, routes `core/jarvis2/api_skills.py`, interface : vue Agents, section Skills.

### Écrire un `SKILL.md`

En-tête YAML obligatoire `name` et `description`, `allowed-tools` facultatif, puis le texte des instructions :

```markdown
---
name: resume-reunion
description: Résumer les notes d'une réunion en décisions et actions.
---

Lis les notes fournies, puis rends trois listes : décisions, actions (avec la personne), questions ouvertes.
```

Scripts possibles dans le dossier : `.py`, `.ps1`, `.sh`, `.js`, `.mjs`. Limites à l'import : 1 Mo par fichier, 5 Mo et 200 fichiers au total ; liens symboliques et chemins qui sortent du dossier refusés.

### Importer

- depuis un **dossier local** que vous choisissez (`POST /v1/skills/importer/dossier`, corps `{"chemin": "…"}`) ;
- depuis une **archive `.zip`** (`POST /v1/skills/importer/archive?nom=…`, corps brut).

La source est lue en lecture seule et copiée dans `<données>/skills/<id>/`. Un skill importé est `non_fiable` : inutilisable tant qu'il n'est pas revu.

### Revue et capacités dangereuses

À l'import, JARVIS repère trois capacités dangereuses : **shell** (`allowed-tools` : `Bash`, `PowerShell`…, scripts, motifs), **réseau** (`WebFetch`, `WebSearch`…) et **écriture** (`Write`, `Edit`…). Elles restent **bloquées** tant que vous ne les cochez pas une à une pendant la revue (vous pouvez lire chaque fichier du skill dans l'interface). Résultat de la revue :

- `instructions` : approuvé, son texte peut être donné au modèle, aucune capacité dangereuse ;
- `capacites` : approuvé avec les capacités cochées.

L'approbation est l'action 🟡 `skill.approuver`, jamais « toujours autorisée », liée à l'empreinte exacte que vous avez revue, et inscrite au journal d'audit.

### Empreinte

L'empreinte SHA-256 du dossier est enregistrée à l'approbation, puis **recalculée à chaque usage** : un fichier ajouté, retiré ou modifié bloque le skill (`statut = bloque`) jusqu'à une nouvelle revue.

### Utilisation

Les skills approuvés (empreinte intacte) sont candidats, avec les outils MCP activés, aux outils proposés au modèle à chaque tour (`agents/outils_tour.py` : moins de 12, choisis par le sens). Le modèle ne lance rien lui-même :

- `skill.lire` (🟢) : lire les instructions d'un skill approuvé, rendues comme une donnée ;
- `skill.executer` (🟡, jamais « toujours autorisée ») : lancer un script du skill. Exige la capacité « shell » acceptée ; le dossier courant est celui du skill, l'environnement est sans clés d'API ni secrets de JARVIS, l'écriture va dans un dossier de sortie à part, la durée est bornée (60 s) et la sortie aussi.

Ce n'est pas un bac à sable du système : le réseau n'est pas coupé au niveau du système, d'où la capacité « réseau » à cocher pour un script qui y touche.

## Autres points d'extension

- les **serveurs MCP** (transport stdio), déclarés dans `config.toml` ; chaque outil reste inactif tant que vous ne l'activez pas (vue Agents), et chaque appel est une action 🟡 :

  ```toml
  [[mcp.serveurs]]
  id = "fichiers"
  commande = "npx"
  args = ["-y", "@modelcontextprotocol/server-filesystem", "C:/Documents/partage"]
  ```

  Réglages, sessions, relance et recherche d'outils : `/v1/mcp/reglages`, `/v1/mcp/sessions`, `/v1/mcp/serveurs/{id}/relancer`, `/v1/mcp/outils/chercher`.

- les **points d'accès compatibles OpenAI** (`[[connecteurs.compatibles]]`, voir [INSTALLATION.md](INSTALLATION.md#serveurs-compatibles-openai)) ;
- dans le code, un **nouveau moteur** (contrat `core/jarvis2/moteurs/base.py`) ou une **nouvelle source d'import** (`core/jarvis2/importeurs/`) : voir [CONTRIBUTING.md](../CONTRIBUTING.md).
