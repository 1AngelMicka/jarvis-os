# Système de design de l'interface JARVIS 2

> Né du système de JARVIS v1 (mêmes jetons, mêmes règles d'ergonomie), mais avec sa propre identité et cinq thèmes.

## Intention

Thème par défaut **JARVIS** : un poste de commandement en **verre dépoli**. Fond quasi noir éclairé par une **aurore** cyan et violette, matrice de points discrète, panneaux arrondis à **arête lumineuse** (cyan → violet), dégradé d'accent sur les titres, les bulles de l'utilisateur et l'action principale. Une seule pièce spectaculaire, le **noyau** (réacteur) ; tout le reste est sobre, lisible et dense. Création originale, aucun élément de marque tiers.

Ce qui distingue JARVIS 2 de JARVIS v1 : plus de coins en équerre ni de tracé du contour, plus de grille de lignes en dérive (points + aurore), rayons de 8 à 14 px au lieu de 2 à 3, verre dépoli (`backdrop-filter`), second accent violet (`--c-aurore`), bulles de dialogue arrondies.

## Thèmes (`src/styles/themes.css`, `src/theme.ts`)

| Thème | Identité |
|---|---|
| **JARVIS** (défaut) | Verre dépoli, aurore cyan-violet, typographie condensée en capitales |
| **Studio nocturne** | Graphite, accent indigo-violet, cartes arrondies, typographie système, aucune lueur |
| **Atelier clair** | Papier chaud, encre, titres en sérif, accent terre cuite (`color-scheme: light`) |
| **Console épurée** | Noir et blanc, traits fins, tout en mono et en minuscules, accent lime, angles vifs |
| **Présence** | Nuit profonde, accent aqua pâle, verre léger ; le noyau devient un **orbe de particules** WebGL (`composants/Orbe.tsx`, `src/presence.ts`) |

**Orbe (thème Présence).** Cinq états : veille (« Prêt »), écoute, réflexion, parole, compactage ; alerte en rouge. Le mouvement vit dans le shader ; les teintes viennent des jetons (`--c-cyan`, `--c-cyan-vif`, `--c-bleu`, `--c-aurore`, `--c-rouge`). Densité de pixels ≤ 2. Le fil audio publie le niveau du micro, la boucle de rendu le lit : jamais l'un n'attend l'autre. Animations réduites : une image fixe. Sans WebGL : le noyau SVG. Option « HUD en fond d'écran » (Réglages › Présence) : l'orbe passe derrière tout le HUD, verre `--flou-fond`. Jetons : `--orbe`, `--orbe-compact`, `--jauge-micro`, `--jauge-micro-h`, `--flou-fond`.

Un thème ne redéfinit **que des jetons** sous `html[data-theme="…"]` : couleurs (canaux RVB), polices, rayons et interrupteurs de décor (`--lueur-k`, `--grille-k`, `--aurore-k`, `--arete-k`, `--flou`, `--casse`). Le choix est gardé par appareil (`jarvis2.theme`, stockage local), appliqué avant le premier rendu, et met à jour `theme-color` et `color-scheme`. Sélecteur : barre du haut (≥ 700 px), onglet Sécurité et vue Réglages (`#reglages/themes`). L'arrêt d'urgence passe l'accent au rouge dans tous les thèmes (rouge foncé dans le thème clair).

Contrastes mesurés dans les cinq thèmes : texte ≥ 15:1, texte secondaire ≥ 5,5:1 sur le fond et les panneaux, accent ≥ 5:1 sur le fond.

## Tokens (`src/styles/tokens.css`)

Hérités de l'ancien `css/hud.css`, puis étendus :
- couleurs en **canaux RVB** (`--c-cyan: 107 230 255`, utilisés en `rgb(var(--c-cyan) / .16)`) : un thème ne redéfinit que ces canaux ; `--c-aurore` (second accent) et `--c-neutre` (traits des thèmes sobres) ;
- polices système : `--f-affiche` DIN Condensed / Bahnschrift Condensed, `--f-ui` DIN Alternate / Bahnschrift, `--f-texte`, `--f-mono` ;
- échelle `--t-micro` 11 → `--t-geant` 52 px (× `--k`, agrandie à 1800 et 2300 px) ;
- grille de 4 px `--e-1` 2 → `--e-10` 56 px ; rayons `--r-1` 4, `--r-2` 8, `--r-3` 14 px, `--r-saisie`, `--r-rond`, `--r-pilule` ; traits `--l-*` ; cible tactile `--cible` 44 px ;
- mouvement `--d-instant` 90 · `--d-rapide` 160 · `--d-moyen` 280 · `--d-lent` 520 · `--d-cine` 900 ms ; courbes `--e-sortie`, `--e-holo`, `--e-entree` ;
- profondeur `--z-*`.

Toute valeur visuelle passe par un token ; un besoin nouveau = un token ajouté dans `tokens.css`.

## Mise en page

| Largeur | Disposition |
|---|---|
| < 900 px (iPhone) | Barre avec noyau compact, Dialogue plein écran, Conversations en feuille latérale (bouton ☰, Échap ou voile pour fermer) |
| 900 – 1279 px | Deux colonnes : noyau + État · Dialogue ; Conversations en feuille |
| ≥ 1280 px | Trois colonnes : noyau + État (264 px) · Dialogue (`minmax(0, 1fr)`) · Conversations (300 px) |
| ≥ 1800 / 2300 px | Même grille, `--k` 1,08 puis 1,18 |

Toutes les colonnes centrales sont en `minmax(0, 1fr)` et les panneaux en `min-width: 0` : c'est ce qui évite le débordement constaté à 1280 px dans JARVIS v1. Vérifié à 375, 1280 et 1920 px.

## Corrections reprises de l'audit d'ergonomie (`AUDIT_UX.md` de JARVIS v1)

- Pendant une réponse, le bouton d'envoi devient **Arrêter** (Échap) ; la requête est annulée côté Core et la CLI tuée (n° 7).
- Erreurs : un message par cas, qui dit quoi faire ; « Réessayer » si le Core est injoignable (n° 9).
- Chargement : lignes squelettes (n° 14) ; états vides qui disent quoi faire (n° 15).
- Tactile : cibles de 44 px sous `pointer: coarse` (n° 17) ; champ de saisie à 16 px sur iPhone (pas de zoom Safari).
- Accueil : « Que voulez-vous faire ? », une phrase, astuces clavier masquées en tactile (n° 20).
- Modèle et effort choisis dans la console, badge modèle + effort sous chaque réponse (n° 12).
- Démarrage : **un seul appel** `/v1/etat` (au lieu d'environ 45), requêtes dédoublonnées (`unSeul`), même en mode strict de React.

## Règles

1. Une valeur = un token. Ambre = attention, rouge = danger, vert = succès ; jamais de rouge décoratif.
2. Texte affiché via React (`TexteRiche`), **jamais** `innerHTML` ni `dangerouslySetInnerHTML` : la règle est imposée par ESLint.
3. Focus clavier toujours visible ; `Entrée` envoie, `Maj+Entrée` nouvelle ligne, `Échap` arrête ou ferme, `/` donne le focus à la saisie.
4. Un état vide dit quoi faire ; une erreur dit ce qui s'est passé et comment corriger.
5. Animations en `transform` / `opacity` ; `html[data-animations="reduites"]` (Réglages › Animations : selon le système, normales ou réduites ; `src/animations.ts`) coupe les rotations, la dérive de la grille et les entrées de panneaux.
6. Ne jamais livrer une interface sans l'avoir chargée en vrai : console vide, aucun débordement à 375, 1280 et 1920 px.
7. Le noyau au repos affiche « Prêt ».
8. Un nouveau réglage se déclare dans `src/reglages.ts` (catégorie, titre, mots-clés) et réutilise le composant qui le gère ailleurs : la vue Réglages, sa recherche et ses adresses directes le trouvent alors toutes seules.
