# Home Assistant et satellites vocaux

JARVIS 2 peut piloter votre maison par **Home Assistant** et parler par des **satellites** posés dans les pièces. Le principe ne change pas : **le PC reste le cerveau**. Home Assistant exécute les commandes que JARVIS a décidées (et que vous avez approuvées) ; les satellites ne font qu'écouter le mot d'éveil, puis envoyer votre phrase au PC, qui transcrit, répond et parle.

Tout est **désactivé par défaut** et se règle dans **Réglages › Connecteurs › Maison**.

## 1. Relier JARVIS à Home Assistant

1. Dans **Maison › Home Assistant**, saisissez l'adresse de Home Assistant, par exemple `http://homeassistant.local:8123`. Seules les adresses du réseau local, de Tailscale ou de ce PC sont acceptées : vos jetons ne partent jamais vers un service en ligne.
2. Choisissez la liaison :
   - **Serveur MCP (conseillé)** : dans Home Assistant, ajoutez l'intégration **« Model Context Protocol Server »** et exposez à Assist les entités que JARVIS peut voir. Puis, dans JARVIS, cliquez **« Connecter (serveur MCP) »** : la page d'autorisation de Home Assistant s'ouvre (OAuth avec PKCE). Acceptez ; vous revenez dans JARVIS. Le jeton de rafraîchissement est rangé dans le **coffre** de ce PC (chiffré par Windows), jamais en base ni au journal.
   - **API REST (repli)** : dans votre profil Home Assistant, créez un **jeton d'accès longue durée** et collez-le dans « Jeton longue durée ». Il va au coffre. Avec un jeton, JARVIS vérifie chaque entité avant d'agir (domaine, type de couverture) ; c'est aussi le seul chemin pour l'alarme.
3. Facultatif : le **code de l'alarme**, rangé au coffre et lu seulement au moment de désarmer (jamais dans une demande ni au journal).
4. **Tester**, puis **Activer**. Désactivé, aucune commande Home Assistant n'existe pour JARVIS.

## 2. Ce que JARVIS peut faire, et ce qu'il demande

Le niveau est décidé par JARVIS selon le **domaine** de l'entité, jamais par Home Assistant ni par l'IA :

| Niveau | Commandes | Ce qu'il faut |
|---|---|---|
| 🟢 | Lire l'état de la maison | rien |
| 🟡 | Lumières (`light.`), prises (`switch.`), média (`media_player.`) | votre accord (un clic, ou « toujours autoriser ») |
| 🔴 | Serrures (`lock.`), alarme (`alarm_control_panel.`), portail et porte de garage (`cover.` de type `gate` ou `garage`) | votre **clé d'accès** ET votre **voix** |

Pour une action 🔴 : dites-la à voix haute (« Jarvis, ouvre le portail »). La **reconnaissance du propriétaire** (Réglages › Voix & écoute) doit être activée, avec votre voix enregistrée : si elle est coupée ou indisponible, l'action est **refusée**. JARVIS exige une phrase reconnue comme la vôtre dans les 2 dernières minutes, puis votre clé d'accès pour approuver ; juste avant d'agir, il vérifie encore que la reconnaissance est disponible.

Une action vise une seule entité du bon domaine : « allumer une prise » ne peut pas ouvrir une serrure, et un volet n'est pas un portail. Chaque étape va au journal d'audit ; l'**arrêt d'urgence** bloque toute commande, même déjà approuvée.

## 3. Prêter la voix de JARVIS à Home Assistant (Wyoming)

JARVIS offre sa transcription (Whisper, sur le PC) et sa voix (Piper, ou la voix choisie) en **protocole Wyoming**.

1. Dans **Maison › Voix pour la maison (Wyoming)**, cochez « Écouter aussi le réseau local » si Home Assistant tourne sur une autre machine, et indiquez son **adresse IP** dans « Adresses de Home Assistant autorisées ». Seules ces adresses (et ce PC) peuvent utiliser le service.
2. **Démarrer**. L'adresse à donner s'affiche (port 10300 par défaut).
3. Dans Home Assistant : **Paramètres › Appareils et services › Ajouter une intégration › Wyoming Protocol**, avec l'adresse du PC et le port. JARVIS apparaît comme moteur de reconnaissance vocale et de synthèse, à choisir dans votre pipeline Assist.

Rien n'est gardé : ni l'audio, ni le texte.

## 4. Satellites dans les pièces

Un satellite (Home Assistant Voice, ESP32-S3 sous ESPHome, ou tout appareil qui parle Wyoming) écoute le mot d'éveil **lui-même**. Seul l'audio **après l'éveil** part vers le PC ; ce qui arriverait avant est jeté sans être lu.

1. Dans **Maison › Satellites et pièces**, donnez un nom et une pièce, puis **Ajouter**. La **clé** de l'appareil s'affiche **une seule fois** : recopiez-la dans le satellite. JARVIS n'en garde que l'empreinte ; « Retirer » révoque l'appareil.
2. Le satellite se connecte au serveur Wyoming de JARVIS et commence par l'événement `jarvis-satellite` avec son identifiant et sa clé (extension de JARVIS au protocole). Ensuite, à chaque éveil : `detection` (ou `run-pipeline`), puis `audio-start`, `audio-chunk`…, `audio-stop`. JARVIS répond `transcript`, puis sa réponse parlée (`audio-start`, `audio-chunk`, `audio-stop`).
3. Les satellites qui passent par Home Assistant (pipeline Assist avec JARVIS comme moteur Wyoming) fonctionnent aussi, sans clé propre : c'est alors Home Assistant qui est autorisé.

Ce que fait JARVIS pour chaque satellite :
- **Déblocage après 25 s** : sans fin de phrase 25 s après l'éveil, il renvoie `error` (code `delai`) et repart en veille ; le satellite ne reste jamais bloqué en écoute.
- **Plafond de volume** : la voix de JARVIS n'y dépasse jamais le plafond choisi (et celui du profil de la personne qui parle, s'il est plus bas).
- **Minuteurs sur le satellite d'origine** : « Jarvis, minuteur de 5 minutes » est compris sur place, sans IA ; `timer-started` puis `timer-finished` partent vers le satellite qui l'a demandé, pas ailleurs.
- **Présence par pièce** : chaque phrase note la pièce, l'heure et la personne reconnue ; une pièce est « occupée » 10 minutes. Rien d'autre n'est gardé.

## 5. Profils par personne

Dans **Maison › Profils par personne**, ajoutez les autres voix de la maison et enregistrez leur voix (6 secondes, empreinte calculée et gardée sur ce PC, jamais l'audio). Un profil sert à la présence par pièce et à son plafond de volume. **Un profil n'est jamais vous** : une phrase plus proche d'un profil que de votre voix ne compte jamais comme la vôtre, si bien qu'un autre membre de la maison ne peut pas ouvrir une serrure en se faisant passer pour vous. Retirer un profil retire ses empreintes.

## 6. Où partent les données

La page **Où partent mes données** l'indique : Home Assistant reçoit seulement les commandes que vous approuvez et les demandes de lecture d'état (catégorie « réseau privé ») ; le serveur Wyoming renvoie le texte et la voix à l'appareil qui a parlé, sans rien garder.

## Dépannage

- **« Serveur MCP absent »** : ajoutez l'intégration « Model Context Protocol Server » dans Home Assistant, ou passez en « REST seulement » avec un jeton longue durée.
- **« Action 🔴 refusée : la reconnaissance du propriétaire est indisponible »** : activez-la dans Voix & écoute, téléchargez son modèle et enregistrez votre voix.
- **« Client non autorisé »** côté Wyoming : ajoutez l'adresse IP de Home Assistant aux adresses autorisées.
- **« Satellite non autorisé »** : clé mal recopiée ou satellite retiré ; ajoutez-le de nouveau pour obtenir une nouvelle clé.
