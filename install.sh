#!/bin/sh
# JARVIS 2 — installation sous macOS et Linux, sans Docker ni Node.
#
#   sh install.sh [--source <roue .whl, dossier core du dépôt ou URL>] [options]
#   curl -LsSf https://raw.githubusercontent.com/1AngelMicka/jarvis-os/main/install.sh | sh -s -- [options]
#
# Contrat commun avec install.ps1 (mêmes étapes, même fichier d'état, mêmes options, mêmes codes de sortie) :
#
# Étapes, dans l'ordre (chacune notée dans le fichier d'état, une étape « fait » est sautée à la relance) :
#   uv           gestionnaire Python d'Astral : Homebrew s'il est là (macOS), sinon son script officiel
#   jarvis2      `uv tool install --python 3.13` (Python géré par uv, environnement isolé, commande `jarvis2`)
#   path         dossier des commandes de uv ajouté au PATH des nouveaux terminaux (`uv tool update-shell`)
#   ollama       FACULTATIF, proposé par une case à cocher, décochée par défaut : Ollama (Homebrew sous macOS,
#                script officiel sous Linux)
#   modele       FACULTATIF, même case à cocher : premier modèle de conversation choisi par la table
#                matériel → modèle de JARVIS (`jarvis2 materiel --modele conversation`), puis `ollama pull`
#   preparation  base SQLite et modèle d'embeddings (`jarvis2 docteur --reparer`, environ 220 Mo, une fois)
#   demarrage    `jarvis2` ouvre l'interface dans le navigateur (sauf --sans-demarrer)
#
# Options :
#   --source <s>          roue .whl, dossier core du dépôt ou URL (défaut : ce dépôt, sinon la dernière version)
#   --oui                 ne rien demander : les outils indispensables (uv) sont installés ; les cases
#                         facultatives (Ollama, modèle) restent DÉCOCHÉES
#   --avec-ollama         cocher d'avance Ollama et le premier modèle (sans question)
#   --sans-ollama         ne pas proposer Ollama ni le modèle
#   --essai               à blanc : n'exécute rien, n'écrit rien, affiche ce qui serait fait
#   --sans-demarrer       installer et préparer, sans lancer JARVIS
#   --sans-modifier-path  ne pas toucher au PATH des terminaux
#   --recommencer         ignorer le fichier d'état et tout refaire
#
# Sans terminal pour répondre (CI, tâche planifiée) : rien n'est demandé, les cases facultatives restent
# décochées, et uv n'est installé qu'avec --oui.
#
# Fichier d'état : $JARVIS2_ETAT_INSTALLATION, sinon <dossier de configuration>/installation.etat
# (dossier de JARVIS2_CONFIG, sinon $XDG_CONFIG_HOME/jarvis2 ou ~/.config/jarvis2). Une ligne par étape :
# `etape=statut`, statut parmi fait, refuse, a_faire, echec ; plus `source=` et `format=1`.
#
# Codes de sortie : 0 installé (ce qui reste à faire est listé à la fin), 1 une étape a échoué (relancer reprend
# là où ça s'est arrêté), 2 option invalide, 3 outil indispensable refusé ou impossible à installer sans réponse.
#
# Claude Code (https://code.claude.com) et Tailscale (https://tailscale.com/download) ne sont jamais installés par
# ce script : JARVIS les détecte et l'assistant de premier lancement les propose.
set -eu

SOURCE="${JARVIS2_SOURCE:-}"
OUI=0
ESSAI=0
DEMARRER=1
MODIFIER_PATH=1
OLLAMA_CHOIX=demander # demander | oui | non
RECOMMENCER=0
while [ $# -gt 0 ]; do
    case "$1" in
        --source)
            [ $# -ge 2 ] || { echo "--source attend une valeur" >&2; exit 2; }
            SOURCE="$2"; shift 2 ;;
        --oui) OUI=1; shift ;;
        --essai) ESSAI=1; shift ;;
        --avec-ollama|--sans-ollama)
            CHOIX=oui; [ "$1" = --sans-ollama ] && CHOIX=non
            if [ "$OLLAMA_CHOIX" != demander ] && [ "$OLLAMA_CHOIX" != "$CHOIX" ]; then
                echo "--avec-ollama et --sans-ollama s'excluent" >&2; exit 2
            fi
            OLLAMA_CHOIX=$CHOIX; shift ;;
        --sans-demarrer) DEMARRER=0; shift ;;
        --sans-modifier-path) MODIFIER_PATH=0; shift ;;
        --recommencer) RECOMMENCER=1; shift ;;
        -h|--help) sed -n '2,44p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Option inconnue : $1 (voir --help)" >&2; exit 2 ;;
    esac
done

# ------------------------------------------------------------------ affichage et questions

if [ -t 1 ]; then BLEU=$(printf '\033[36m'); GRIS=$(printf '\033[90m'); FIN=$(printf '\033[0m'); else BLEU=; GRIS=; FIN=; fi
etape() { printf '\n%s» %s%s\n' "$BLEU" "$1" "$FIN"; }
info() { printf '  %s\n' "$1"; }

# Terminal pour répondre : l'entrée standard, ou /dev/tty quand le script arrive par `curl … | sh`.
ENTREE=
if [ -t 0 ]; then
    ENTREE=/dev/stdin
elif (: </dev/tty) 2>/dev/null; then
    ENTREE=/dev/tty
fi
interactif() { [ -n "$ENTREE" ] && [ "$OUI" -ne 1 ]; }

# demander "question" → 0 si oui ; jamais de oui implicite
demander() {
    interactif || return 1
    printf '%s [o/N] ' "$1"
    read -r reponse <"$ENTREE" || return 1
    case "$reponse" in o|O|oui|Oui|OUI|y|Y|yes) return 0 ;; *) return 1 ;; esac
}

# executer cmd args… : à blanc, n'affiche que la commande
executer() {
    if [ "$ESSAI" -eq 1 ]; then
        printf '  %s[essai] ferait : %s%s\n' "$GRIS" "$*" "$FIN"
        return 0
    fi
    "$@"
}

# ------------------------------------------------------------------ fichier d'état

if [ -n "${JARVIS2_ETAT_INSTALLATION:-}" ]; then
    ETAT="$JARVIS2_ETAT_INSTALLATION"
elif [ -n "${JARVIS2_CONFIG:-}" ]; then
    ETAT="$(dirname "$JARVIS2_CONFIG")/installation.etat"
else
    ETAT="${XDG_CONFIG_HOME:-$HOME/.config}/jarvis2/installation.etat"
fi
if [ "$RECOMMENCER" -eq 1 ] && [ -f "$ETAT" ] && [ "$ESSAI" -ne 1 ]; then rm -f "$ETAT"; fi

lire_etat() { # lire_etat cle → valeur ou vide
    if [ -f "$ETAT" ] && [ "$RECOMMENCER" -ne 1 ]; then sed -n "s/^$1=//p" "$ETAT" | tail -n 1; fi
}

noter() { # noter cle valeur (remplacement atomique : écrit à côté puis renommé)
    [ "$ESSAI" -eq 1 ] && return 0
    mkdir -p "$(dirname "$ETAT")"
    {
        if [ -f "$ETAT" ]; then grep -v -e "^$1=" -e '^format=' "$ETAT" || true; fi
        printf '%s=%s\n' "$1" "$2"
    } >"$ETAT.tmp"
    { echo 'format=1'; cat "$ETAT.tmp"; } >"$ETAT.tmp2" && rm -f "$ETAT.tmp" && mv -f "$ETAT.tmp2" "$ETAT"
}

# Bilan final : une ligne par étape, dans l'ordre
BILAN=
bilan() { BILAN="$BILAN$1|$2
"; }
A_FAIRE=
a_faire() { A_FAIRE="$A_FAIRE  - $1
"; }

deja_fait() { # deja_fait etape libellé → 0 (et bilan) si l'étape est notée faite
    if [ "$(lire_etat "$1")" = fait ]; then
        etape "$2 : déjà fait (fichier d'état), sauté"
        bilan "$2" "déjà fait"
        return 0
    fi
    return 1
}

afficher_bilan() {
    printf '\n%s» Bilan%s\n' "$BLEU" "$FIN"
    printf '%s' "$BILAN" | while IFS='|' read -r nom statut; do
        if [ -n "$nom" ]; then printf '  %s : %s\n' "$nom" "$statut"; fi
    done
    if [ -n "$A_FAIRE" ]; then printf '\nReste à faire :\n%s' "$A_FAIRE"; fi
}

finir() { # finir code
    afficher_bilan
    if [ "$ESSAI" -eq 1 ]; then
        printf '\nEssai à blanc : rien n'"'"'a été installé ni écrit.\n'
    elif [ "$1" -eq 0 ]; then
        printf '\nJARVIS 2 est installé. Fichier d'"'"'état : %s\n' "$ETAT"
    elif [ "$1" -eq 1 ]; then
        printf '\nInstallation INCOMPLÈTE : relancez ce script, il reprendra à l'"'"'étape en échec.\n'
    else
        printf '\nInstallation arrêtée avant d'"'"'avoir installé JARVIS 2.\n'
    fi
    exit "$1"
}

echec() { # echec etape libellé message
    noter "$1" echec
    bilan "$2" "ÉCHEC"
    printf '  %s\n' "$3" >&2
    finir 1
}

SYSTEME=$(uname -s 2>/dev/null || echo inconnu)
BREW=
if command -v brew >/dev/null 2>&1; then BREW=brew; fi
[ "$ESSAI" -eq 1 ] && printf '%sEssai à blanc : aucune commande ne sera exécutée.%s\n' "$BLEU" "$FIN"
info "Système : $SYSTEME ; Homebrew : ${BREW:-absent} ; fichier d'état : $ETAT"

# ------------------------------------------------------------------ 1. uv

if command -v uv >/dev/null 2>&1; then
    etape "uv : présent ($(uv --version 2>/dev/null || echo 'version inconnue'))"
    bilan "uv" "présent"
    noter uv fait
else
    etape "uv (gestionnaire Python d'Astral) est absent"
    if [ "$SYSTEME" = Darwin ] && [ -n "$BREW" ]; then
        COMMANDE_UV="brew install uv"
    else
        COMMANDE_UV="curl -LsSf https://astral.sh/uv/install.sh | sh"
    fi
    if [ "$OUI" -ne 1 ] && [ "$ESSAI" -ne 1 ]; then
        if ! interactif; then
            bilan "uv" "absent"
            a_faire "installer uv ($COMMANDE_UV), ou relancer avec --oui"
            finir 3
        fi
        if ! demander "L'installer avec : $COMMANDE_UV ?"; then
            noter uv refuse
            bilan "uv" "refusé"
            a_faire "installer uv (https://docs.astral.sh/uv/), puis relancer ce script"
            finir 3
        fi
    fi
    if [ "$ESSAI" -eq 1 ]; then
        executer "$COMMANDE_UV"
    elif [ "$COMMANDE_UV" = "brew install uv" ]; then
        brew install uv || echec uv "uv" "brew install uv a échoué"
    else
        curl -LsSf https://astral.sh/uv/install.sh | sh || echec uv "uv" "le script officiel de uv a échoué"
    fi
    PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    export PATH
    if [ "$ESSAI" -ne 1 ] && ! command -v uv >/dev/null 2>&1; then
        echec uv "uv" "uv installé mais introuvable dans le PATH : ouvrez un nouveau terminal et relancez"
    fi
    noter uv fait
    bilan "uv" "$([ "$ESSAI" -eq 1 ] && echo 'à installer' || echo 'installé')"
fi

# ------------------------------------------------------------------ 2. JARVIS 2

# Source : roue (.whl) ou URL indiquée ; sinon le dépôt où se trouve ce script (interface compilée requise) ;
# sinon la dernière version publiée sur GitHub.
if [ -z "$SOURCE" ]; then
    DEPOT=$(cd "$(dirname "$0")" 2>/dev/null && pwd || true)
    if [ -n "$DEPOT" ] && [ -f "$DEPOT/core/pyproject.toml" ]; then
        if [ ! -f "$DEPOT/interface/dist/index.html" ] && [ "$ESSAI" -ne 1 ]; then
            bilan "JARVIS 2" "non installé"
            a_faire "compiler l'interface (cd interface && npm install && npm run build), ou --source <roue .whl>"
            finir 3
        fi
        SOURCE="$DEPOT/core"
    elif [ "$ESSAI" -eq 1 ]; then
        SOURCE="(dernière version publiée sur GitHub)"
    else
        etape "Recherche de la dernière version publiée de JARVIS 2"
        SOURCE=$(curl -LsSf -H "User-Agent: jarvis2-installation" \
            https://api.github.com/repos/1AngelMicka/jarvis-os/releases/latest \
            | grep -o '"browser_download_url": *"[^"]*\.whl"' | head -n 1 | sed 's/.*"\(http[^"]*\)"/\1/' || true)
        if [ -z "$SOURCE" ]; then
            bilan "JARVIS 2" "non installé"
            a_faire "indiquer --source <fichier .whl> (aucune version publiée trouvée)"
            finir 3
        fi
    fi
fi

if [ "$(lire_etat jarvis2)" = fait ] && [ "$(lire_etat source)" = "$SOURCE" ]; then
    deja_fait jarvis2 "JARVIS 2" || true
else
    etape "Installation de JARVIS 2 ($SOURCE)"
    executer uv tool install --force --python 3.13 "$SOURCE" || echec jarvis2 "JARVIS 2" "uv tool install a échoué"
    noter source "$SOURCE"
    noter jarvis2 fait
    bilan "JARVIS 2" "$([ "$ESSAI" -eq 1 ] && echo 'à installer' || echo 'installé')"
fi

if command -v uv >/dev/null 2>&1; then BIN=$(uv tool dir --bin); else BIN="$HOME/.local/bin"; fi
JARVIS="$BIN/jarvis2"

# ------------------------------------------------------------------ 3. PATH

if ! deja_fait path "PATH des terminaux"; then
    case ":$PATH:" in
        *":$BIN:"*)
            etape "PATH : $BIN y est déjà"
            noter path fait
            bilan "PATH des terminaux" "déjà bon" ;;
        *)
            if [ "$MODIFIER_PATH" -eq 1 ]; then
                etape "PATH : ajout de $BIN pour les nouveaux terminaux"
                if executer uv tool update-shell; then
                    noter path fait
                    bilan "PATH des terminaux" "$([ "$ESSAI" -eq 1 ] && echo 'à modifier' || echo 'modifié')"
                    a_faire "ouvrir un nouveau terminal pour que la commande jarvis2 y soit connue"
                else
                    noter path a_faire
                    bilan "PATH des terminaux" "non modifié"
                    a_faire "ajouter $BIN au PATH (uv tool update-shell)"
                fi
            else
                noter path refuse
                bilan "PATH des terminaux" "laissé tel quel (--sans-modifier-path)"
                a_faire "ajouter $BIN au PATH, ou lancer $JARVIS"
            fi ;;
    esac
fi
PATH="$BIN:$PATH"
export PATH

# ------------------------------------------------------------------ 4. Ollama et premier modèle (facultatifs)

OLLAMA_PRESENT=0
command -v ollama >/dev/null 2>&1 && OLLAMA_PRESENT=1

if [ "$SYSTEME" = Darwin ]; then
    if [ -n "$BREW" ]; then COMMANDE_OLLAMA="brew install ollama"; else COMMANDE_OLLAMA=; fi
else
    COMMANDE_OLLAMA="curl -fsSL https://ollama.com/install.sh | sh"
fi

# Premier modèle : la table matériel → modèle de JARVIS (lecture seule, rien n'est installé ni démarré)
MODELE=
MODELE_DETAIL=
if [ -x "$JARVIS" ] || command -v jarvis2 >/dev/null 2>&1; then
    LIGNE=$("$JARVIS" materiel --modele conversation 2>/dev/null || jarvis2 materiel --modele conversation 2>/dev/null || true)
    if [ -n "$LIGNE" ]; then
        MODELE=$(printf '%s' "$LIGNE" | cut -f1)
        MODELE_DETAIL="$(printf '%s' "$LIGNE" | cut -f3), environ $(printf '%s' "$LIGNE" | cut -f2) Go de mémoire"
    fi
fi

COCHE_OLLAMA=0
COCHE_MODELE=0
if [ "$(lire_etat ollama)" = fait ] && [ "$(lire_etat modele)" = fait ]; then
    deja_fait ollama "Ollama" || true
    deja_fait modele "Premier modèle" || true
elif [ "$OLLAMA_CHOIX" = non ]; then
    etape "Ollama : non proposé (--sans-ollama)"
    bilan "Ollama" "non proposé"
else
    etape "Facultatif : modèles locaux avec Ollama (https://ollama.com)"
    if [ "$OLLAMA_PRESENT" -eq 1 ]; then
        info "[x] 1  Ollama : déjà installé"
    elif [ -n "$COMMANDE_OLLAMA" ]; then
        info "[ ] 1  Ollama, par : $COMMANDE_OLLAMA"
    else
        info "[-] 1  Ollama : à installer vous-même (https://ollama.com/download), Homebrew absent"
    fi
    if [ -n "$MODELE" ]; then
        info "[ ] 2  Premier modèle conseillé pour ce PC : $MODELE ($MODELE_DETAIL)"
    elif [ "$ESSAI" -eq 1 ]; then
        info "[ ] 2  Premier modèle : choisi après l'installation par « jarvis2 materiel --modele conversation »"
        MODELE="(modèle conseillé par la table matériel → modèle)"
    else
        info "[-] 2  Premier modèle : aucun ne tient dans la mémoire de ce PC"
    fi
    if [ "$OLLAMA_CHOIX" = oui ]; then
        COCHE_OLLAMA=1
        COCHE_MODELE=1
        info "Cochés d'avance (--avec-ollama)."
    elif interactif; then
        printf '  Numéros à cocher (ex. « 1 2 »), Entrée pour aucun : '
        read -r choix <"$ENTREE" || choix=
        for n in $choix; do
            case "$n" in 1) COCHE_OLLAMA=1 ;; 2) COCHE_MODELE=1 ;; esac
        done
    else
        info "Sans réponse possible : rien n'est coché."
    fi
    [ "$OLLAMA_PRESENT" -eq 1 ] && COCHE_OLLAMA=0
    if [ "$COCHE_MODELE" -eq 1 ] && [ "$OLLAMA_PRESENT" -ne 1 ] && [ "$COCHE_OLLAMA" -ne 1 ]; then
        info "Le modèle demande Ollama : case 1 cochée aussi."
        COCHE_OLLAMA=1
    fi
    [ -z "$MODELE" ] && COCHE_MODELE=0

    # Ollama
    if [ "$OLLAMA_PRESENT" -eq 1 ]; then
        noter ollama fait
        bilan "Ollama" "présent"
    elif [ "$COCHE_OLLAMA" -eq 1 ]; then
        if [ -z "$COMMANDE_OLLAMA" ]; then
            noter ollama a_faire
            bilan "Ollama" "à installer vous-même"
            a_faire "installer Ollama : https://ollama.com/download"
        else
            etape "Installation d'Ollama"
            if [ "$ESSAI" -eq 1 ]; then
                executer "$COMMANDE_OLLAMA"
                bilan "Ollama" "à installer"
            elif { if [ "$COMMANDE_OLLAMA" = "brew install ollama" ]; then brew install ollama; else curl -fsSL https://ollama.com/install.sh | sh; fi; }; then
                noter ollama fait
                bilan "Ollama" "installé"
                command -v ollama >/dev/null 2>&1 && OLLAMA_PRESENT=1
            else
                noter ollama echec
                bilan "Ollama" "ÉCHEC (facultatif)"
                a_faire "installer Ollama : https://ollama.com/download"
            fi
        fi
    else
        noter ollama refuse
        bilan "Ollama" "non coché"
    fi

    # Premier modèle : jamais de démarrage d'Ollama par ce script (il doit déjà répondre)
    if [ "$COCHE_MODELE" -eq 1 ]; then
        if [ "$ESSAI" -eq 1 ]; then
            etape "Premier modèle"
            executer ollama pull "$MODELE"
            bilan "Premier modèle" "à télécharger"
        elif [ "$OLLAMA_PRESENT" -eq 1 ] && ollama list >/dev/null 2>&1; then
            etape "Téléchargement du premier modèle : $MODELE"
            if ollama pull "$MODELE"; then
                noter modele fait
                bilan "Premier modèle" "$MODELE téléchargé"
            else
                noter modele echec
                bilan "Premier modèle" "ÉCHEC (facultatif)"
                a_faire "télécharger le modèle : ollama pull $MODELE"
            fi
        else
            noter modele a_faire
            bilan "Premier modèle" "en attente : Ollama ne répond pas"
            a_faire "lancer Ollama (ce script ne le démarre jamais), puis : ollama pull $MODELE"
        fi
    elif [ "$OLLAMA_PRESENT" -eq 1 ] || [ "$COCHE_OLLAMA" -eq 1 ]; then
        noter modele refuse
        bilan "Premier modèle" "non coché"
    else
        noter modele refuse
    fi
fi

# ------------------------------------------------------------------ 5. Préparation

if ! deja_fait preparation "Préparation"; then
    etape "Préparation : base de données et modèle d'embeddings (une seule fois, environ 220 Mo)"
    if executer "$JARVIS" docteur --reparer; then
        noter preparation fait
        bilan "Préparation" "$([ "$ESSAI" -eq 1 ] && echo 'à faire' || echo 'faite')"
    elif [ -x "$JARVIS" ]; then
        # Le diagnostic rend un code non nul tant qu'il reste un point à régler (cerveau, téléphone) :
        # la base et le modèle sont prêts ; l'assistant de premier lancement s'occupe du reste.
        noter preparation fait
        bilan "Préparation" "faite, points signalés ci-dessus"
        a_faire "régler les points signalés par « jarvis2 docteur » (l'assistant de premier lancement aide)"
    else
        echec preparation "Préparation" "jarvis2 introuvable : $JARVIS"
    fi
fi

# ------------------------------------------------------------------ 6. Démarrage

if [ "$DEMARRER" -ne 1 ]; then
    bilan "Démarrage" "non lancé (--sans-demarrer)"
    a_faire "démarrer JARVIS : jarvis2   (ou $JARVIS)"
    finir 0
fi
if [ "$ESSAI" -eq 1 ]; then
    etape "Démarrage"
    executer "$JARVIS"
    bilan "Démarrage" "à lancer"
    finir 0
fi
afficher_bilan
etape "Démarrage : l'interface s'ouvre dans le navigateur (Ctrl+C ici pour arrêter JARVIS)"
exec "$JARVIS"
