# Unlock app.asar under dist / release / lab-solver-out (often held by Cursor.exe)
param(
    [string]$RepoRoot = (Split-Path $PSScriptRoot -Parent)
)

$parent = Split-Path $RepoRoot -Parent
$targets = @(
    (Join-Path $RepoRoot "dist\win-unpacked"),
    (Join-Path $RepoRoot "release\win-unpacked"),
    (Join-Path $RepoRoot "out\win-unpacked"),
    (Join-Path $parent "lab-solver-out\win-unpacked")
)

$handle = Join-Path $env:TEMP "handle64.exe"
if (-not (Test-Path $handle)) {
    Write-Host "Downloading handle64.exe ..."
    Invoke-WebRequest -Uri "https://live.sysinternals.com/handle64.exe" -OutFile $handle -UseBasicParsing
}

function Unlock-Dir([string]$dir) {
    if (-not (Test-Path $dir)) { return $true }
    $asar = Join-Path $dir "resources\app.asar"
    if (Test-Path $asar) {
        Write-Host "Checking lock: $asar"
        $out = & $handle -accepteula $asar 2>&1 | Out-String
        foreach ($m in [regex]::Matches($out, "pid:\s*(\d+)")) {
            $procId = [int]$m.Groups[1].Value
            $name = (Get-Process -Id $procId -ErrorAction SilentlyContinue).ProcessName
            Write-Host "  Stop $name (PID $procId)"
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 1
    }
    Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
    return -not (Test-Path $dir)
}

$ok = $true
foreach ($dir in $targets) {
    if (-not (Unlock-Dir $dir)) {
        Write-Host "  WARN: still locked: $dir"
        $ok = $false
    } elseif (Test-Path (Join-Path (Split-Path $dir -Parent) "")) {
        Write-Host "  Cleared: $dir"
    }
}

# Stop running packaged app
Get-Process -Name LabSolver, electron -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and ($_.Path -like '*lab-solver*' -or $_.Path -like '*LabSolver*') } |
    ForEach-Object { Write-Host "Stop $($_.ProcessName) PID $($_.Id)"; Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }

if ($ok) {
    Write-Host "unlock: OK"
    exit 0
}
Write-Host "unlock: some folders still locked (build will use TEMP dir)"
exit 0
