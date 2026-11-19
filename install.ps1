<#
JARVIS 2 — installation sous Windows, sans Docker ni Node.

  powershell -ExecutionPolicy Bypass -File install.ps1 [--source <roue .whl, dossier core du dépôt ou URL>] [options]
  irm https://raw.githubusercontent.com/1AngelMicka/jarvis-os/main/install.ps1 | iex

Contrat commun avec install.sh (mêmes étapes, même fichier d'état, mêmes options, mêmes codes de sortie). Les
options s'écrivent à la manière de install.sh (--oui) ou de PowerShell (-Oui).

Étapes, dans l'ordre (chacune notée dans le fichier d'état, une étape « fait » est sautée à la relance) :
  uv           gestionnaire Python d'Astral : winget s'il est là, sinon son script officiel
  jarvis2      `uv tool install --python 3.13` (Python géré par uv, environnement isolé, commande `jarvis2`)
  path         dossier des commandes de uv ajouté au PATH de l'utilisateur (`uv tool update-shell`) ; le PATH de
               cette session est relu depuis le registre après chaque installation (pas besoin de rouvrir)
  ollama       FACULTATIF, proposé par une case à cocher, décochée par défaut : Ollama par winget
  modele       FACULTATIF, même case à cocher : premier modèle de conversation choisi par la table
               matériel → modèle de JARVIS (`jarvis2 materiel --modele conversation`), puis `ollama pull`
  preparation  base SQLite et modèle d'embeddings (`jarvis2 docteur --reparer`, environ 220 Mo, une fois)
  demarrage    `jarvis2` ouvre l'interface dans le navigateur (sauf --sans-demarrer)

Options :
  --source <s>          roue .whl, dossier core du dépôt ou URL (défaut : ce dépôt, sinon la dernière version)
  --oui                 ne rien demander : les outils indispensables (uv) sont installés ; les cases
                        facultatives (Ollama, modèle) restent DÉCOCHÉES
  --avec-ollama         cocher d'avance Ollama et le premier modèle (sans question)
  --sans-ollama         ne pas proposer Ollama ni le modèle
  --essai               à blanc : n'exécute rien, n'écrit rien, affiche ce qui serait fait
  --sans-demarrer       installer et préparer, sans lancer JARVIS
  --sans-modifier-path  ne pas toucher au PATH de l'utilisateur
  --recommencer         ignorer le fichier d'état et tout refaire

Sans console pour répondre (CI, tâche planifiée) : rien n'est demandé, les cases facultatives restent décochées,
et uv n'est installé qu'avec --oui.

Fichier d'état : $env:JARVIS2_ETAT_INSTALLATION, sinon <dossier de configuration>\installation.etat (dossier de
JARVIS2_CONFIG, sinon %APPDATA%\JARVIS2). Une ligne par étape : `etape=statut`, statut parmi fait, refuse,
a_faire, echec ; plus `source=` et `format=1`.

Codes de sortie : 0 installé (ce qui reste à faire est listé à la fin), 1 une étape a échoué (relancer reprend là
où ça s'est arrêté), 2 option invalide, 3 outil indispensable refusé ou impossible à installer sans réponse.

Claude Code (https://code.claude.com) et Tailscale (https://tailscale.com/download) ne sont jamais installés par
ce script : JARVIS les détecte et l'assistant de premier lancement les propose.
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$Source = $env:JARVIS2_SOURCE,
    [switch]$Oui,
    [switch]$Essai,
    [switch]$AvecOllama,
    [switch]$SansOllama,
    [switch]$SansDemarrer,
    [switch]$SansModifierPath,
    [switch]$Recommencer,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Reste
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
# Sortie redirigée (journal de CI, fichier) : accents en UTF-8 ; la console de l'utilisateur n'est pas touchée
try { if ([Console]::IsOutputRedirected) { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } } catch { $null = $_ }

$script:CodeSortie = 0
$script:Bilan = New-Object System.Collections.Generic.List[string]
$script:AFaire = New-Object System.Collections.Generic.List[string]

# ------------------------------------------------------------------ options à la manière de install.sh

$i = 0
$options = @($Reste | Where-Object { $null -ne $_ })
while ($i -lt $options.Count) {
    switch ($options[$i]) {
        '--source' {
            if ($i + 1 -ge $options.Count) { [Console]::Error.WriteLine('--source attend une valeur'); exit 2 }
            $Source = $options[$i + 1]; $i++
        }
        '--oui' { $Oui = $true }
        '--essai' { $Essai = $true }
        '--avec-ollama' { $AvecOllama = $true }
        '--sans-ollama' { $SansOllama = $true }
        '--sans-demarrer' { $SansDemarrer = $true }
        '--sans-modifier-path' { $SansModifierPath = $true }
        '--recommencer' { $Recommencer = $true }
        { $_ -in '-h', '--help', '/?' } {
            if ($PSCommandPath) { (Get-Content -LiteralPath $PSCommandPath -Encoding UTF8 -TotalCount 43 | Select-Object -Skip 1) -join "`n" | Write-Output }
            exit 0
        }
        default { [Console]::Error.WriteLine("Option inconnue : $($options[$i]) (voir --help)"); exit 2 }
    }
    $i++
}
if ($AvecOllama -and $SansOllama) { [Console]::Error.WriteLine('--avec-ollama et --sans-ollama s''excluent'); exit 2 }

# ------------------------------------------------------------------ affichage, questions, exécution

function AfficherEtape([string]$texte) { Write-Host "`n» $texte" -ForegroundColor Cyan }
function Info([string]$texte) { Write-Host "  $texte" }

function EstInteractif {
    if ($Oui) { return $false }
    try { return [Environment]::UserInteractive -and -not [Console]::IsInputRedirected } catch { return $false }
}

function Demander([string]$question) {
    # jamais de oui implicite : sans console, ou sur une erreur de lecture, la réponse est non
    if (-not (EstInteractif)) { return $false }
    try { $reponse = Read-Host "$question [o/N]" } catch { return $false }
    return ($reponse -match '^(o|oui|y|yes)$')
}

function LireChoix([string]$invite) {
    if (-not (EstInteractif)) { return '' }
    try { return [string](Read-Host $invite) } catch { return '' }
}

function Executer([string]$exe, [string[]]$arguments) {
    # Commande native ; à blanc, l'affiche seulement. Rend $true si le code de sortie vaut 0.
    if ($Essai) {
        Write-Host "  [essai] ferait : $exe $($arguments -join ' ')" -ForegroundColor DarkGray
        return $true
    }
    $avant = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'  # Windows PowerShell 5.1 : la sortie d'erreur d'un programme n'est pas fatale
    try { & $exe @arguments | Out-Host; return ($LASTEXITCODE -eq 0) }
    catch { Write-Host "  $($_.Exception.Message)"; return $false }
    finally { $ErrorActionPreference = $avant }
}

function TesterCommande([string]$exe, [string[]]$arguments) {
    # Lecture seule, sortie masquée (même en mode essai : rien n'est modifié)
    $avant = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $exe @arguments *> $null; return ($LASTEXITCODE -eq 0) } catch { return $false }
    finally { $ErrorActionPreference = $avant }
}

function Present([string]$nom) { return [bool](Get-Command $nom -ErrorAction SilentlyContinue) }

function RelirePath {
    # Après une installation (winget, uv tool update-shell), le PATH de cette session est relu depuis le registre
    # (machine puis utilisateur) ; les dossiers ajoutés à la main pendant la session sont gardés à la fin.
    $registre = @(
        [Environment]::GetEnvironmentVariable('Path', 'Machine'),
        [Environment]::GetEnvironmentVariable('Path', 'User')
    ) -join ';'
    $morceaux = New-Object System.Collections.Generic.List[string]
    foreach ($d in (($registre + ';' + $env:Path) -split ';')) {
        $d = [Environment]::ExpandEnvironmentVariables($d.Trim())
        if ($d -and -not ($morceaux -contains $d)) { $morceaux.Add($d) }
    }
    $env:Path = $morceaux -join ';'
}

# ------------------------------------------------------------------ fichier d'état et bilan

if ($env:JARVIS2_ETAT_INSTALLATION) {
    $Etat = $env:JARVIS2_ETAT_INSTALLATION
} elseif ($env:JARVIS2_CONFIG) {
    $Etat = Join-Path (Split-Path -Parent $env:JARVIS2_CONFIG) 'installation.etat'
} else {
    $Etat = Join-Path (Join-Path $env:APPDATA 'JARVIS2') 'installation.etat'
}
if ($Recommencer -and -not $Essai -and (Test-Path -LiteralPath $Etat)) { Remove-Item -LiteralPath $Etat -Force }

function LireEtat([string]$cle) {
    if ($Recommencer -or -not (Test-Path -LiteralPath $Etat)) { return '' }
    $valeur = ''
    foreach ($ligne in [IO.File]::ReadAllLines($Etat)) {
        if ($ligne.StartsWith("$cle=")) { $valeur = $ligne.Substring($cle.Length + 1) }
    }
    return $valeur
}

function NoterEtat([string]$cle, [string]$valeur) {
    # Remplacement d'un bloc : écrit à côté puis renommé (une coupure laisse l'ancien fichier entier)
    if ($Essai) { return }
    $dossier = Split-Path -Parent $Etat
    if (-not (Test-Path -LiteralPath $dossier)) { New-Item -ItemType Directory -Force -Path $dossier | Out-Null }
    $lignes = New-Object System.Collections.Generic.List[string]
    $lignes.Add('format=1')
    if (Test-Path -LiteralPath $Etat) {
        foreach ($ligne in [IO.File]::ReadAllLines($Etat)) {
            if ($ligne -and -not $ligne.StartsWith("$cle=") -and -not $ligne.StartsWith('format=')) { $lignes.Add($ligne) }
        }
    }
    $lignes.Add("$cle=$valeur")
    $temporaire = "$Etat.tmp"
    [IO.File]::WriteAllText($temporaire, (($lignes -join "`n") + "`n"), (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $temporaire -Destination $Etat -Force
}

function AjouterBilan([string]$nom, [string]$statut) { $script:Bilan.Add("$nom : $statut") }
function AjouterAFaire([string]$texte) { $script:AFaire.Add($texte) }

function DejaFait([string]$cle, [string]$nom) {
    if ((LireEtat $cle) -eq 'fait') {
        AfficherEtape "$nom : déjà fait (fichier d'état), sauté"
        AjouterBilan $nom 'déjà fait'
        return $true
    }
    return $false
}

function SiEssai([string]$essai, [string]$reel) { if ($Essai) { return $essai } return $reel }

function AfficherBilan {
    Write-Host "`n» Bilan" -ForegroundColor Cyan
    foreach ($ligne in $script:Bilan) { Write-Host "  $ligne" }
    if ($script:AFaire.Count) {
        Write-Host "`nReste à faire :"
        foreach ($ligne in $script:AFaire) { Write-Host "  - $ligne" }
    }
}

function Finir([int]$code) {
    $script:CodeSortie = $code
    throw 'JARVIS2_FIN'
}

function Echouer([string]$cle, [string]$nom, [string]$message) {
    NoterEtat $cle 'echec'
    AjouterBilan $nom 'ÉCHEC'
    Write-Host "  $message" -ForegroundColor Red
    Finir 1
}

# ------------------------------------------------------------------ l'installation

function Installer {
    RelirePath
    $winget = Present 'winget'
    if ($Essai) { Write-Host 'Essai à blanc : aucune commande ne sera exécutée.' -ForegroundColor Cyan }
    Info "Windows ; winget : $(if ($winget) { 'présent' } else { 'absent' }) ; fichier d'état : $Etat"

    # 1. uv
    if (Present 'uv') {
        AfficherEtape "uv : présent ($((& uv --version) -join ' '))"
        AjouterBilan 'uv' 'présent'
        NoterEtat 'uv' 'fait'
    } else {
        AfficherEtape "uv (gestionnaire Python d'Astral) est absent"
        if ($winget) {
            $exe = 'winget'
            $arguments = @('install', '--id', 'astral-sh.uv', '--exact', '--source', 'winget',
                '--accept-source-agreements', '--accept-package-agreements', '--disable-interactivity')
        } else {
            $exe = 'powershell'
            $arguments = @('-NoProfile', '-ExecutionPolicy', 'ByPass', '-Command', 'irm https://astral.sh/uv/install.ps1 | iex')
        }
        $libelle = if ($winget) { 'winget install astral-sh.uv' } else { 'son script officiel (https://astral.sh/uv/install.ps1)' }
        if (-not $Oui -and -not $Essai) {
            if (-not (EstInteractif)) {
                AjouterBilan 'uv' 'absent'
                AjouterAFaire "installer uv ($libelle), ou relancer avec --oui"
                Finir 3
            }
            if (-not (Demander "L'installer avec $libelle ?")) {
                NoterEtat 'uv' 'refuse'
                AjouterBilan 'uv' 'refusé'
                AjouterAFaire 'installer uv (https://docs.astral.sh/uv/), puis relancer ce script'
                Finir 3
            }
        }
        if (-not (Executer $exe $arguments)) { Echouer 'uv' 'uv' "l'installation de uv a échoué" }
        RelirePath
        $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
        if (-not $Essai -and -not (Present 'uv')) {
            Echouer 'uv' 'uv' 'uv installé mais introuvable : ouvrez un nouveau terminal et relancez ce script'
        }
        NoterEtat 'uv' 'fait'
        AjouterBilan 'uv' (SiEssai 'à installer' 'installé')
    }

    # 2. JARVIS 2. Source : roue (.whl) ou URL indiquée ; sinon le dépôt où se trouve ce script (interface
    #    compilée requise) ; sinon la dernière version publiée sur GitHub.
    $source = $Source
    if (-not $source) {
        $depot = $PSScriptRoot
        if ($depot -and (Test-Path (Join-Path $depot 'core\pyproject.toml'))) {
            if (-not $Essai -and -not (Test-Path (Join-Path $depot 'interface\dist\index.html'))) {
                AjouterBilan 'JARVIS 2' 'non installé'
                AjouterAFaire "compiler l'interface (cd interface ; npm install ; npm run build), ou --source <roue .whl>"
                Finir 3
            }
            $source = Join-Path $depot 'core'
        } elseif ($Essai) {
            $source = '(dernière version publiée sur GitHub)'
        } else {
            AfficherEtape 'Recherche de la dernière version publiée de JARVIS 2'
            $version = Invoke-RestMethod -Uri 'https://api.github.com/repos/1AngelMicka/jarvis-os/releases/latest' -Headers @{ 'User-Agent' = 'jarvis2-installation' }
            $source = ($version.assets | Where-Object { $_.name -like '*.whl' } | Select-Object -First 1).browser_download_url
            if (-not $source) {
                AjouterBilan 'JARVIS 2' 'non installé'
                AjouterAFaire 'indiquer --source <fichier .whl> (aucune version publiée trouvée)'
                Finir 3
            }
            Info "Version $($version.tag_name)"
        }
    }
    if ((LireEtat 'jarvis2') -eq 'fait' -and (LireEtat 'source') -eq $source) {
        [void](DejaFait 'jarvis2' 'JARVIS 2')
    } else {
        AfficherEtape "Installation de JARVIS 2 ($source)"
        if (-not (Executer 'uv' @('tool', 'install', '--force', '--python', '3.13', $source))) {
            Echouer 'jarvis2' 'JARVIS 2' 'uv tool install a échoué'
        }
        NoterEtat 'source' $source
        NoterEtat 'jarvis2' 'fait'
        AjouterBilan 'JARVIS 2' (SiEssai 'à installer' 'installé')
    }
    if (Present 'uv') { $bin = ((& uv tool dir --bin) | Select-Object -First 1).Trim() } else { $bin = "$env:USERPROFILE\.local\bin" }
    $jarvis = Join-Path $bin 'jarvis2.exe'

    # 3. PATH
    if (-not (DejaFait 'path' 'PATH de l''utilisateur')) {
        $pathUtilisateur = [Environment]::GetEnvironmentVariable('Path', 'User')
        if ((@($pathUtilisateur -split ';') + @([Environment]::GetEnvironmentVariable('Path', 'Machine') -split ';')) -contains $bin) {
            AfficherEtape "PATH : $bin y est déjà"
            NoterEtat 'path' 'fait'
            AjouterBilan 'PATH de l''utilisateur' 'déjà bon'
        } elseif ($SansModifierPath) {
            NoterEtat 'path' 'refuse'
            AjouterBilan 'PATH de l''utilisateur' 'laissé tel quel (--sans-modifier-path)'
            AjouterAFaire "ajouter $bin au PATH, ou lancer $jarvis"
        } else {
            AfficherEtape "PATH : ajout de $bin pour l'utilisateur"
            if (Executer 'uv' @('tool', 'update-shell')) {
                NoterEtat 'path' 'fait'
                AjouterBilan 'PATH de l''utilisateur' (SiEssai 'à modifier' 'modifié (relu dans cette session)')
            } else {
                NoterEtat 'path' 'a_faire'
                AjouterBilan 'PATH de l''utilisateur' 'non modifié'
                AjouterAFaire "ajouter $bin au PATH (uv tool update-shell)"
            }
        }
    }
    RelirePath
    if (($env:Path -split ';') -notcontains $bin) { $env:Path = "$bin;$env:Path" }

    # 4. Ollama et premier modèle (facultatifs, décochés par défaut)
    $ollamaPresent = Present 'ollama'
    $modele = ''
    $detailModele = ''
    if (Test-Path -LiteralPath $jarvis) {
        # Table matériel → modèle de JARVIS : lecture seule, rien n'est installé ni démarré
        # (sortie lue en UTF-8 des deux côtés, pour les accents de la taille)
        $avant = $ErrorActionPreference
        $encodage = [Console]::OutputEncoding
        $ErrorActionPreference = 'Continue'
        $env:PYTHONIOENCODING = 'utf-8'
        try {
            [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
            $ligne = [string](& $jarvis materiel --modele conversation 2>$null | Select-Object -First 1)
        } catch { $ligne = '' }
        finally {
            $ErrorActionPreference = $avant
            Remove-Item Env:PYTHONIOENCODING -ErrorAction SilentlyContinue
            try { [Console]::OutputEncoding = $encodage } catch { $null = $_ }
        }
        if ($ligne) {
            $morceaux = $ligne.Split("`t")
            $modele = $morceaux[0]
            if ($morceaux.Count -ge 3) { $detailModele = "$($morceaux[2]), environ $($morceaux[1]) Go de mémoire" }
        }
    }
    $cocheOllama = $false
    $cocheModele = $false
    if ((LireEtat 'ollama') -eq 'fait' -and (LireEtat 'modele') -eq 'fait') {
        [void](DejaFait 'ollama' 'Ollama')
        [void](DejaFait 'modele' 'Premier modèle')
    } elseif ($SansOllama) {
        AfficherEtape 'Ollama : non proposé (--sans-ollama)'
        AjouterBilan 'Ollama' 'non proposé'
    } else {
        AfficherEtape 'Facultatif : modèles locaux avec Ollama (https://ollama.com)'
        if ($ollamaPresent) { Info '[x] 1  Ollama : déjà installé' }
        elseif ($winget) { Info '[ ] 1  Ollama, par : winget install Ollama.Ollama' }
        else { Info '[-] 1  Ollama : à installer vous-même (https://ollama.com/download), winget absent' }
        if ($modele) {
            Info "[ ] 2  Premier modèle conseillé pour ce PC : $modele ($detailModele)"
        } elseif ($Essai) {
            Info '[ ] 2  Premier modèle : choisi après l''installation par « jarvis2 materiel --modele conversation »'
            $modele = '(modèle conseillé par la table matériel → modèle)'
        } else {
            Info '[-] 2  Premier modèle : aucun ne tient dans la mémoire de ce PC'
        }
        if ($AvecOllama) {
            $cocheOllama = $true; $cocheModele = $true
            Info 'Cochés d''avance (--avec-ollama).'
        } elseif (EstInteractif) {
            foreach ($n in ((LireChoix '  Numéros à cocher (ex. « 1 2 »), Entrée pour aucun') -split '[\s,;]+')) {
                if ($n -eq '1') { $cocheOllama = $true }
                if ($n -eq '2') { $cocheModele = $true }
            }
        } else {
            Info 'Sans réponse possible : rien n''est coché.'
        }
        if ($ollamaPresent) { $cocheOllama = $false }
        if ($cocheModele -and -not $ollamaPresent -and -not $cocheOllama) {
            Info 'Le modèle demande Ollama : case 1 cochée aussi.'
            $cocheOllama = $true
        }
        if (-not $modele) { $cocheModele = $false }

        if ($ollamaPresent) {
            NoterEtat 'ollama' 'fait'
            AjouterBilan 'Ollama' 'présent'
        } elseif ($cocheOllama) {
            if (-not $winget) {
                NoterEtat 'ollama' 'a_faire'
                AjouterBilan 'Ollama' 'à installer vous-même'
                AjouterAFaire 'installer Ollama : https://ollama.com/download'
            } else {
                AfficherEtape 'Installation d''Ollama'
                $ok = Executer 'winget' @('install', '--id', 'Ollama.Ollama', '--exact', '--source', 'winget',
                    '--accept-source-agreements', '--accept-package-agreements', '--disable-interactivity')
                if ($ok) {
                    RelirePath
                    $dossierOllama = Join-Path $env:LOCALAPPDATA 'Programs\Ollama'
                    if (-not (Present 'ollama') -and (Test-Path (Join-Path $dossierOllama 'ollama.exe'))) { $env:Path = "$env:Path;$dossierOllama" }
                    $ollamaPresent = Present 'ollama'
                    NoterEtat 'ollama' 'fait'
                    AjouterBilan 'Ollama' (SiEssai 'à installer' 'installé')
                } else {
                    NoterEtat 'ollama' 'echec'
                    AjouterBilan 'Ollama' 'ÉCHEC (facultatif)'
                    AjouterAFaire 'installer Ollama : https://ollama.com/download'
                }
            }
        } else {
            NoterEtat 'ollama' 'refuse'
            AjouterBilan 'Ollama' 'non coché'
        }

        # Premier modèle : ce script ne démarre jamais Ollama (il doit déjà répondre)
        if ($cocheModele) {
            if ($Essai) {
                AfficherEtape 'Premier modèle'
                [void](Executer 'ollama' @('pull', $modele))
                AjouterBilan 'Premier modèle' 'à télécharger'
            } elseif ($ollamaPresent -and (TesterCommande 'ollama' @('list'))) {
                AfficherEtape "Téléchargement du premier modèle : $modele"
                if (Executer 'ollama' @('pull', $modele)) {
                    NoterEtat 'modele' 'fait'
                    AjouterBilan 'Premier modèle' "$modele téléchargé"
                } else {
                    NoterEtat 'modele' 'echec'
                    AjouterBilan 'Premier modèle' 'ÉCHEC (facultatif)'
                    AjouterAFaire "télécharger le modèle : ollama pull $modele"
                }
            } else {
                NoterEtat 'modele' 'a_faire'
                AjouterBilan 'Premier modèle' 'en attente : Ollama ne répond pas'
                AjouterAFaire "lancer Ollama (ce script ne le démarre jamais), puis : ollama pull $modele"
            }
        } else {
            NoterEtat 'modele' 'refuse'
            if ($ollamaPresent -or $cocheOllama) { AjouterBilan 'Premier modèle' 'non coché' }
        }
    }

    # 5. Préparation
    if (-not (DejaFait 'preparation' 'Préparation')) {
        AfficherEtape 'Préparation : base de données et modèle d''embeddings (une seule fois, environ 220 Mo)'
        if (Executer $jarvis @('docteur', '--reparer')) {
            NoterEtat 'preparation' 'fait'
            AjouterBilan 'Préparation' (SiEssai 'à faire' 'faite')
        } elseif (Test-Path -LiteralPath $jarvis) {
            # Le diagnostic rend un code non nul tant qu'il reste un point à régler (cerveau, téléphone) : la base
            # et le modèle sont prêts ; l'assistant de premier lancement s'occupe du reste.
            NoterEtat 'preparation' 'fait'
            AjouterBilan 'Préparation' 'faite, points signalés ci-dessus'
            AjouterAFaire 'régler les points signalés par « jarvis2 docteur » (l''assistant de premier lancement aide)'
        } else {
            Echouer 'preparation' 'Préparation' "jarvis2 introuvable : $jarvis"
        }
    }

    # 6. Démarrage
    if ($SansDemarrer) {
        AjouterBilan 'Démarrage' 'non lancé (--sans-demarrer)'
        AjouterAFaire "démarrer JARVIS : jarvis2   (ou $jarvis)"
        Finir 0
    }
    AfficherEtape 'Démarrage'
    if ($Essai) {
        [void](Executer $jarvis @())
        AjouterBilan 'Démarrage' 'à lancer'
        Finir 0
    }
    $script:Demarrer = $jarvis
    Finir 0
}

$script:Demarrer = ''
try {
    Installer
} catch {
    if ([string]$_.Exception.Message -ne 'JARVIS2_FIN') {
        Write-Host "  Erreur inattendue : $($_.Exception.Message)" -ForegroundColor Red
        AjouterBilan 'Installation' 'ÉCHEC'
        $script:CodeSortie = 1
    }
}
AfficherBilan
if ($Essai) {
    Write-Host "`nEssai à blanc : rien n'a été installé ni écrit."
} elseif ($script:CodeSortie -eq 0) {
    Write-Host "`nJARVIS 2 est installé. Fichier d'état : $Etat"
} elseif ($script:CodeSortie -eq 1) {
    Write-Host "`nInstallation INCOMPLÈTE : relancez ce script, il reprendra à l'étape en échec." -ForegroundColor Yellow
} else {
    Write-Host "`nInstallation arrêtée avant d'avoir installé JARVIS 2." -ForegroundColor Yellow
}
if ($script:Demarrer) {
    Write-Host "`nL'interface s'ouvre dans le navigateur (Ctrl+C ici pour arrêter JARVIS)" -ForegroundColor Cyan
    & $script:Demarrer
}
# `irm … | iex` : pas d'exit, qui fermerait la fenêtre de l'utilisateur
if ($PSCommandPath) { exit $script:CodeSortie } else { $global:LASTEXITCODE = $script:CodeSortie }
