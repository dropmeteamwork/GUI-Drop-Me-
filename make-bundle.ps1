param(
  [string]$RepoPath = "D:\nada\DropMe\ai x embedded\dropme-gui-final",
  [int]$MaxMB = 2
)

Set-Location $RepoPath

$excludeDirs = @("\.git\", "\node_modules\", "\dist\", "\build\", "\.venv\", "\__pycache__\")
$maxBytes = $MaxMB * 1MB

$skipExt = @(
  ".png",".jpg",".jpeg",".gif",".bmp",".ico",".webp",
  ".pdf",".zip",".7z",".rar",".tar",".gz",
  ".exe",".dll",".so",".dylib",
  ".ttf",".otf",".woff",".woff2",
  ".mp3",".mp4",".mov",".avi",".mkv",
  ".bin",".dat",".pkl",".npz",".npy",
  ".class",".jar",".pyc",
  ".db",".sqlite",".sqlite3",
  ".map"
)

function Test-IsBinaryFile($path) {
  try {
    $fs = [System.IO.File]::OpenRead($path)
    try {
      $buf = New-Object byte[] 4096
      $read = $fs.Read($buf, 0, $buf.Length)
      for ($i = 0; $i -lt $read; $i++) { if ($buf[$i] -eq 0) { return $true } }
      return $false
    } finally { $fs.Close() }
  } catch { return $true }
}

# Tree (UTF-8)
tree /F /A | Set-Content -Encoding utf8 REPO_TREE.txt

# Bundle (UTF-8 no BOM)
$bundlePath = Join-Path (Get-Location) "REPO_BUNDLE.txt"
$utf8 = New-Object System.Text.UTF8Encoding($false)
$sw = New-Object System.IO.StreamWriter($bundlePath, $false, $utf8)

try {
  Get-ChildItem -Recurse -File | Where-Object {
    $p = $_.FullName
    -not ($excludeDirs | ForEach-Object { $p -like "*$_*" } | Where-Object { $_ } | Measure-Object).Count
  } | Sort-Object FullName | ForEach-Object {

    $ext = $_.Extension.ToLowerInvariant()

    $sw.WriteLine("")
    $sw.WriteLine("===== FILE: $($_.FullName) =====")
    $sw.WriteLine("")

    if ($skipExt -contains $ext) {
      $sw.WriteLine("[SKIPPED: binary/asset extension $ext]")
      return
    }

    if ($_.Length -gt $maxBytes) {
      $sw.WriteLine("[SKIPPED: file is $([Math]::Round($_.Length/1MB,2)) MB, over limit of $MaxMB MB]")
      return
    }

    if (Test-IsBinaryFile $_.FullName) {
      $sw.WriteLine("[SKIPPED: detected as binary]")
      return
    }

    try {
      foreach ($line in [System.IO.File]::ReadLines($_.FullName)) { $sw.WriteLine($line) }
    } catch {
      $sw.WriteLine("[SKIPPED: could not read file as text: $($_.Exception.Message)]")
    }
  }
}
finally {
  $sw.Close()
}

Write-Host "Done. Updated REPO_TREE.txt and REPO_BUNDLE.txt in $RepoPath"