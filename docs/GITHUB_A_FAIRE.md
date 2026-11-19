# Réglages GitHub à faire

Ce qui se règle sur la page du dépôt et ne peut pas venir d'un commit. Ces réglages se font sur GitHub, par le propriétaire du dépôt ou à sa demande. Les cases cochées ont été faites le 2026-11-19.

Dépôt : https://github.com/1AngelMicka/jarvis-os

## 1. Présentation du dépôt

Page d'accueil du dépôt, roue dentée à droite de « About » :

- [x] **Description** proposée :
  > Assistant personnel open source, local d'abord : mémoire à long terme, IA de votre choix (Claude Code, API, Ollama), voix, téléphone, sous votre contrôle.
- [x] **Sujets (topics)** proposés :
  `assistant-personnel`, `personal-assistant`, `local-first`, `self-hosted`, `ai-assistant`, `llm`, `ollama`, `claude-code`, `long-term-memory`, `rag`, `pgvector`, `sqlite`, `fastapi`, `react`, `tauri`, `voice-assistant`, `whisper`, `privacy`, `french`
- [ ] Cocher « Releases » (et « Packages » seulement si des paquets y sont publiés) ; décocher « Deployments » s'il n'y en a pas.

## 2. Image de partage

Settings › General › Social preview :

- [ ] Créer l'image (1280 × 640 px, moins de 1 Mo, PNG ou JPG) et la ranger dans `docs/images/partage.png` (le dossier `docs/images/` est à créer) : nom du projet, une phrase, une capture réelle de l'interface, rien de personnel dans la capture.
- [ ] La téléverser dans « Social preview ».

## 3. Fonctions du dépôt

Settings › General › Features :

- [x] **Issues** : activées.
- [x] **Discussions** : à activer. Catégories proposées : Annonces, Questions, Idées, Montrez votre installation. Ensuite, décommenter le lien « Questions et échanges » dans `.github/ISSUE_TEMPLATE/config.yml`.
- [x] **Wiki** : désactivé (la documentation vit dans `docs/`).
- [ ] **Projects** : selon l'usage ; la feuille de route publique est [FEUILLE_DE_ROUTE.md](FEUILLE_DE_ROUTE.md).

## 4. Étiquettes

Issues › Labels :

- [x] Créer `bogue` et `idée` : les modèles d'issues les appliquent, une étiquette absente n'est pas posée.
- [x] Créer `good first issue` et `help wanted` s'ils manquent (noms exacts : GitHub les met en avant aux nouveaux contributeurs).
- [x] Facultatif : `sécurité`, `documentation`, `interface`, `core`, `voix`, `mémoire`, `installation`.
- [ ] Marquer quelques premières issues simples « good first issue ».

## 5. Sécurité

Settings › Code security (ou « Security » selon l'interface) :

- [x] **Private vulnerability reporting** : activer. C'est le canal décrit dans [SECURITY.md](../SECURITY.md) et dans le code de conduite ; sans lui, le lien « Report a vulnerability » n'existe pas.
- [x] **Dependabot alerts** et **Dependabot security updates** : activer.
- [x] **Secret scanning** et **Push protection** : activer (un secret poussé par erreur est bloqué ou signalé).
- [ ] **Code scanning** (CodeQL, configuration par défaut) : facultatif, à activer si souhaité.

## 6. Protection de la branche `main`

Settings › Rules › Rulesets (ou Branches › Branch protection rules), cible `main` :

- [x] Interdire la suppression et les poussées forcées.
- [ ] Exiger une demande de fusion avant toute fusion.
- [ ] Exiger que la CI passe : vérifications « Core (Python) », « Interface (TypeScript) », « Paquet (roue + pipx) » et « Installeurs (…) » (les noms apparaissent dans la liste après une première exécution).
- [ ] Exiger que la branche soit à jour avant la fusion.
- [ ] Facultatif : exiger la résolution des conversations, des commits signés.

## 7. Actions et secrets

Settings › Actions › General :

- [x] Permissions du `GITHUB_TOKEN` : lecture seule par défaut (les workflows demandent eux-mêmes ce qu'il leur faut).
- [ ] Exiger une approbation pour les workflows lancés par de nouveaux contributeurs venant de forks.

Settings › Secrets and variables › Actions, quand les certificats sont disponibles (tous facultatifs ; sans eux, les installeurs sont construits mais non signés) :

- [ ] `TAURI_SIGNING_PRIVATE_KEY` et `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` (mises à jour de l'application, clé créée par `tauri signer generate`).
- [ ] `WINDOWS_CERTIFICATE` et `WINDOWS_CERTIFICATE_PASSWORD` (signature de code Windows).
- [ ] `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID` (signature et notarisation macOS).

## 8. Publier une version

Le workflow `publication.yml` crée une version **en brouillon** à chaque étiquette `v*` : rien n'est public tant qu'elle n'est pas publiée à la main.

- [ ] Vérifier que la CI de l'étiquette est verte et que le brouillon contient la roue, `install.ps1`, `install.sh` et les installeurs.
- [ ] Rédiger les notes de version à partir de la section correspondante du [CHANGELOG](../CHANGELOG.md), en disant honnêtement ce qui n'est pas signé ou pas encore essayé.
- [x] Pour la v0.8.0 : cocher « Set as a pre-release ».
- [x] Publier.
- [ ] Après publication : vérifier que l'installation en une ligne (qui prend la roue de la dernière version publiée) fonctionne.

## 9. Ensuite

- [ ] Épingler le dépôt sur le profil, si souhaité.
- [x] Ajouter les badges (CI, licence, version) au README une fois la première version publiée.
- [ ] Revoir cette liste à chaque changement de réglages.
