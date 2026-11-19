# Inspirations : le meilleur des autres assistants

JARVIS 2 s'inspire de plusieurs projets d'assistants personnels. **Aucun n'est installé ni requis** : chaque idée retenue est réimplémentée dans JARVIS 2. Les outils tiers (Ollama, Piper, modèles…) sont seulement proposés, facultatifs, avec l'accord de l'utilisateur. Les garde-fous de JARVIS (🟢🟡🔴, audit, arrêt d'urgence) ne changent pas.

## Licences : ce qu'on peut reprendre

| Projet | Licence | Ce qu'on peut reprendre |
|---|---|---|
| OpenJarvis | Apache-2.0 | code, avec mention dans `NOTICE` |
| ASDprogrammer521/jarvis | MIT | code, avec copyright |
| akshayaggarwal99/jarvis | MIT | code, avec copyright (pas son ffmpeg versionné, LGPL/GPL) |
| lancejames221b/jarvis | MIT | code, avec copyright |
| microsoft/JARVIS (HuggingGPT) | MIT | code, avec copyright |
| TopMyster/jarvis | MIT | code, avec copyright |
| b1-loop | MIT | code, avec copyright |
| sosoj92/jarvis | MIT | code, avec copyright (ex. filtre d'hallucinations) |
| DonJyde/jarvis | MIT | code, avec copyright |
| livekit-rtc (AudioProcessingModule) | Apache-2.0 | dépendance possible |
| Dodaios | Apache-2.0 | code ; **nom et logo interdits** |
| isair/jarvis | non commercial | **idées seulement** : aucune ligne de code, prompt ni texte de spécification |
| ethanplusai/jarvis | non commercial | **idées seulement** |
| amanimran786/jarvis-ai | AGPL | **idées seulement** |
| Jarvis Automation | AGPL | **idées seulement** |
| NeyorDEV/jarvis | GPL | **idées seulement** |
| Piper (OHF-Voice/piper1-gpl) | GPL-3.0 | lancé comme **processus séparé** (sous-processus ou service Wyoming), jamais importé |
| Autres dépôts sans licence claire (hasibjaan, jarvis799, Jarvis.sh…) | — | **idées seulement** |

Toute ligne de code reprise d'un projet permissif est signalée dans `NOTICE` (et `THIRD_PARTY_LICENSES` si besoin), avec son copyright.

**À ne pas reprendre** :
- le modèle openWakeWord « hey_jarvis » (CC BY-NC-SA) ;
- les voix « clone de Jarvis » et les répliques des films ;
- Edge TTS (service non officiel) ;
- Porcupine (clé payante) ;
- InsightFace (modèles non commerciaux) ;
- wyoming-satellite (archivé).

## Les meilleures idées et où elles vont

Le détail de chaque point est dans [PLAN.md](PLAN.md) : phase 13 (lots), phase 14, et l'objectif transversal « le meilleur dépôt GitHub du genre ».

| Domaine | Meilleure source | Rangé dans |
|---|---|---|
| Installation : winget/brew, reprise après coupure, téléchargements en arrière-plan avec marqueurs d'état, une seule table matériel → modèle | OpenJarvis | Phase 14 · A |
| Point d'entrée pipx | TopMyster | Phase 14 · A |
| Éveil en deux étages (tampon, alias des erreurs de Whisper, juge d'intention local) | isair (idée) | Lot K |
| Relance sans mot d'éveil, machine à états actif / veille | lancejames | Lot K |
| Coupure quand on parle par-dessus, annulation d'écho (APM livekit), repli sans annulation d'écho | livekit, b1-loop | Lot K |
| Reconnaissance du propriétaire (ECAPA-TDNN), fermée pour 🟡🔴 si indisponible | lancejames | Lot K |
| Transcription robuste (VAD, anti-hallucinations, disjoncteur), filtre des hallucinations françaises | Akshay, sosoj92 | Lot K |
| Synthèse neuronale locale (Piper en processus séparé), jamais muet | — | Lot K |
| Latence mesurée étape par étape (Ollama par 127.0.0.1, préchauffage, keep_alive) | b1-loop | Lot K |
| Fin de tour (Smart Turn), transcription anticipée | Dodaios (idée) | Lot K |
| Dictée globale Windows | Akshay | Lot K |
| Veille des sessions Claude Code de l'utilisateur (lecture seule) | — | Lot I |
| Jauges d'abonnement 5 h / 7 jours, pied de réponse (moteur, durée, jetons, énergie) | OpenJarvis | Lot N |
| Barrière d'injection par tour, approbation liée au plan exact, pile d'annulation | ASD | Phase 14 · B |
| Détecteur d'exécution inventée | — | Phase 14 · B |
| Ateliers en bac à sable réel (refus si indisponible) | aman (à l'inverse) | Phase 14 · B |
| Brainstorm → spec → plan à cases → exécution ; missions en graphe | microsoft/JARVIS | Phase 14 · B |
| Routeur par type de tâche (petit classifieur local) | — | Phase 14 · B |
| Skills SKILL.md avec confiance, empreinte, confinement ; MCP persistant et outils choisis par sens | OpenJarvis, NeyorDEV (idée) | Phase 14 · B |
| Commandes rapides sans LLM, éditables | Jarvis.sh (idée, sans eval) | Lot F |
| « Toujours autoriser » pour 🟡 (jamais pour les clics), 🔴 jamais à distance sans clé | sosoj92 | Lot F |
| Contrôle du PC (volume, luminosité, fenêtres, média), modes qui changent vraiment Windows, OCR d'abord | ASD | Lot J |
| Actions vérifiées en relisant l'état | jarvis799 (idée) | Lot J |
| Téléphone : Web Push, « Partager vers JARVIS », appel de décision 🔴 oui / non | — | Lot M |
| Masquage des secrets étendu (Luhn, clés connues, JWT…), niveaux de confidentialité, porte de rappel sans LLM, fait remplacé quand on change d'avis | OpenJarvis (idée, réimplémentée) | Phase 14 · C |
| Page « Où partent mes données » | — | Phase 14 · C |
| Orbe de particules (shader, grille spatiale, 5 états, réagit à la voix) ; HUD séparé du fil audio | — , hasibjaan (idée) | Lot P |
| Widgets générés filtrés (DOMPurify, liste fermée) | DonJyde | Phase 14 · D |
| Hue, OBS, Home Assistant (Wyoming, MCP de HA, satellites), mode sans écran | — | Phase 14 · D |
| Home Assistant piloté par son serveur MCP, satellites Wyoming (éveil sur l'appareil, minuteurs, plafond de volume), profils par voix | Home Assistant, protocole Wyoming (idées, protocoles publics réimplémentés ; ni la bibliothèque `wyoming` ni wyoming-satellite) | Phase 14 · D 18 |
| Préréglages à l'installation (chat, code, recherche, matin) | OpenJarvis | Lot L |

## À éviter

- Télémétrie ou statistiques activées par défaut.
- Mise à jour forcée.
- Confirmation par mots-clés.
- Transcription envoyée au cloud par défaut.
- Tout ce qui suppose une carte NVIDIA (CUDA) : JARVIS détecte CUDA, ROCm ou le processeur. Les cartes AMD récentes ont des roues ROCm pour CTranslate2 sous Windows, et whisper.cpp Vulkan est une autre voie.

## Point à décider par l'utilisateur

« JARVIS » est un nom lié à Marvel, et un autre projet annonce un « Jarvis 2.0 ». Rien ne change pour l'instant ; le choix du nom reste à l'utilisateur.
