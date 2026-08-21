$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$reusePayload = $env:DOUYIN_REUSE_PAYLOAD -eq '1'
$outputDir = Join-Path $projectRoot 'dist'
$payloadPath = Join-Path $PSScriptRoot 'payload.zip'
$setupPath = Join-Path $outputDir 'douyin-dashboard-setup-20260821.exe'
$portablePath = Join-Path $outputDir 'douyin-dashboard-portable-20260821.zip'
$stubPath = Join-Path $PSScriptRoot 'installer-stub.exe'

$rootFiles = @(
    'douyin-dashboard.exe',
    'douyin-dashboard.backend.exe',
    'login_capture.js',
    'login_helper.js',
    'restart-browser-worker.exe',
    'stop-dashboard.exe',
    '停止看板.vbs',
    '登录抖音.vbs',
    '使用说明.md'
)

foreach ($file in $rootFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $file))) {
        throw "缺少运行文件：$file"
    }
}

New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
Remove-Item -LiteralPath $setupPath, $stubPath -Force -ErrorAction SilentlyContinue
if (-not $reusePayload) {
    Remove-Item -LiteralPath $payloadPath, $portablePath -Force -ErrorAction SilentlyContinue
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Add-ZipEntry {
    param(
        [System.IO.Compression.ZipArchive]$Archive,
        [string]$Source,
        [string]$EntryName
    )
    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
        $Archive,
        $Source,
        $EntryName.Replace('\', '/'),
        [System.IO.Compression.CompressionLevel]::Optimal
    ) | Out-Null
}

function New-PayloadZip {
    param([string]$Destination)
    $stream = [System.IO.File]::Open($Destination, [System.IO.FileMode]::CreateNew)
    try {
        $archive = New-Object System.IO.Compression.ZipArchive(
            $stream,
            [System.IO.Compression.ZipArchiveMode]::Create,
            $false
        )
        try {
            foreach ($file in $rootFiles) {
                Add-ZipEntry -Archive $archive -Source (Join-Path $projectRoot $file) -EntryName $file
            }
            Get-ChildItem -LiteralPath (Join-Path $projectRoot '_internal') -Recurse -File -Force |
                Where-Object { $_.Extension -ne '.bak' } | ForEach-Object {
                $relative = $_.FullName.Substring($projectRoot.Length + 1)
                Add-ZipEntry -Archive $archive -Source $_.FullName -EntryName $relative
            }
        }
        finally {
            $archive.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
}

if (-not $reusePayload -or -not (Test-Path -LiteralPath $payloadPath)) {
    New-PayloadZip -Destination $payloadPath
}
if (-not $reusePayload -or -not (Test-Path -LiteralPath $portablePath)) {
    Copy-Item -LiteralPath $payloadPath -Destination $portablePath
}

$compiler = @{
    Path = (Join-Path $PSScriptRoot 'installer.cs')
    OutputAssembly = $stubPath
    OutputType = 'WindowsApplication'
    ReferencedAssemblies = @(
        'System.dll',
        'System.Core.dll',
        'System.IO.Compression.dll',
        'System.IO.Compression.FileSystem.dll',
        'Microsoft.CSharp.dll'
    )
}
Add-Type @compiler

$setupStream = [System.IO.File]::Open($setupPath, [System.IO.FileMode]::CreateNew)
try {
    $stubStream = [System.IO.File]::OpenRead($stubPath)
    try { $stubStream.CopyTo($setupStream) } finally { $stubStream.Dispose() }
    $payloadStream = [System.IO.File]::OpenRead($payloadPath)
    try { $payloadStream.CopyTo($setupStream) } finally { $payloadStream.Dispose() }
    $writer = New-Object System.IO.BinaryWriter($setupStream, [System.Text.Encoding]::ASCII, $true)
    try {
        $writer.Write([int64](Get-Item -LiteralPath $payloadPath).Length)
        $writer.Write([System.Text.Encoding]::ASCII.GetBytes('DYDASHBOARDZIP01'))
    }
    finally { $writer.Dispose() }
}
finally { $setupStream.Dispose() }

Remove-Item -LiteralPath $payloadPath, $stubPath -Force

$hashes = Get-FileHash -Algorithm SHA256 -LiteralPath $setupPath, $portablePath
$hashLines = $hashes | ForEach-Object { "{0}  {1}" -f $_.Hash.ToLowerInvariant(), (Split-Path -Leaf $_.Path) }
[System.IO.File]::WriteAllLines((Join-Path $outputDir 'SHA256SUMS.txt'), $hashLines, [System.Text.UTF8Encoding]::new($false))

$hashes | Select-Object Path, Hash






