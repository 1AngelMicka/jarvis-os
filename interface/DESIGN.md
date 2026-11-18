# Système de design de l'interface JARVIS 2

> Reprend le système de design de JARVIS v1 (son `static/DESIGN.md` reste la référence détaillée). Ce document dit ce qui est repris, ce qui change et les règles à tenir.

## Intention

Un **poste de commandement holographique** : fond spatial quasi noir, lignes et lueurs cyan, typographie technique condensée. Une seule pièce spectaculaire, le **noyau** (réacteur) ; tout le reste est sobre, lisible et dense. Création originale, aucun élément de marque tiers.

## Tokens (`src/styles/tokens.css`)

Copiés **tels quels** de l'ancien `css/hud.css` (section 1) :
- couleurs en **canaux RVB** (`--c-cyan: 107 230 255`, utilisés en `rgb(var(--c-cyan) / .16)`) : un thème ne redéfinit que ces canaux ;
- polices système : `--f-affiche` DIN Condensed / Bahnschrift Condensed, `--f-ui` DIN Alternate / Bahnschrift, `--f-texte`, `--f-mono` ;
- échelle `--t-micro` 11 → `--t-geant` 52 px (× `--k`, agrandie à 1800 et 2300 px) ;
- grille de 4 px `--e-1` 2 → `--e-10` 56 px ; rayons `--r-*` ; traits `--l-*` ; cible tactile `--cible` 44 px ;
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
5. Animations en `transform` / `opacity` ; `html[data-animations="reduites"]` coupe les rotations et la dérive de la grille.
6. Ne jamais livrer une interface sans l'avoir chargée en vrai : console vide, aucun débordement à 375, 1280 et 1920 px.
7. Le noyau au repos affiche « Prêt ».
