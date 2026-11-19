# JARVIS 2 sur un serveur domestique (sans écran)

Un mini-PC, un NAS ou une machine Linux sans écran peut faire tourner le Core en permanence ; on l'utilise depuis le
navigateur du PC ou du téléphone. Le **mode sans écran** coupe tout ce qui regarde ou pilote l'écran du serveur.

## Ce que change le mode sans écran

- **Refusé par le Core** (réponse 409 « Indisponible en mode sans écran ») : description d'une capture d'écran,
  clics et contrôle de l'écran. Le refus vient du Core lui-même, pas seulement de l'interface.
- **Interface** : le bouton « Écran » devient « Sans écran » (grisé, « indisponible en mode sans écran »), le panneau État affiche « mode sans écran ».
- **Voix** : dictée et mains libres passent par le **micro du navigateur** (PC ou téléphone) ; la transcription se
  fait sur le serveur. Aucune carte son n'est nécessaire côté serveur.
- **Démarrage** : aucune dépendance graphique ; aucun navigateur n'est ouvert sur le serveur (même avec `--ouvrir`).
- `jarvis2 docteur` l'indique (ligne « Écran »), et signale un serveur Linux sans session graphique lancé sans ce mode.

## Installation

```sh
sh install.sh --source <jarvis2-x.y.z-py3-none-any.whl> --sans-demarrer
jarvis2 serveur --sans-ecran
```

Réglage équivalent, permanent : `JARVIS2_SANS_ECRAN=true` dans `jarvis2.env` (dossier de configuration, à côté de
`config.toml`). Pour un démarrage automatique, un service systemd utilisateur suffit :

```ini
# ~/.config/systemd/user/jarvis2.service
[Unit]
Description=JARVIS 2 (Core, sans écran)

[Service]
ExecStart=%h/.local/bin/jarvis2 serveur --sans-ecran
Restart=on-failure

[Install]
WantedBy=default.target
```

```sh
systemctl --user enable --now jarvis2
loginctl enable-linger "$USER"   # le service tourne même sans session ouverte
jarvis2 docteur
```

## Sécurité : jamais exposé sans jumelage

1. **Le Core n'écoute que sur 127.0.0.1** (par défaut). Ne changez pas `JARVIS2_HOTE` et ne mettez pas
   `JARVIS2_OUVERTURE_RESEAU=true` : n'ouvrez aucun port sur la box, et n'exposez jamais le Core sur Internet.
2. **Accès à distance par Tailscale** : installez Tailscale sur le serveur et sur vos appareils (même compte), puis,
   une fois sur le serveur : `tailscale serve --bg 8765`. Le Core est joignable en HTTPS à
   `https://<nom-du-serveur>.<réseau>.ts.net`, sur votre réseau privé seulement (`tailscale serve`, jamais
   `tailscale funnel`, qui publierait sur Internet).
3. **Jumelage obligatoire** : chaque appareil doit être associé ; sans jeton d'appareil, toute l'API répond 401.
   Le serveur n'ayant pas de navigateur, associez le premier appareil :
   - soit par un code à usage unique (5 minutes), depuis une session SSH sur le serveur :
     `jarvis2 jumeler --adresse https://<nom-du-serveur>.<réseau>.ts.net`, puis ouvrez le lien affiché ;
   - soit par un tunnel SSH (`ssh -L 8765:127.0.0.1:8765 <serveur>`), puis `http://localhost:8765` sur votre PC.
   Ajoutez ensuite une clé d'accès (onglet Sécurité) : elle protège les actions 🔴.
4. Le micro du navigateur exige une page sécurisée : utilisez l'adresse HTTPS de Tailscale (ou `localhost` par le
   tunnel SSH), pas une adresse IP en HTTP.
