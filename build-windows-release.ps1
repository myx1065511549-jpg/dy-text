$ErrorActionPreference = 'Stop'

$projectRoot = $PSScriptRoot
$runtimeDir = Join-Path $projectRoot 'dist\douyin-dashboard'
$releaseDir = Join-Path $projectRoot 'release'

Push-Location $projectRoot
try {
    python -m PyInstaller --clean --noconfirm build.spec
}
finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath (Join-Path $runtimeDir 'douyin-dashboard.backend.exe'))) {
    throw 'PyInstaller 未生成 douyin-dashboard.backend.exe'
}

function Build-WindowsExecutable {
    param([string]$Source, [string]$Output)

    Remove-Item -LiteralPath $Output -Force -ErrorAction SilentlyContinue
    Add-Type -Path $Source -OutputAssembly $Output -OutputType WindowsApplication `
        -ReferencedAssemblies 'System.dll','System.Core.dll','Microsoft.CSharp.dll'
}

Build-WindowsExecutable -Source (Join-Path $projectRoot 'launcher.cs') `
    -Output (Join-Path $runtimeDir 'douyin-dashboard.exe')
Build-WindowsExecutable -Source (Join-Path $projectRoot 'restart-browser-worker.cs') `
    -Output (Join-Path $runtimeDir 'restart-browser-worker.exe')
Build-WindowsExecutable -Source (Join-Path $projectRoot 'stop-dashboard.cs') `
    -Output (Join-Path $runtimeDir 'stop-dashboard.exe')

Copy-Item -LiteralPath `
    (Join-Path $projectRoot 'login_capture.js'), `
    (Join-Path $projectRoot 'login_helper.js'), `
    (Join-Path $projectRoot '停止看板.vbs'), `
    (Join-Path $projectRoot '登录抖音.vbs') `
    -Destination $runtimeDir -Force
Copy-Item -LiteralPath (Join-Path $projectRoot 'docs\使用说明.md') `
    -Destination (Join-Path $runtimeDir '使用说明.md') -Force

$runtimeInstaller = Join-Path $runtimeDir 'installer'
New-Item -ItemType Directory -Path $runtimeInstaller -Force | Out-Null
Copy-Item -LiteralPath `
    (Join-Path $projectRoot 'installer\installer.cs'), `
    (Join-Path $projectRoot 'installer\build-installer.ps1') `
    -Destination $runtimeInstaller -Force

& (Join-Path $runtimeInstaller 'build-installer.ps1')

New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $runtimeDir 'dist\douyin-dashboard-setup-20260821.exe') `
    -Destination $releaseDir -Force
Copy-Item -LiteralPath (Join-Path $runtimeDir 'dist\douyin-dashboard-portable-20260821.zip') `
    -Destination $releaseDir -Force
Copy-Item -LiteralPath (Join-Path $runtimeDir 'dist\SHA256SUMS.txt') `
    -Destination $releaseDir -Force

Get-ChildItem -LiteralPath $releaseDir | Select-Object Name, Length, LastWriteTime
