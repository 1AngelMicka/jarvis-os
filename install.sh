#!/bin/sh
# JARVIS 2 — installation sous macOS et Linux, sans Docker ni Node.
#
#   sh install.sh [--source <roue .whl, dossier core du dépôt ou URL>] [--oui] [--sans-demarrer] [--sans-modifier-path]
#
# 1. uv (gestionnaire Python d'Astral) : installé par son script officiel s'il manque (après confirmation, sauf --oui).
# 2. JARVIS 2 : `uv tool install` (Python 3.13 géré par uv, environnement isolé, commande `jarvis2`).
# 3. Préparation : base SQLite et modèle d'embeddings (`jarvis2 docteur --reparer`, environ 220 Mo une seule fois).
# 4. Démarrage : `jarvis2` ouvre l'interface dans le navigateur ; l'assistant de premier lancement prend le relais.
#
# Facultatif : Claude Code (https://code.claude.com), Ollama (https://ollama.com), Tailscale
# (https://tailscale.com/download). JARVIS les détecte, ne les installe jamais.
set -eu

SOURCE="${JARVIS2_SOURCE:-}"
OUI=0
DEMARRER=1
MODIFIER_PATH=1
while [ $# -gt 0 ]; do
    case "$1" in
        --source) SOURCE="$2"; shift 2 ;;
        --oui) OUI=1; shift ;;
        --sans-demarrer) DEMARRER=0; shift ;;
        --sans-modifier-path) MODIFIER_PATH=0; shift ;;
        *) echo "Option inconnue : $1" >&2; exit 2 ;;
    esac
done

etape() { printf '\n\033[36m» %s\033[0m\n' "$1"; }

# 1. uv
if ! command -v uv >/dev/null 2>&1; then
    etape "uv (gestionnaire Python d'Astral) est absent."
    if [ "$OUI" -ne 1 ]; then
        printf "L'installer avec son script officiel (https://astral.sh/uv/install.sh) ? [o/N] "
        read -r reponse
        case "$reponse" in
            o|O|y|Y|oui|yes) ;;
            *) echo "Installez uv (https://docs.astral.sh/uv/), puis relancez ce script."; exit 1 ;;
        esac
    fi
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="$HOME/.local/bin:$PATH"
    export PATH
fi

# 2. Source : roue (.whl), URL, ou le dépôt où se trouve ce script (interface compilée requise)
# Sinon : le dépôt où se trouve ce script, ou la dernière version publiée sur GitHub
# (installation en une ligne : curl -LsSf https://raw.githubusercontent.com/1AngelMicka/jarvis-os/main/install.sh | sh)
if [ -z "$SOURCE" ]; then
    DEPOT=$(cd "$(dirname "$0")" 2>/dev/null && pwd || true)
    if [ -n "$DEPOT" ] && [ -f "$DEPOT/core/pyproject.toml" ]; then
        if [ ! -f "$DEPOT/interface/dist/index.html" ]; then
            echo "Interface non compilée : cd interface && npm install && npm run build (ou --source <roue .whl>)" >&2
            exit 1
        fi
        SOURCE="$DEPOT/core"
    else
        etape "Recherche de la dernière version publiée de JARVIS 2"
        SOURCE=$(curl -LsSf -H "User-Agent: jarvis2-installation" https://api.github.com/repos/1AngelMicka/jarvis-os/releases/latest \
            | grep -o '"browser_download_url": *"[^"]*\.whl"' | head -n 1 | sed 's/.*"\(http[^"]*\)"/\1/')
        if [ -z "$SOURCE" ]; then
            echo "Aucune version publiée trouvée : indiquez --source <fichier .whl>" >&2
            exit 1
        fi
    fi
fi
etape "Installation de JARVIS 2 ($SOURCE)"
uv tool install --force --python 3.13 "$SOURCE"

BIN=$(uv tool dir --bin)
JARVIS="$BIN/jarvis2"
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) if [ "$MODIFIER_PATH" -eq 1 ]; then uv tool update-shell >/dev/null; fi ;;
esac

# 3. Préparation
etape "Préparation : base de données et modèle d'embeddings (une seule fois)"
"$JARVIS" docteur --reparer || true  # le diagnostic signale ce qui reste à faire ; l'assistant s'en occupe

# 4. Démarrage
if [ "$DEMARRER" -ne 1 ]; then
    printf '\nInstallé. Démarrer JARVIS : jarvis2   (ou %s)\n' "$JARVIS"
    exit 0
fi
etape "Démarrage : l'interface s'ouvre dans le navigateur (Ctrl+C ici pour arrêter JARVIS)"
exec "$JARVIS"
