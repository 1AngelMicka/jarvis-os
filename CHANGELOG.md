# Journal des modifications

Toutes les modifications notables de JARVIS 2 sont consignées ici.

Le format suit [Keep a Changelog 1.1.0](https://keepachangelog.com/fr/1.1.0/) et le projet suit le [versionnage sémantique](https://semver.org/lang/fr/). Tant que la version reste en 0.x, une version mineure peut changer un comportement existant ; ces changements sont signalés dans « Modifié ».

## [Unreleased]

## [0.9.0] - 2026-11-19

### Ajouté

- Barrière d'injection par tour : après lecture de contenu non fiable (web, écran, fichier, partage, MCP), les actions qui agissent sont retenues jusqu'à la fin du tour.
- Approbation liée à l'empreinte du plan exact (un plan modifié fait tomber l'approbation) ; pile d'annulation des actions 🟡 réversibles pendant 24 h, « Annuler » et `/annuler`.
- Routeur par type de tâche (code, raisonnement, rapide, privé) : classifieur local qui donne sa raison, scores sur 7 jours, rétrogradation et « Rétablir » ; avis 👍 / 👎 sous les réponses.
- Skills `SKILL.md` importables : revue des capacités dangereuses, empreinte SHA-256 vérifiée à chaque usage, exécution confinée ; sessions MCP persistantes, relance, outils choisis par le sens (11 au plus par tour).
- Missions projet : brainstorm, spec, plan à cases modifiable, exécution en graphe de dépendances (étapes en parallèle, approbation par étape).
- Ateliers dans un vrai bac à sable (conteneur sans réseau, Windows Sandbox, bubblewrap, sandbox-exec) ; refus si aucun n'est disponible.
- Home Assistant (MCP + OAuth/PKCE, repli REST), serveur Wyoming, satellites vocaux par pièce et profils par personne ; serrures, alarme et portail exigent la clé d'accès et la voix du propriétaire.
- Widgets du HUD générés à la demande, validés par listes fermées (Core et DOMPurify), épinglables ; phrase d'attente pendant les outils longs.
- Mise à jour automatique : application de bureau (signée, installation sur clic seulement) et `jarvis2 mettre-a-jour` ; indicateur « nouvelle version » désactivable.
- Interface traduisible : français et anglais (écrans principaux), langue choisie par appareil.
- Documentation : README en anglais et en français, installation, dépannage, architecture, sécurité, extensions, FAQ, Home Assistant, mises à jour ; captures et démonstration ; modèles d'issues et de PR, code de conduite.
- Historique des conversations : recherche (titres et messages), renommer, épingler, archives restaurables ; titre écrit par l'IA après le premier échange ; résumé daté de chaque conversation rangé en mémoire.
- Vue Mémoire : chronologie par jour, filtres par origine, recherche, rendu Markdown ; nouveautés de la mémoire au début de chaque conversation (rien de privé vers une IA externe) ; notification « JARVIS a appris ».
- Connaissances : domaines (carte, fiches, questions de contrôle, niveau, journal), extraction après chaque mission de recherche, révision ; vue Savoir.
- Sources scientifiques pour les missions : OpenAlex, arXiv, PubMed, Europe PMC.
- Dialogue : images jointes (coller, glisser, trombone, vignettes, visionneuse) transmises aux moteurs qui les lisent, jamais gardées ; palette Ctrl+K, commandes « / », raccourcis et aide.
- Accueil du matin : météo Open-Meteo, carte du jour par appareil, lecture à voix haute, réglages et préréglages proposés à l'installation.
- Coûts et transparence : dépenses par connecteur, plafond mensuel, jauges d'abonnement Claude Code, vue Coûts et pied « Détails » sous chaque réponse.
- Chantiers suivis sans doublon (« C'est fait », abandon 🟡, suppression 🔴) et onglet Activité (chantiers, missions, ateliers, créations).
- Profil guidé : questionnaire par sections, réponses en mémoire, entretien vocal.
- Une seule table matériel → modèle (cartes AMD avec ROCm, Apple Silicon), conseils de modèles locaux par usage et commande `jarvis2 materiel`.
- Détecteur d'« exécution inventée » : une réponse qui prétend avoir agi sans action réelle est signalée (dialogue, missions, audit, avertissement sous la réponse).
- Vue Réglages par catégories, avec recherche et adresses directes ; animations réglables ; voix rallumable.
- Téléchargements des modèles en tâche de fond : module unique, marqueurs d'état, reprise, progression et « Réessayer » dans l'interface.
- Paquet pipx : métadonnées, LICENSE et NOTICE dans la roue, repli si l'interface est absente.
- Mode serveur sans écran (`jarvis2 serveur --sans-ecran`) et guide [docs/SERVEUR.md](docs/SERVEUR.md).
- Thème « Présence » : orbe de particules WebGL, jauge du micro, HUD en fond d'écran.
- Connecteurs maison Philips Hue et OBS, désactivés par défaut, actions 🟢🟡🔴.
- JARVIS pilote l'interface : bloc d'actions validé par le Core, règles de protection, commandes rapides éditables, « toujours autoriser » pour une action 🟡.
- Page « Où partent mes données », générée depuis la configuration réelle.
- Ateliers : pause réelle, relance, choix du modèle, clôture avec notes, conflits de fichiers entre ateliers, veille des sessions Claude Code de l'utilisateur en lecture seule.
- Amélioration continue : vue Améliorations (suggestions, réalisation en atelier, aperçu, tests, mise en service et retour arrière 🟡).
- Bureau et téléphone : protocole `jarvis://`, raccourcis globaux voix et écran, gadget de bureau, notifications Web Push, « Partager vers JARVIS », liens de fichiers à usage unique, appel de décision.
- Ressources et contrôle du PC (CPU, RAM, GPU, VRAM), Ollama démarré seulement sur demande, mode jeu, OCR avant le modèle de vision ; Réglages › PC & mode jeu.
- Voix : synthèse Piper et ElevenLabs avec file ordonnée et secours par la voix du système, coupure quand on parle par-dessus, éveil « Dis Jarvis » en deux étages et conversation vocale.
- Voix : transcription robuste, reconnaissance du propriétaire, fin de tour, mesure de la latence, transcription anticipée et dictée globale (raccourci maintenu).
- Mémoire : niveaux public / semi-privé / privé, porte de rappel sans LLM, fait remplacé quand l'utilisateur change d'avis (« J'ai changé d'avis », versions).
- Installeurs complets : winget / Homebrew, fichier d'état pour reprendre après une coupure, essai à blanc, Ollama et un premier modèle seulement proposés.
- CI : roue installée par pipx et vérifiée ; installeurs non interactifs essayés sur Windows, Ubuntu et macOS.

### Modifié

- Application : les liens vers d'autres sites s'ouvrent dans le navigateur du système.
- Interface : barre en onglets sur téléphone, onglets latéraux à 320 px ; état du Core surveillé (hors ligne puis retour) ; cache de l'interface revalidé après une mise à jour.
- Demandes : file rafraîchie seule toutes les 15 s ; une demande close entre-temps disparaît de la file au lieu d'une erreur.
- Ouvrir une conversation affiche le dialogue depuis toute vue.
- Modèles : jamais téléchargés sans accord ; leur état est lu par `jarvis2 docteur` et l'API.
- Flux de données réels affichés seulement pour les connecteurs installés.
- README : installeurs non signés et contournements expliqués.

### Corrigé

- Sources scientifiques : arXiv ne reçoit que des requêtes en anglais ; une réponse 429 au « Retry-After » court est retentée une fois.
- Images jointes : trace claire des images passées, qu'un petit modèle ne confond plus avec le message actuel.
- Savoir : disposition selon la largeur du panneau, onglet actif visible.
- Chantiers : rouvrir garde les étapes cohérentes avec la progression.
- Exécution inventée : extrait gardé avec sa casse, une phrase affichée une fois, un nom de fichier ne coupe plus la phrase.
- Conseils de modèles : libellés sans doublon.
- CLI : sortie redirigée sous Windows sans plantage de `--help` ni de `docteur`.
- Pilotage : mode écrit compatible avec les droits du rôle applicatif sous PostgreSQL.
- Un lien `jarvis://` arrivé avant le montage de la saisie ou du micro n'est plus perdu ; l'assistant de premier lancement ne masque plus un lien, un partage ou une décision.
- Bureau : page cachée jamais ralentie pour « Dis Jarvis ».
- Voix : console propre quand aucune voix locale ou aucun modèle n'est disponible (réponses 204 et 200 au lieu d'erreurs).
- Mémoire : « J'ai changé d'avis » marche aussi sans modèle d'embeddings téléchargé.
- `install.ps1` : sortie de `jarvis2 materiel` lue en UTF-8.
- Tests et CI : courses dans les tests des connaissances, état remis à zéro entre les tests PostgreSQL, dates réelles, chemins Windows, dossiers d'essai des installeurs.

### Sécurité

- Barrière d'injection par tour : dès qu'un tour a lu un contenu extérieur, les actions qui agissent sont refusées jusqu'à la fin du tour.
- Masquage des secrets étendu (cartes avec contrôle de Luhn, clés, jetons, codes) et appliqué avant le journal d'audit et le journal applicatif.
- Accueil du matin : le lieu n'apparaît plus dans le journal des requêtes HTTP.
- Accord séparé avant d'envoyer une image à un service cloud.
- Jumelage limité en nombre de tentatives.
- Amélioration continue : l'essai des tests est invalidé, et signalé, quand les tests modifient l'atelier.

## [0.8.0] - 2026-11-19

Première version étiquetée (pré-version).

### Ajouté

- Socle : PostgreSQL 16 + pgvector sous Docker, migrations, rôles de base séparés, journalisation, tests.
- Registre de moteurs ; moteurs `claude_code` (abonnement Claude Code de l'utilisateur) et Ollama ; télémétrie ; dialogue en flux SSE.
- Interface HUD (React + Vite) : écran de dialogue en flux, conversations, CSP.
- Mémoire : importeur générique en lecture seule (première source `jarvis_v1`), recherche hybride, noyau injecté dans le dialogue, configuration locale hors dépôt ; mémoire visible dans l'interface.
- Sécurité : appareils, jumelage, clés d'accès, approbations, journal d'audit chaîné, arrêt d'urgence, filtre avant les fournisseurs externes ; interface de sécurité.
- Connecteurs d'IA : comptes par CLI officielle, clés d'API, modèles locaux ; routeur sur les connecteurs actifs ; conseil multi-IA ; vue Connecteurs.
- Stockage SQLite par défaut (sqlite-vec, FTS5), même interface que PostgreSQL ; copie complète entre les deux (`jarvis2 stockage copier`), vérifiée par aller-retour.
- Diagnostic `jarvis2 docteur`, assistant de premier lancement, accueil de Claude Code avec case à cocher, PWA installable, Tailscale pour le téléphone.
- Scripts d'installation, paquet avec l'interface, documentation.
- Dépôt public : licence Apache-2.0, SECURITY, CONTRIBUTING, modèles d'issues, CI GitHub Actions.
- Thème JARVIS renouvelé et trois thèmes au choix (Studio nocturne, Atelier clair, Console épurée).
- Agents : recettes planifiées, missions sourcées rangées en mémoire, sujets privés routés en local, outils MCP sous approbation, vue Agents.
- Mémoire v2 : classement RRF + importance, blocs versionnés, oubli par archivage, consolidation locale, bascule de modèle sans interruption, export Markdown, banc d'évaluation ; `BAAI/bge-m3` utilisable.
- Ateliers Claude Code : un worktree par atelier, autorisations par JARVIS, arrêt et reprise, fusion approuvée.
- Voix locale (transcription, mot d'éveil, mains libres, lecture), vision sur demande, créations en bac à sable.
- Application de bureau Tauri 2 (fenêtre, icône de notification, raccourci), publication des installeurs en brouillon, installation en une ligne.
- Sauvegarde chiffrée hors du PC et vérification par restauration.

### Modifié

- Claude Code : abonnement générique, aucune formule d'abonnement supposée.
- Interface livrée seulement dans la roue du Core.
- Application : raccourci global facultatif (Ctrl+Maj+J, ou Ctrl+Alt+J s'il est pris) ; nom « JARVIS 2 ».

### Corrigé

- Application : plus de plantage quand le raccourci global est déjà pris.
- CI : chemins de données fixes, registre Windows vérifié par mypy seulement sous Windows, actions à jour.
- Ateliers : chemins absolus portables dans les tests (Linux), ligne trop longue.

### Sécurité

- Publication : seuls les secrets de signature réellement configurés sont transmis.

[Unreleased]: https://github.com/1AngelMicka/jarvis-os/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/1AngelMicka/jarvis-os/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/1AngelMicka/jarvis-os/releases/tag/v0.8.0
