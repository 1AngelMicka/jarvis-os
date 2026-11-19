# Sécurité et permissions

JARVIS garde votre mémoire et peut agir pour vous : la sécurité est construite avant les accès. Ce document décrit les garde-fous tels qu'ils sont **implémentés** dans le Core (`core/jarvis2/securite/` pour l'essentiel).

**Signaler une faille** : n'ouvrez pas d'issue publique, suivez [SECURITY.md](../SECURITY.md) (signalement privé).

## Principes

- **Local d'abord** : le Core n'écoute que sur `127.0.0.1`. Écouter ailleurs est refusé au démarrage sans `JARVIS2_OUVERTURE_RESEAU=true`. L'accès à distance passe par Tailscale (`tailscale serve`), jamais par un port ouvert.
- **Rien d'irréversible ou d'externe sans validation humaine** : toute action qui agit passe par la file d'approbations.
- **Contenu externe = donnée, jamais instruction** : pages web, fichiers, captures, partages reçus, résultats d'outils ne donnent pas d'ordres (barrière d'injection ci-dessous).
- **Tout est tracé** dans un journal d'audit en ajout seul, chaîné par empreintes.

## Appareils et accès

- Chaque requête `/v1/` exige le jeton d'un **appareil autorisé** (`Authorization: Bearer`), sauf la santé et le jumelage. Le jeton fait 32 octets aléatoires ; seule son empreinte SHA-256 est stockée. Un appareil se révoque dans Réglages › Appareils.
- Le **premier appareil** ne s'enregistre que depuis le navigateur du PC (`http://localhost`). Ensuite, seulement par **jumelage** : code à usage unique valable 5 minutes, montré en QR par un appareil autorisé ou créé par `jarvis2 jumeler` sur le PC. 5 échecs par source, ou 20 au total en 15 minutes, bloquent l'échange (HTTP 429).
- Une **origine web inconnue** est refusée (403) : une page malveillante ouverte dans votre navigateur ne peut pas viser le Core.
- Les **clés d'API** vivent dans un coffre local (`coffre.json` à côté de `config.toml`) : chiffrées par DPAPI sous Windows, fichier en droits 0600 ailleurs ; jamais dans la base ni dans les journaux. L'interface n'en reçoit que l'état « enregistrée » et les 4 derniers caractères.

## Niveaux 🟢 🟡 🔴

Défini dans `securite/permissions.py`. Chaque action déclarée du registre a un niveau :

| Niveau | Code | Effet |
|---|---|---|
| 🟢 | `vert` | exécutée tout de suite (lecture, protection, arrêt d'urgence, retrait d'un accès) |
| 🟡 | `jaune` | une **demande** attend l'approbation d'un appareil autorisé, d'un clic |
| 🔴 | `rouge` | la demande ne s'approuve **qu'avec une clé d'accès** (WebAuthn, vérification de l'utilisateur : empreinte, visage ou code de l'appareil), défi lié à cette seule demande |

Chaque étape (demande, approbation, refus, exécution, échec) est inscrite au journal d'audit. Une demande expire après 30 minutes. Sur le téléphone, chaque demande 🟡🔴 déclenche un **appel de décision** (notification générique, sans le détail) : Oui (clé d'accès obligatoire pour 🔴), Non, ou Plus tard (rappel 15 minutes après, 3 fois au plus).

Les clés d'accès exigent un nom d'hôte (`localhost`, nom Tailscale), jamais une adresse IP. Enregistrez-en une dans Réglages › Sécurité › Clés d'accès : sans elle, aucune action 🔴 ne peut être approuvée.

### Actions déclarées

| Action | Niveau |
|---|---|
| `conversation.archiver`, `memoire.archiver` (archivage, réversible) | 🟡 |
| `conversation.supprimer`, `chantier.supprimer` | 🔴 |
| `chantier.abandonner`, `regle.supprimer` | 🟡 |
| `atelier.fusionner`, `amelioration.mettre_en_service`, `amelioration.revenir` | 🟡 |
| `mcp.appeler` (outil d'un serveur MCP) | 🟡 |
| `urgence.lever` | 🔴 |
| `pc.etat`, `pc.extinction.annuler`, `pc.jeu`, `ollama.decharger` | 🟢 |
| `pc.volume`, `pc.sourdine`, `pc.luminosite`, `pc.fenetre.*`, `pc.media`, `pc.verrouiller`, `pc.mode`, `ollama.demarrer`, `ollama.arreter` | 🟡 |
| `pc.eteindre` (extinction annulable jusqu'au bout) | 🔴 |
| `hue.etat`, `obs.etat` | 🟢 |
| `hue.allumer`, `hue.eteindre`, `hue.luminosite`, `hue.couleur`, `hue.scene`, `obs.scene`, `obs.enregistrement`, `obs.direct.arreter` | 🟡 |
| `obs.direct.demarrer` | 🔴 |
| `ha.etat` (Home Assistant : lecture de l'état) | 🟢 |
| `ha.lumiere`, `ha.prise`, `ha.media` | 🟡 |
| `ha.serrure`, `ha.alarme`, `ha.portail` (clé d'accès **et** voix du propriétaire, voir plus bas) | 🔴 |
| `skill.lire` | 🟢 |
| `skill.approuver`, `skill.executer` (jamais « toujours autorisées ») | 🟡 |

Les actions `pc.*` (sauf `pc.jeu`) ne sont disponibles que là où JARVIS sait piloter le PC (Windows, hors mode sans écran) ; les actions `hue.*`, `obs.*` et `ha.*` seulement quand le connecteur correspondant est activé. La liste réelle de votre installation est donnée par `GET /v1/actions`.

Le registre **refuse toute action dont le nom contient `deverrouill` ou `unlock`** : rien ne déverrouille le PC ni le téléphone, ni à distance ni sur place.

### Empreinte du plan exact

À la création d'une demande, le Core calcule l'empreinte SHA-256 du texte canonique de ce qui sera exécuté (action, niveau, résumé, paramètres ; `empreinte_plan` dans `securite/permissions.py`). L'interface affiche une empreinte courte (8 caractères) et renvoie l'empreinte qu'elle a montrée avec l'approbation :

- si elle diffère, ou si la demande enregistrée ne correspond plus à son empreinte, l'approbation tombe (demande en échec, à relancer) ;
- l'empreinte est revérifiée juste avant d'exécuter ;
- une action dont la cible peut changer entre la demande et l'approbation (contenu d'un atelier) « fige » cet état dans ses paramètres : il entre dans l'empreinte et l'exécution le revérifie ;
- le modèle ne peut rien approuver : aucune action du registre ni aucun bloc du pilotage n'appelle la décision.

### Pile d'annulation

Chaque action 🟡 déclare si elle est réversible et comment l'annuler (ou pourquoi elle ne s'annule pas, et quoi faire à la main). Une action réversible exécutée entre dans la pile d'annulation (table `annulations`, 24 heures, 30 entrées listées dans « Dernières actions annulables »). « Annuler », depuis l'interface ou par commande rapide, rejoue son annulation, inscrite au journal d'audit.

### Home Assistant : 🔴 gardé

Le connecteur Home Assistant (`maison/home_assistant.py`, désactivé par défaut) décide lui-même du niveau de chaque domaine, jamais Home Assistant ni le modèle : 🟢 lecture de l'état, 🟡 lumières, prises, média, 🔴 serrures, alarme et portail (`lock`, `alarm_control_panel`, `cover` de type portail ou garage). Une entité d'un autre domaine que celui de l'action est refusée : « allumer une prise » ne peut pas ouvrir un portail. Une adresse Internet est refusée : seuls le réseau local, Tailscale ou ce PC sont acceptés.

Une action 🔴 de Home Assistant exige, en plus de la clé d'accès, **la voix du propriétaire** (`maison.garder_rouge`) : la reconnaissance doit être activée et disponible, et à la demande une phrase du propriétaire reconnue dans les 2 dernières minutes est exigée (la demande se dit à voix haute). Sinon l'action est refusée et le refus est inscrit au journal d'audit. Le code d'alarme éventuel reste dans le coffre, jamais dans les paramètres d'une demande. Détails : [HOME_ASSISTANT.md](HOME_ASSISTANT.md).

### « Toujours autoriser »

Une action 🟡 peut être approuvée avec la case « Toujours autoriser » : elle s'exécute ensuite sans demande. Jamais pour :

- une action 🔴 ;
- une action marquée non autorisable : clic à l'écran (`pc.fenetre.activer`, `minimiser`, `restaurer`), navigateur, outil MCP dont l'effet n'est pas connu d'avance ;
- `ollama.demarrer`.

La liste et le retrait sont dans Réglages › Sécurité › Toujours autorisé.

### Règles de protection

`securite/regles.py`, Réglages › Sécurité › Règles de protection. Deux genres, avec un motif à jokers cherché n'importe où dans le nom, le résumé ou les paramètres de l'action (sans accents ni majuscules) :

- **interdire** (« ne touche jamais à X ») : l'action est refusée, quel que soit son niveau, même déjà approuvée ;
- **demander** (« demande-moi avant Y ») : l'action passe toujours par une demande, même 🟢 ou « toujours autorisée ».

Retirer une règle est une action 🟡. JARVIS peut proposer une règle sous une réponse ; elle n'est ajoutée que sur votre clic.

## Arrêt d'urgence

`securite/urgence.py`. Bouton « Arrêt d'urgence » de la barre du HUD, commande `/urgence` (alias `/stop`) ou palette Ctrl+K, avec confirmation.

- **Déclencher est 🟢** : n'importe quel appareil autorisé peut tout arrêter, tout de suite (`POST /v1/urgence/arreter`).
- Les réponses en cours sont **annulées** (la CLI d'IA est tuée), une extinction du PC planifiée est annulée, puis **toute écriture est refusée** (HTTP 423, « Arrêt d'urgence actif : aucune écriture n'est acceptée »), sauf ce qui sert à le lever ou à retirer un accès (demandes, clés d'accès, appareils, autorisations, règles).
- Recettes, tâches de nuit et accueil du matin ne se lancent pas ; les connecteurs maison et le contrôle du PC n'envoient plus aucune commande.
- L'état est gardé en base : il **survit à un redémarrage**.
- **Lever est 🔴** (clé d'accès). Secours si la clé est perdue : `jarvis2 lever-urgence` sur le PC, qui exige l'accès au propriétaire de la base (identifiants du `.env` avec PostgreSQL, fichier de la base avec SQLite), est journalisé 🔴, puis redémarrer le Core.

## Journal d'audit

`securite/audit.py`. Réglages › Sécurité › Journal d'audit ; `jarvis2 verifier-audit` en ligne de commande.

- **Ajout seul, chaîné** : chaque entrée porte l'empreinte SHA-256 de la précédente ; `jarvis2 verifier-audit` recalcule la chaîne et indique l'entrée altérée (« ALTÉRATION du journal d'audit détectée à l'entrée … »).
- **Rôles séparés avec PostgreSQL** : la table appartient à un rôle d'audit distinct, sans connexion ; le rôle applicatif du Core n'écrit que par la fonction `audit_ajouter()` et ne peut ni modifier ni effacer une entrée ; des déclencheurs refusent `UPDATE`, `DELETE` et `TRUNCATE`.
- **Avec SQLite**, qui n'a pas de rôles : des déclencheurs refusent `UPDATE` et `DELETE`. Qui a accès au fichier peut les retirer, mais toute altération est détectée par la chaîne. Pour une séparation forte, utilisez PostgreSQL.
- Les secrets sont masqués avant d'entrer dans le journal ; certains textes n'y entrent jamais (texte de la dictée, texte d'un lien `jarvis://dire`, lieu de l'accueil du matin).

## Barrière d'injection par tour

`securite/barriere.py`, seul endroit où un tour est marqué et où un refus est décidé.

Un **tour** est une unité de travail menée par un modèle : une réponse du dialogue (ou d'une recette), une mission, un conseil, une exécution d'atelier. Dès que ce tour lit du contenu qui ne vient pas de vous, il est **contaminé** :

- une page ou une recherche web ;
- une source scientifique en ligne ;
- une capture d'écran ou une image (OCR, vision) ;
- un fichier externe ;
- un contenu partagé reçu (« Partager vers JARVIS ») ;
- la sortie d'une autre session ou d'un atelier ;
- le résultat d'un outil MCP ;
- des fiches de connaissances bâties sur des sources externes.

Jusqu'à la fin du tour :

- les **lectures** restent permises ;
- les actions 🟡 et 🔴 du registre, et les actions 🟢 qui écrivent ou envoient, sont **refusées**, même « toujours autorisées » ;
- les propositions du pilotage qui agissent sont marquées bloquées (bouton « Lancer moi-même », jamais appliquées seules) ;
- dans un atelier, les outils autres que la lecture sont refusés.

Chaque refus donne sa raison, laisse une entrée d'audit `barriere.action_refusee` et un bandeau « Barrière d'injection » sous la réponse. **Un clic de votre part, hors de tout tour, n'est jamais bloqué.**

Le contenu reçu de l'extérieur est en plus encadré comme non fiable (`<contenu_recu non_fiable>`), avec la consigne de n'y suivre aucune instruction.

### Détecteur d'« exécution inventée »

`securite/invente.py`. Une réponse qui affirme avoir agi (« j'ai envoyé », « a bien été supprimé », « I've sent »…) est confrontée au journal réel du tour (entrées d'audit, outils exécutés). Sans action correspondante : avertissement sous la réponse et entrée d'audit 🟡 `dialogue.execution_inventee`. La réponse n'est jamais modifiée.

## Confidentialité de la mémoire

`memoire.py`. Chaque souvenir et chaque bloc de mémoire a un **niveau**, visible et modifiable dans la vue Mémoire :

| Niveau | Vers un moteur externe |
|---|---|
| **Public** | part partout : noyau, blocs, souvenirs trouvés, nouveautés |
| **Semi-privé** (défaut d'un souvenir) | part seulement s'il est trouvé pertinent pour le message ; jamais dans le noyau, les blocs ni les nouveautés |
| **Privé** | ne part **jamais** |

Invariant : niveau « privé » ⇔ confidentialité `local_uniquement`. Les deux colonnes restent synchronisées.

En plus des niveaux, dans `config.toml` :

- `[confidentialite] sujets_exclus` : toute phrase qui nomme ces sujets est retirée de la mémoire injectée au modèle, quel qu'il soit ;
- `[confidentialite] sujets_prives` : un message qui les nomme (ou auquel répondent des souvenirs privés) n'est confié qu'à une **IA locale** par le routeur ; s'il n'y en a aucune, la réponse est refusée plutôt que de laisser sortir le message.

Quand vous changez d'avis, « J'ai changé d'avis » **remplace** le souvenir (l'ancien reçoit une date de fin, rien n'est effacé ; ses versions restent consultables).

## Ce qui ne part jamais vers un moteur externe

Un connecteur est « externe » quand les données quittent le PC (Claude Code, Codex, Antigravity, API Anthropic, OpenAI, Gemini, OpenRouter, point d'accès non local). Pour lui :

- les souvenirs **privés** (`local_uniquement`), et les semi-privés non pertinents ;
- les réponses d'une IA locale bâties sur des souvenirs privés : remplacées par « (réponse confidentielle produite par une IA locale : masquée pour les IA externes) » ;
- les **secrets et données personnelles** de tout le texte envoyé (consignes, mémoire, historique, message), remplacés par une étiquette lisible par `securite/filtre.py` : clés d'API et jetons, clés privées, mots de passe, IBAN et cartes bancaires (contrôle de Luhn), numéros de sécurité sociale, e-mails, téléphones… La conversation stockée et les IA locales gardent le texte d'origine ;
- les **images jointes**, tant que vous n'avez pas donné l'accord une fois pour ce connecteur (révocable dans Réglages › Sécurité › Où partent mes données) ;
- les sujets exclus.

Restent toujours locaux : la consolidation nocturne de la mémoire (sinon elle est ignorée : « aucune IA locale disponible : rien ne quitte le PC »), la description d'une capture d'écran (OCR puis modèle de vision local), la transcription de la voix, les empreintes de reconnaissance de votre voix.

Les connecteurs par **programme officiel** (Claude Code, Codex, Antigravity) tournent dans un dossier temporaire vide, avec un environnement sans clé d'API ni secret de JARVIS ; JARVIS ne lit, ne copie ni ne stocke jamais leurs fichiers d'identifiants. Le moteur `claude_code` refuse toute réponse dont la source d'authentification n'est pas votre abonnement.

La page **Où partent mes données** (Réglages › Sécurité) est générée depuis votre configuration réelle : pour chaque fonction, le service contacté, ce qui part, ce qui ne part jamais, et où la désactiver.

## Autres garde-fous

- **Ateliers Claude Code** : chaque atelier travaille dans son propre worktree git. Écriture hors du worktree refusée (chemins résolus avant comparaison), jamais d'écriture dans `.git` ni dans un `.env` ; commandes et accès réseau soumis à votre décision en direct ; fusion 🟡 dans le projet.
- **Créations** : pages HTML servies dans un bac à sable (CSP `sandbox`, aucune requête réseau, lien signé de 10 minutes).
- **Liens `jarvis://`** : liste blanche, jamais plus qu'une action d'interface 🟢 ; rien n'est exécuté ni envoyé seul.
- **Reconnaissance de votre voix** (désactivée par défaut) : activée, une action 🟡🔴 dite à voix haute n'est acceptée que si la voix est reconnue.
- **Skills `SKILL.md`** : importés `non_fiable`, capacités dangereuses (shell, réseau, écriture) bloquées sans revue, empreinte du dossier recalculée à chaque usage (un changement bloque le skill), scripts lancés sans clés d'API ni secrets : voir [EXTENSIONS.md](EXTENSIONS.md#skills).
- **Widgets du HUD** : un fragment généré par le modèle est validé contre des listes fermées (balises, attributs, classes, adresses internes) et réécrit par le Core ; le moindre écart écarte le widget entier. L'interface le filtre encore (DOMPurify) puis le construit avec React, jamais avec `innerHTML`.
- **Wyoming et satellites vocaux** (désactivés par défaut) : serveur sur 127.0.0.1 tant que vous ne choisissez pas une autre adresse du réseau local ; Home Assistant seulement depuis une adresse autorisée ; une clé par satellite, montrée une fois, dont la base ne garde que l'empreinte SHA-256 ; seul l'audio après le mot d'éveil est lu, le reste est jeté.
- **Routeur par type de tâche** : une route « privée » ne part jamais vers un moteur externe.
- **Ollama** n'est jamais démarré automatiquement ; JARVIS n'arrête que l'Ollama qu'il a lui-même lancé.
- **Mode sans écran** : capture, clics et contrôle de l'écran refusés par le Core lui-même.

## Hors champ

Un attaquant qui contrôle déjà votre session sur le PC (accès aux fichiers, au coffre, à la base SQLite) n'est pas arrêté par JARVIS : l'audit permet alors de détecter, pas d'empêcher.
