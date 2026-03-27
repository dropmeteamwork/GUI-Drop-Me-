[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Target,

    [string]$RegistryDir = $PSScriptRoot,
    [string]$DeploySource = (Join-Path $PSScriptRoot "..\.."),
    [string]$RemoteRoot = "C:\DropMe\gui",
    [string]$SecretsFile = (Join-Path $PSScriptRoot "secrets.local.ps1"),
    [string]$ModelsSource = "",
    [string]$MachineName = "",

    [switch]$PromptForCredential,
    [switch]$SkipDependencyInstall,
    [switch]$RegisterStartupTask,
    [switch]$RenameComputer
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Info {
    param([string]$Message)
    Write-Host "[fleet] $Message"
}

function Ensure-Registry {
    param([string]$PathRoot)
    if (-not (Test-Path $PathRoot)) {
        New-Item -ItemType Directory -Path $PathRoot -Force | Out-Null
    }
    $csv = Join-Path $PathRoot "machines.csv"
    if (-not (Test-Path $csv)) {
        @("timestamp,machine_name,target,remote_root,status,notes") | Set-Content -Path $csv -Encoding ascii
    }
}

function Append-RegistryRow {
    param(
        [string]$PathRoot,
        [string]$Machine,
        [string]$TargetHost,
        [string]$Root,
        [string]$Status,
        [string]$Notes
    )
    Ensure-Registry -PathRoot $PathRoot
    $csv = Join-Path $PathRoot "machines.csv"
    $row = [pscustomobject]@{
        timestamp    = (Get-Date).ToString("s")
        machine_name = $Machine
        target       = $TargetHost
        remote_root  = $Root
        status       = $Status
        notes        = $Notes
    }
    $row | Export-Csv -Path $csv -NoTypeInformation -Append
}

function Resolve-MachineName {
    param(
        [string]$Requested,
        [string]$RegistryPath
    )
    if ($Requested) { return $Requested.Trim() }

    $allocator = Join-Path $PSScriptRoot "next-machine-id.ps1"
    if (-not (Test-Path $allocator)) {
        throw "Allocator script not found: $allocator"
    }
    $json = & $allocator -RegistryDir $RegistryPath -OutputJson
    if (-not $json) {
        throw "Failed to allocate machine name."
    }
    $result = $json | ConvertFrom-Json
    return [string]$result.machine_name
}

function Load-Secrets {
    param([string]$Path)
    if (Test-Path $Path) {
        . $Path
        Write-Info "Loaded secrets from $Path"
    } else {
        Write-Info "No secrets file found at $Path (continuing with env vars / defaults)."
    }

    return @{
        MACHINE_API_KEY        = $env:MACHINE_API_KEY
        AWS_ACCESS_KEY_ID      = $env:AWS_ACCESS_KEY_ID
        AWS_SECRET_ACCESS_KEY  = $env:AWS_SECRET_ACCESS_KEY
        AWS_REGION             = $env:AWS_REGION
        AWS_BUCKET_NAME        = $env:AWS_BUCKET_NAME
        DROPME_SERVER_BASE_URL = $env:DROPME_SERVER_BASE_URL
    }
}

function New-DeployZip {
    param(
        [string]$SourceRoot
    )
    $resolvedSource = (Resolve-Path $SourceRoot).Path
    $staging = Join-Path $env:TEMP ("dropme_staging_" + [Guid]::NewGuid().ToString("N"))
    $zipPath = Join-Path $env:TEMP ("dropme_release_" + [Guid]::NewGuid().ToString("N") + ".zip")

    New-Item -ItemType Directory -Path $staging -Force | Out-Null

    $include = @(
        "src",
        "qml",
        "images",
        "fonts",
        "pyproject.toml",
        "uv.lock",
        "README.md",
        "version.txt",
        "gui.pyproject",
        "sv.py",
        "pytest.ini",
        "docs"
    )

    foreach ($item in $include) {
        $path = Join-Path $resolvedSource $item
        if (Test-Path $path) {
            Copy-Item -Path $path -Destination $staging -Recurse -Force
        }
    }

    Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zipPath -CompressionLevel Optimal -Force
    Remove-Item -Path $staging -Recurse -Force
    return $zipPath
}

Ensure-Registry -PathRoot $RegistryDir
$machine = Resolve-MachineName -Requested $MachineName -RegistryPath $RegistryDir
$secretMap = Load-Secrets -Path $SecretsFile

if (-not (Test-Path $DeploySource)) {
    throw "DeploySource not found: $DeploySource"
}
if ($ModelsSource -and -not (Test-Path $ModelsSource)) {
    throw "ModelsSource not found: $ModelsSource"
}

$cred = $null
if ($PromptForCredential) {
    $cred = Get-Credential -Message "Enter credentials for $Target"
}

$sessionArgs = @{
    ComputerName = $Target
    ErrorAction  = "Stop"
}
if ($cred) { $sessionArgs.Credential = $cred }

$session = $null
$zip = $null
try {
    Write-Info "Connecting to $Target ..."
    $session = New-PSSession @sessionArgs

    Write-Info "Preparing remote folders under $RemoteRoot ..."
    Invoke-Command -Session $session -ScriptBlock {
        param($root)
        foreach ($p in @(
            $root,
            (Join-Path $root "app"),
            (Join-Path $root "models"),
            (Join-Path $root "runtime"),
            (Join-Path $root "runtime\data"),
            (Join-Path $root "runtime\state")
        )) {
            New-Item -Path $p -ItemType Directory -Force | Out-Null
        }
    } -ArgumentList $RemoteRoot

    Write-Info "Packaging deploy source ..."
    $zip = New-DeployZip -SourceRoot $DeploySource

    $remoteZip = Join-Path $RemoteRoot "release.zip"
    Write-Info "Copying package to remote machine ..."
    Copy-Item -Path $zip -Destination $remoteZip -ToSession $session -Force

    Write-Info "Extracting package on remote machine ..."
    Invoke-Command -Session $session -ScriptBlock {
        param($root, $archive)
        $app = Join-Path $root "app"
        Get-ChildItem -Path $app -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Expand-Archive -Path $archive -DestinationPath $app -Force
        Remove-Item -Path $archive -Force
    } -ArgumentList $RemoteRoot, $remoteZip

    if ($ModelsSource) {
        Write-Info "Copying models from $ModelsSource ..."
        Copy-Item -Path (Join-Path (Resolve-Path $ModelsSource).Path "*") -Destination (Join-Path $RemoteRoot "models") -ToSession $session -Recurse -Force
    } else {
        Write-Info "ModelsSource not provided; skipping model copy."
    }

    $machineEnv = @{
        MACHINE_NAME        = $machine
        DROPME_MODELS_DIR   = (Join-Path $RemoteRoot "models")
        DROPME_DATA_DIR     = (Join-Path $RemoteRoot "runtime\data")
        DROPME_STATE_DIR    = (Join-Path $RemoteRoot "runtime\state")
        DROPME_DEV          = "0"
    }
    foreach ($k in $secretMap.Keys) {
        $v = $secretMap[$k]
        if ($null -ne $v -and "$v".Trim() -ne "") {
            $machineEnv[$k] = "$v"
        }
    }

    Write-Info "Setting machine-level environment variables ..."
    Invoke-Command -Session $session -ScriptBlock {
        param($envPairs)
        foreach ($key in $envPairs.Keys) {
            [Environment]::SetEnvironmentVariable($key, [string]$envPairs[$key], "Machine")
        }
    } -ArgumentList $machineEnv

    if (-not $SkipDependencyInstall) {
        Write-Info "Installing dependencies on remote machine (uv sync --frozen) ..."
        Invoke-Command -Session $session -ScriptBlock {
            param($root)
            $app = Join-Path $root "app"
            Set-Location $app
            $uv = Get-Command uv -ErrorAction SilentlyContinue
            if (-not $uv) {
                throw "uv is not installed on remote machine."
            }
            & uv sync --frozen
        } -ArgumentList $RemoteRoot
    } else {
        Write-Info "Skipping dependency installation by request."
    }

    if ($RegisterStartupTask) {
        Write-Info "Registering startup scheduled task ..."
        Invoke-Command -Session $session -ScriptBlock {
            param($root)
            $app = Join-Path $root "app"
            $taskName = "DropMeGUI"
            $cmd = "cd /d `"$app`" && uv run gui"
            schtasks /Create /TN $taskName /SC ONLOGON /TR "cmd.exe /c $cmd" /RL HIGHEST /F | Out-Null
        } -ArgumentList $RemoteRoot
    }

    Write-Info "Starting GUI in operating mode ..."
    Invoke-Command -Session $session -ScriptBlock {
        param($root)
        $app = Join-Path $root "app"
        Start-Process -FilePath "uv" -ArgumentList @("run", "gui") -WorkingDirectory $app -WindowStyle Hidden
    } -ArgumentList $RemoteRoot

    if ($RenameComputer) {
        Write-Info "Renaming remote computer to $machine (restart required to apply hostname) ..."
        Invoke-Command -Session $session -ScriptBlock {
            param($newName)
            Rename-Computer -NewName $newName -Force -ErrorAction Stop
        } -ArgumentList $machine
    }

    Append-RegistryRow -PathRoot $RegistryDir -Machine $machine -TargetHost $Target -Root $RemoteRoot -Status "provisioned" -Notes "ok"
    Write-Host ""
    Write-Host "Provisioning completed successfully."
    Write-Host "Machine Name: $machine"
    Write-Host "Target: $Target"
    if ($RenameComputer) {
        Write-Host "Note: reboot target to apply computer rename."
    }
}
catch {
    $err = $_.Exception.Message
    Append-RegistryRow -PathRoot $RegistryDir -Machine $machine -TargetHost $Target -Root $RemoteRoot -Status "failed" -Notes $err
    throw
}
finally {
    if ($zip -and (Test-Path $zip)) {
        Remove-Item -Path $zip -Force -ErrorAction SilentlyContinue
    }
    if ($session) {
        Remove-PSSession -Session $session -ErrorAction SilentlyContinue
    }
}
