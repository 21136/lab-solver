# Build Windows installer into a fresh TEMP folder (avoids app.asar file locks)
param(
    [string]$RepoRoot = (Split-Path $PSScriptRoot -Parent)
)

$ErrorActionPreference = "Stop"
Set-Location $RepoRoot

Write-Host "== unlock old outputs =="
& (Join-Path $PSScriptRoot "unlock-dist.ps1") -RepoRoot $RepoRoot

$GraphvizDot = Join-Path $RepoRoot "src\python\assets\graphviz\bin\dot.exe"
if (-not (Test-Path $GraphvizDot)) {
    Write-Host "== portable Graphviz missing; fetching =="
    & (Join-Path $PSScriptRoot "fetch-graphviz-portable.ps1") -RepoRoot $RepoRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "WARN: Graphviz fetch failed; DFD rendering may be unavailable in installer"
    }
}

$buildOut = Join-Path $env:TEMP ("lab-solver-eb-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Force -Path $buildOut | Out-Null
Write-Host "== electron-builder output: $buildOut =="

$builder = Join-Path $RepoRoot "node_modules\.bin\electron-builder.cmd"
if (-not (Test-Path $builder)) {
    Write-Host "Running npm install..."
    npm install
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& $builder --win "--config.directories.output=$buildOut"
if ($LASTEXITCODE -ne 0) {
    Write-Host "BUILD FAILED (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}

$installerDir = Join-Path $RepoRoot "installer"
New-Item -ItemType Directory -Force -Path $installerDir | Out-Null
Get-ChildItem -Path $buildOut -Filter "*.exe" | Copy-Item -Destination $installerDir -Force
if (Test-Path (Join-Path $buildOut "win-unpacked")) {
    $portable = Join-Path $installerDir "win-unpacked"
    if (Test-Path $portable) { Remove-Item -LiteralPath $portable -Recurse -Force }
    Copy-Item -Path (Join-Path $buildOut "win-unpacked") -Destination $portable -Recurse -Force
}

$marker = Join-Path $RepoRoot "installer\LAST_BUILD.txt"
@(
    "time=$(Get-Date -Format o)",
    "temp_output=$buildOut",
    "installer_dir=$installerDir"
) | Set-Content -Path $marker -Encoding UTF8

Write-Host ""
Write-Host "BUILD OK"
Write-Host "  Installer: $installerDir\*.exe"
Write-Host "  Portable:  $installerDir\win-unpacked\LabSolver.exe"
Write-Host "  Temp copy: $buildOut"
exit 0
