[CmdletBinding()]
param(
    [string]$RegistryDir = $PSScriptRoot,
    [switch]$OutputJson,
    [switch]$NoCommit
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Format-MachineName {
    param([int]$Id)
    return ("RVM-{0:D3}" -f $Id)
}

if (-not (Test-Path $RegistryDir)) {
    New-Item -ItemType Directory -Path $RegistryDir -Force | Out-Null
}

$nextIdPath = Join-Path $RegistryDir "next_id.txt"
$machinesCsvPath = Join-Path $RegistryDir "machines.csv"

if (-not (Test-Path $nextIdPath)) {
    Set-Content -Path $nextIdPath -Value "1" -Encoding ascii
}
if (-not (Test-Path $machinesCsvPath)) {
    @(
        "timestamp,machine_name,target,remote_root,status,notes"
    ) | Set-Content -Path $machinesCsvPath -Encoding ascii
}

$rawNext = (Get-Content -Path $nextIdPath -TotalCount 1).Trim()
if (-not $rawNext -or -not ($rawNext -as [int])) {
    throw "Invalid next_id.txt content: '$rawNext'. Expected integer."
}

$nextId = [int]$rawNext
$used = @{}

try {
    $rows = Import-Csv -Path $machinesCsvPath
    foreach ($row in $rows) {
        $name = ($row.machine_name | ForEach-Object { "$_".Trim() })
        if ($name) { $used[$name.ToUpperInvariant()] = $true }
    }
} catch {
    throw "Failed to read machines registry: $machinesCsvPath. $($_.Exception.Message)"
}

$candidateId = $nextId
while ($true) {
    if ($candidateId -gt 9999) {
        throw "Machine ID exhausted. Last tried: $candidateId"
    }
    $candidateName = Format-MachineName -Id $candidateId
    if (-not $used.ContainsKey($candidateName.ToUpperInvariant())) {
        break
    }
    $candidateId++
}

if (-not $NoCommit) {
    Set-Content -Path $nextIdPath -Value ($candidateId + 1) -Encoding ascii
}

$result = [pscustomobject]@{
    machine_name = $candidateName
    numeric_id   = $candidateId
    next_id      = $candidateId + 1
    committed    = (-not $NoCommit)
}

if ($OutputJson) {
    $result | ConvertTo-Json -Compress
} else {
    $candidateName
}
