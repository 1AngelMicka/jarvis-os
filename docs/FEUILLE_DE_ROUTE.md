# Feuille de route

Vue d'ensemble publique de l'avancement de JARVIS 2. Le détail de chaque phase (contenu, critères « terminé », ce qui a été vérifié en vrai) est dans le [plan](PLAN.md) ; les choix techniques dans les [décisions](DECISIONS.md) ; ce qui a changé version par version dans le [CHANGELOG](../CHANGELOG.md).

Chaque phase est utilisable seule. Les numéros renvoient aux sections du plan.

## Fait

| Phase | Contenu |
|---|---|
| 1. Socle | Configuration sans secret dans git, PostgreSQL + pgvector, migrations, rôles séparés, journalisation, tests |
| 2. Parler à JARVIS | Registre de moteurs (Claude Code par l'abonnement de l'utilisateur, Ollama), télémétrie, dialogue en flux, écran HUD |
| 3. Souvenirs | Importeur générique en lecture seule, recherche hybride, noyau injecté, souvenirs privés jamais envoyés à un moteur externe |
| 4. Sécurité, appareils, approbations | Permissions 🟢🟡🔴, file d'approbations, audit en ajout seul, arrêt d'urgence, filtre des secrets, jetons par appareil, clés d'accès |
| 5. Connecteurs d'IA | Comptes par CLI officielle, clés d'API, modèles locaux, routeur, conseil multi-IA |
| 6. Installation pour tous | Mode navigateur, assistant de premier lancement, `jarvis2 docteur`, SQLite par défaut, jumelage du téléphone, scripts d'installation — reste à essayer par l'utilisateur : macOS, téléphone via Tailscale |
| 7. Agents | Recettes planifiées, missions sourcées, sujets privés en local, client MCP sous approbation |
| 8. Mémoire v2 | Classement RRF + importance, blocs éditables, consolidation locale, oubli par archivage, export Markdown, banc d'évaluation, `BAAI/bge-m3` |
| 9. Ateliers Claude Code | Un worktree git par atelier, autorisations par JARVIS, fusion approuvée |
| 10. Voix, vision, créations | Transcription locale, mot d'éveil, mains libres, vision sur demande, créations en bac à sable — reste à essayer par l'utilisateur : l'échange vocal complet au micro |

Reporté depuis ces phases (voir le plan) : compétences SKILL.md, serveur MCP de JARVIS, OAuth des serveurs MCP distants ; reclasseur, entités légères, types faits / opinions / épisodes ; bac à sable Docker des ateliers ; Wyoming / Home Assistant.

## En cours

### 11. Application, installeurs, publication

Fait : coque de bureau Tauri 2, installeurs Windows, macOS et Linux construits par GitHub Actions en version brouillon, dépôt public.
À venir : installeurs signés et mises à jour signées (certificats à fournir), publication d'une version, essai macOS.

### 12. Bascule de l'installation personnelle

Outils prêts : sauvegarde chiffrée hors du PC, vérification par restauration, rattrapage rejouable depuis JARVIS v1. Le reste relève de décisions de l'utilisateur.

### 13. Tout JARVIS v1, en mieux

| Lot | État |
|---|---|
| A. Historique (recherche, renommer, épingler, archiver, titre et résumé) | livré |
| B. Mémoire visible (vue Mémoire, nouveautés, « JARVIS a appris ») | livré |
| C. Chantiers et activité | livré |
| D. Profil guidé | livré |
| E. Dialogue avancé (images jointes, Ctrl+K, commandes « / ») | livré |
| F. JARVIS pilote l'interface | fait |
| G. Réglages par catégories | fait |
| H. Connaissances et sources scientifiques | livré |
| I. Ateliers (pause, relance, clôture, conflits, veille des sessions) | fait — reporté : notification poussée vers un téléphone dont l'interface est fermée |
| J. Ressources et contrôle du PC, mode jeu | fait — non essayé en vrai : les réglages eux-mêmes et le démarrage réel d'Ollama |
| K. Voix (éveil en deux étages, synthèse, coupure, transcription robuste, reconnaissance du propriétaire, dictée) | fait — reste : modèle openWakeWord « Dis Jarvis », essais au micro par l'utilisateur |
| L. Accueil du matin | fait |
| M. Bureau et téléphone (`jarvis://`, Web Push, partages, appel de décision) | fait |
| N. Coûts et transparence | fait — énergie non mesurable pour l'instant |
| O. Amélioration continue | fait — reporté : suggestions automatiques hors conversation |
| P. Thème « Présence » | fait |

« Livré » : présent dans le code et le [CHANGELOG](../CHANGELOG.md), sans compte rendu détaillé dans le plan. La phase sera terminée quand chaque capacité de JARVIS v1 aura été vérifiée en vrai.

### 14. Le meilleur des autres

Idées reprises d'autres assistants personnels, réimplémentées (sources et licences : [INSPIRATIONS.md](INSPIRATIONS.md)).

| Point | État |
|---|---|
| A1. Installeurs complets (winget / Homebrew, reprise, Ollama proposé) | fait |
| A2. Gros téléchargements en arrière-plan, jamais sans accord | fait |
| A3. Une seule table matériel → modèle (AMD compris) | livré |
| A4. Point d'entrée pipx | livré |
| A5. Signature du code, mises à jour signées, paquets winget et Homebrew | à venir |
| B6. Barrière d'injection par tour | fait |
| B7. Approbation liée à l'empreinte du plan, pile d'annulation | à venir |
| B8. Détecteur d'« exécution inventée » | fait |
| B9. Ateliers dans un vrai bac à sable sous Windows | à venir |
| B10. Brainstorm → spec → plan à cases → exécution ; missions en graphe | à venir |
| B11. Routeur par type de tâche (petit classifieur local) | à venir |
| B12. Skills SKILL.md importables sous confiance ; MCP amélioré | à venir |
| C13. Masquage des secrets étendu | livré |
| C14. Niveaux public / semi-privé / privé, « J'ai changé d'avis » | fait |
| C15. Page « Où partent mes données », accord avant d'envoyer une image | livré |
| D16. Widgets générés à la demande dans le HUD | à venir |
| D17. Connecteurs Philips Hue et OBS | fait |
| D18. Home Assistant (Wyoming, MCP, satellites, profils par voix) | à venir |
| D19. Mode serveur sans écran | fait |

## À venir : le dépôt

Objectif transversal du plan, traité au fil des phases :

- README en anglais avec `README.fr.md`, interface traduisible (anglais en plus du français) ;
- GIF de démonstration réel, captures dans les thèmes et sur téléphone, tableau « ce qui tourne en local / ce qui sort », matériel requis dit honnêtement ;
- documentation : installation par système, dépannage, architecture, sécurité et permissions, écrire un skill, une commande ou une recette, FAQ ;
- badges, tests et banc mémoire publiés, CHANGELOG tenu, versions sémantiques, notes de version honnêtes ;
- communauté : [CONTRIBUTING](../CONTRIBUTING.md), [code de conduite](../CODE_OF_CONDUCT.md), modèles d'issues et de demandes de fusion, Discussions, étiquettes « good first issue » ;
- installeurs signés dès que les certificats sont fournis.

## Plus tard, facultatif

- Passerelle de messagerie (Telegram / Signal, avec jumelage des expéditeurs inconnus).
- Application mobile native.

Une idée qui n'y est pas ? Ouvrez une issue « Idée » (voir [CONTRIBUTING](../CONTRIBUTING.md)).
