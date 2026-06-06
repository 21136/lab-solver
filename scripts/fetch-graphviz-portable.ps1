# Fetch official Graphviz Windows portable zip into src/python/assets/graphviz/
# Usage (from repo root):
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/fetch-graphviz-portable.ps1

param(
    [string]$RepoRoot = (Split-Path $PSScriptRoot -Parent),
    [string]$Version = "12.2.1"
)

$ErrorActionPreference = "Stop"

$AssetsGraphviz = Join-Path $RepoRoot "src\python\assets\graphviz"
$ZipUrl = "https://gitlab.com/api/v4/projects/4207231/packages/generic/graphviz-releases/$Version/windows_10_cmake_Release_Graphviz-$Version-win64.zip"
$TempDir = Join-Path $env:TEMP ("graphviz-fetch-" + [guid]::NewGuid().ToString("n"))
$ZipPath = Join-Path $TempDir "graphviz.zip"

Write-Host "== Graphviz portable fetch =="
Write-Host "  Version: $Version"
Write-Host "  URL:     $ZipUrl"
Write-Host "  Target:  $AssetsGraphviz"

New-Item -ItemType Directory -Force -Path $TempDir | Out-Null

try {
    Write-Host "Downloading..."
    Invoke-WebRequest -Uri $ZipUrl -OutFile $ZipPath -UseBasicParsing

    Write-Host "Extracting..."
    Expand-Archive -Path $ZipPath -DestinationPath $TempDir -Force

    $DotExe = Get-ChildItem -Path $TempDir -Recurse -Filter "dot.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $DotExe) {
        throw "dot.exe not found inside downloaded archive"
    }

    $BinDir = $DotExe.Directory.FullName
    $RootDir = Split-Path $BinDir -Parent
    $LibDir = Join-Path $RootDir "lib"

    if (-not (Test-Path $LibDir)) {
        throw "lib directory not found next to bin (expected $LibDir)"
    }

    if (Test-Path $AssetsGraphviz) {
        Write-Host "Removing existing $AssetsGraphviz ..."
        Remove-Item -LiteralPath $AssetsGraphviz -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $AssetsGraphviz | Out-Null

    Write-Host "Copying bin/ and lib/ ..."
    Copy-Item -Path $BinDir -Destination (Join-Path $AssetsGraphviz "bin") -Recurse -Force
    Copy-Item -Path $LibDir -Destination (Join-Path $AssetsGraphviz "lib") -Recurse -Force

    $TargetDot = Join-Path $AssetsGraphviz "bin\dot.exe"
    if (-not (Test-Path $TargetDot)) {
        throw "Install failed: $TargetDot missing"
    }

    Write-Host "Verifying dot -V ..."
    $ver = & $TargetDot -V 2>&1 | Out-String
    Write-Host "  $($ver.Trim())"
    Write-Host ""
    Write-Host "OK: portable Graphviz installed to $AssetsGraphviz"
}
finally {
    if (Test-Path $TempDir) {
        Remove-Item -LiteralPath $TempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
