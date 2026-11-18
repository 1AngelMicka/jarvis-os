<#
JARVIS 2 — installation sous Windows, sans Docker ni Node.

  powershell -ExecutionPolicy Bypass -File install.ps1 [-Source <roue .whl, dossier core du dépôt ou URL>] [-Oui]

1. uv (gestionnaire Python d'Astral) : installé par son script officiel s'il manque (après confirmation, sauf -Oui).
2. JARVIS 2 : `uv tool install` (Python 3.13 géré par uv, environnement isolé, commande `jarvis2`).
3. Préparation : base SQLite et modèle d'embeddings (`jarvis2 docteur --reparer`, environ 220 Mo une seule fois).
4. Démarrage : `jarvis2` ouvre l'interface dans le navigateur ; l'assistant de premier lancement prend le relais.

Facultatif : Claude Code (votre abonnement Claude, https://code.claude.com), Ollama (modèles locaux,
https://ollama.com), Tailscale (téléphone, https://tailscale.com/download). JARVIS les détecte, ne les installe jamais.
#>
param(
    [string]$Source = $env:JARVIS2_SOURCE,
    [switch]$Oui,                # ne rien demander (installation de uv comprise)
    [switch]$SansDemarrer,       # installer et préparer, sans lancer JARVIS
    [switch]$SansModifierPath    # ne pas ajouter le dossier des commandes de uv au PATH de l'utilisateur
)
$ErrorActionPreference = 'Stop'

function Etape([string]$texte) { Write-Host "`n» $texte" -ForegroundColor Cyan }

# 1. uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Etape "uv (gestionnaire Python d'Astral) est absent."
    if (-not $Oui) {
        $reponse = Read-Host "L'installer avec son script officiel (https://astral.sh/uv/install.ps1) ? [o/N]"
        if ($reponse -notmatch '^[oOyY]') {
            Write-Host "Installez uv (https://docs.astral.sh/uv/), puis relancez ce script."
            exit 1
        }
    }
    powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

# 2. Source : roue (.whl) ou URL indiquée ; sinon le dépôt où se trouve ce script ; sinon la dernière version
#    publiée sur GitHub (installation en une ligne : irm https://raw.githubusercontent.com/1AngelMicka/jarvis-os/main/install.ps1 | iex)
if (-not $Source) {
    $depot = $PSScriptRoot
    if ($depot -and (Test-Path (Join-Path $depot 'core\pyproject.toml'))) {
        if (-not (Test-Path (Join-Path $depot 'interface\dist\index.html'))) {
            throw "Interface non compilée dans ce dépôt : cd interface ; npm install ; npm run build (ou -Source <roue .whl>)"
        }
        $Source = Join-Path $depot 'core'
    } else {
        Etape "Recherche de la dernière version publiée de JARVIS 2"
        $version = Invoke-RestMethod -Uri 'https://api.github.com/repos/1AngelMicka/jarvis-os/releases/latest' -Headers @{ 'User-Agent' = 'jarvis2-installation' }
        $Source = ($version.assets | Where-Object { $_.name -like '*.whl' } | Select-Object -First 1).browser_download_url
        if (-not $Source) { throw "Aucune version publiée trouvée : indiquez -Source <fichier .whl>" }
        Write-Host "Version $($version.tag_name)"
    }
}
Etape "Installation de JARVIS 2 ($Source)"
uv tool install --force --python 3.13 $Source
if ($LASTEXITCODE) { throw "Échec de uv tool install" }

$bin = (uv tool dir --bin).Trim()
$jarvis = Join-Path $bin 'jarvis2.exe'
if (-not $SansModifierPath -and ($env:Path -split ';') -notcontains $bin) {
    uv tool update-shell | Out-Null  # ajoute le dossier des commandes au PATH (nouveaux terminaux)
}

# 3. Préparation
Etape "Préparation : base de données et modèle d'embeddings (une seule fois)"
& $jarvis docteur --reparer
# Le diagnostic signale ce qui reste à faire (cerveau, téléphone) : l'assistant de l'interface s'en occupe.

# 4. Démarrage
if ($SansDemarrer) {
    Write-Host "`nInstallé. Démarrer JARVIS : jarvis2   (ou $jarvis)"
    exit 0
}
Etape "Démarrage : l'interface s'ouvre dans le navigateur (Ctrl+C ici pour arrêter JARVIS)"
& $jarvis
