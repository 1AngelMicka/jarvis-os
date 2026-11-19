# Mises à jour de JARVIS 2

JARVIS ne s'installe **jamais** une nouvelle version tout seul : il peut seulement vous prévenir qu'elle existe. Chaque vérification est désactivable et figure dans « Où partent mes données » (Réglages › Sécurité).

## Le Core (`jarvis2`)

### Mettre à jour

```sh
jarvis2 mettre-a-jour          # montre la nouvelle version et ses notes, puis demande « o/N »
jarvis2 mettre-a-jour --oui    # sans question (scripts)
```

La commande interroge l'API publique de GitHub (dernière version publiée, sans compte ni jeton), compare au numéro installé, affiche les notes de version, puis, **après votre accord** seulement, installe la roue (`.whl`) jointe à la nouvelle version selon la façon dont JARVIS a été installé :

| Installation | Commande lancée |
|---|---|
| Scripts `install.ps1` / `install.sh` (uv tool) | `uv tool install --force --python 3.13 <roue de la version>` |
| pipx | `pipx install --force --python 3.13 <roue de la version>` |
| Dépôt git (développement) | rien : la commande rappelle `git pull`, `uv sync`, `npm ci` et `npm run build` |
| Non reconnue | rien : la commande affiche les deux commandes possibles |

Pourquoi pas `uv tool upgrade` : les installeurs installent la roue d'une version précise, par son adresse ; une « mise à niveau » relirait la même roue. Vos données et votre configuration ne sont pas touchées.

Arrêtez le Core (et l'application de bureau) avant : sous Windows, ses fichiers restent verrouillés tant qu'il tourne. Sous Windows, la commande se termine et la mise à jour continue dans une nouvelle fenêtre. Hors ligne ou si GitHub limite le débit, la commande le dit et ne change rien.

### L'indicateur « Nouvelle version » des Réglages

Réglages › Appareils › **Version et mises à jour** (`#reglages/version`) affiche la version installée et, s'il y en a une, « Nouvelle version X disponible », ses notes (repliables, en texte brut), la commande à lancer et le lien vers la version.

- Le Core vérifie **au plus une fois par jour**, quand cette section est ouverte ; la date de la dernière vérification est gardée en base (un redémarrage ne relance pas l'appel). Un échec (hors ligne, limite de débit) n'est pas réessayé avant le lendemain.
- Ce qui part : la demande elle-même (votre adresse IP) et l'en-tête `User-Agent: jarvis2`. Rien de personnel.
- Pour la désactiver : décochez « Vérifier les nouvelles versions (une fois par jour) » dans la même section. Plus aucun appel n'est fait.
- API : `GET /v1/mises-a-jour` (installée, dernière, nouvelle, notes, page de la version, date de vérification, active) ; `PUT /v1/mises-a-jour` avec `{"verifier": false}` ou `true`.

## L'application de bureau

L'application de bureau (Tauri) a son propre mécanisme, signé :

- elle vérifie au démarrage, puis une fois par jour, en téléchargeant `latest.json` depuis la page des versions de GitHub ;
- si une version plus récente existe, une boîte demande **« Installer et redémarrer »** ou **« Plus tard »** ; l'entrée correspondante du menu de l'icône de notification permet de l'installer plus tard. Rien n'est installé sans votre accord ;
- l'installeur téléchargé est vérifié avec la clé publique de mise à jour avant d'être lancé ;
- la case **« Vérifier les mises à jour chaque jour »** du menu de l'icône de notification coupe la vérification quotidienne ; la variable d'environnement `JARVIS2_MISES_A_JOUR=0` la désactive complètement ;
- sans clé publique configurée dans la version installée, la mise à jour est désactivée et le menu le dit.

## Pour le mainteneur : activer les mises à jour signées

À faire une fois, sur votre poste. **Le projet ne génère ni ne stocke aucune clé** : elle vous appartient.

1. Créer la paire de clés (un mot de passe est conseillé) :

   ```sh
   npx tauri signer generate -w ~/.tauri/jarvis.key
   ```

   Gardez la clé privée (`~/.tauri/jarvis.key`) **hors du dépôt** et **sauvegardée** : la perdre, c'est ne plus jamais pouvoir publier de mise à jour pour les installations existantes (elles n'accepteront que des mises à jour signées par cette clé).
2. Donner la clé **publique** (contenu de `~/.tauri/jarvis.key.pub`) à l'application : dans `app/src-tauri/tauri.conf.json`, champ `plugins.updater.pubkey`, ou bien, si le workflow le prend en charge, dans la variable de dépôt `TAURI_UPDATER_PUBKEY` (Settings → Secrets and variables → Actions → Variables). La clé publique n'est pas un secret.
3. Ajouter les secrets du dépôt (Settings → Secrets and variables → Actions → Secrets) :
   - `TAURI_SIGNING_PRIVATE_KEY` : le contenu de la clé privée ;
   - `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` : son mot de passe (vide si aucun).

   Sans ces secrets, le workflow de publication construit les installeurs mais saute `latest.json`, avec un message dans le journal.
4. Publier : une étiquette `v*` lance `.github/workflows/publication.yml`, qui crée une version **brouillon**. Une fois le brouillon publié depuis GitHub, `https://github.com/1AngelMicka/jarvis-os/releases/latest/download/latest.json` devient visible et les applications installées voient la nouvelle version (au plus tard le lendemain).

La **signature du code** (certificat Windows, signature et notarisation Apple) est un autre sujet, à la charge de l'utilisateur qui publie : elle évite les avertissements SmartScreen et Gatekeeper, pas la vérification des mises à jour. Les secrets correspondants sont listés en tête de `.github/workflows/publication.yml`.
