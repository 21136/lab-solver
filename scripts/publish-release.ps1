# Upload Windows installer to GitHub Releases (requires: gh auth login)
param(
    [string]$RepoRoot = (Split-Path $PSScriptRoot -Parent),
    [string]$Tag = "v1.0.1",
    [string]$Title = "v1.0.1",
    [string]$NotesFile = ""
)

$ErrorActionPreference = "Stop"
Set-Location $RepoRoot

$ghExe = $null
$ghCmd = Get-Command gh -ErrorAction SilentlyContinue
if ($ghCmd) {
    $ghExe = $ghCmd.Source
} else {
    foreach ($p in @(
            "${env:ProgramFiles}\GitHub CLI\gh.exe",
            "${env:LocalAppData}\Programs\GitHub CLI\gh.exe"
        )) {
        if (Test-Path $p) { $ghExe = $p; break }
    }
}
if (-not $ghExe) {
    Write-Error "GitHub CLI (gh) not found. Install from https://cli.github.com/ and run: gh auth login"
}

$exe = Get-ChildItem -Path (Join-Path $RepoRoot "installer") -Filter "*.exe" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $exe) {
    Write-Error "No installer/*.exe found. Run build-installer.bat first."
}

$asset = Join-Path $exe.DirectoryName "LabSolver-Setup-1.0.0-win64.exe"
Copy-Item -LiteralPath $exe.FullName -Destination $asset -Force

$gitExe = Join-Path ${env:ProgramFiles} "Git\bin\git.exe"
$commit = if (Test-Path $gitExe) {
    (& $gitExe rev-parse --short HEAD 2>$null)
} else {
    (Get-Command git -ErrorAction SilentlyContinue | ForEach-Object { & $_.Source rev-parse --short HEAD 2>$null })
}
if (-not $commit) { $commit = "unknown" }

$body = @"
## 更新内容

- Agnes AI 内置 Key（零配置试玩）
- LLM 模型注册表与 DeepSeek V4 迁移（deepseek-v4-flash）
- 设置页 provider 切换与模型列表从 API 动态加载

## 安装

下载 ``LabSolver-Setup-1.0.0-win64.exe`` 双击安装。SmartScreen 提示时选「仍要运行」。

代码提交: ``$commit``
"@

if ($NotesFile -and (Test-Path $NotesFile)) {
    $body = Get-Content -Path $NotesFile -Raw -Encoding UTF8
}

Write-Host "Creating release $Tag with asset: $asset"
& $ghExe release create $Tag $asset `
    --repo "21136/lab-solver" `
    --title $Title `
    --notes $body `
    --latest

Write-Host "Done: https://github.com/21136/lab-solver/releases/tag/$Tag"
