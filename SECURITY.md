# Sécurité

JARVIS 2 garde la mémoire de son utilisateur et peut agir pour lui : la sécurité passe avant les fonctions.

## Signaler une vulnérabilité

**N'ouvrez pas d'issue publique.** Utilisez le signalement privé de GitHub : onglet **Security** du dépôt, puis **Report a vulnerability**. Décrivez le problème, comment le reproduire et son effet. Nous accusons réception sous 7 jours et vous tenons informé jusqu'au correctif ; votre contribution est créditée si vous le souhaitez.

## Versions prises en charge

Projet en développement : seule la dernière version de la branche `main` reçoit des correctifs.

## Ce que JARVIS garantit (et teste)

- **Local d'abord** : le Core n'écoute que sur 127.0.0.1 ; l'accès à distance passe par Tailscale (`tailscale serve`), jamais par un port ouvert par défaut.
- **Appareils** : un jeton par appareil (seule son empreinte SHA-256 est stockée), révocable ; jumelage par code à usage unique valable 5 minutes.
- **Approbations** : actions 🟡 approuvées d'un clic, actions 🔴 seulement par une clé d'accès (WebAuthn, vérification de l'utilisateur).
- **Audit** : journal en ajout seul, chaîné par empreintes SHA-256 (`jarvis2 verifier-audit`). Avec PostgreSQL, il appartient à un rôle distinct que le Core ne peut ni modifier ni vider ; avec SQLite, des déclencheurs l'empêchent et toute altération est détectée.
- **Arrêt d'urgence** : coupe les réponses en cours et refuse toute écriture.
- **Fournisseurs externes** : un filtre retire secrets et données personnelles avant tout envoi ; les souvenirs privés ne partent jamais vers une IA externe.
- **Comptes d'IA** : JARVIS appelle les programmes officiels (Claude Code, Codex, Antigravity) installés et connectés par l'utilisateur ; il ne lit, ne copie ni ne stocke jamais leurs identifiants. Les clés d'API restent dans un coffre local chiffré (DPAPI sous Windows).
- **Contenu externe = donnée, jamais instruction** : pages, fichiers et résultats d'outils ne donnent pas d'ordres.

## Hors champ

Un attaquant qui contrôle déjà la session de l'utilisateur sur le PC (accès aux fichiers, au coffre, à la base SQLite) n'est pas arrêté par JARVIS ; l'audit permet alors de détecter, pas d'empêcher.
