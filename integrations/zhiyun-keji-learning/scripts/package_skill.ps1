param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version
)

$ErrorActionPreference = 'Stop'
$skillRoot = Split-Path -Parent $PSScriptRoot
$skillFile = Join-Path $skillRoot 'SKILL.md'
$skillName = 'zhiyun-keji-learning'
$distDir = Join-Path $skillRoot 'dist'
$buildRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
    'zhiyun-keji-learning-build-' + [Guid]::NewGuid().ToString('N')
)
$packageRoot = Join-Path $buildRoot $skillName
$zipPath = Join-Path $buildRoot "$skillName-v$Version.zip"
$outputPath = Join-Path $distDir "$skillName-v$Version.skill"

if (-not (Test-Path -LiteralPath $skillFile)) {
    throw "SKILL.md not found: $skillFile"
}

try {
    New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null
    Copy-Item -LiteralPath $skillFile -Destination (Join-Path $packageRoot 'SKILL.md')

    foreach ($folder in @('agents', 'references')) {
        $source = Join-Path $skillRoot $folder
        if (Test-Path -LiteralPath $source) {
            Copy-Item -LiteralPath $source -Destination $packageRoot -Recurse
        }
    }

    New-Item -ItemType Directory -Path $distDir -Force | Out-Null
    if (Test-Path -LiteralPath $outputPath) {
        throw "Package already exists; choose a new version: $outputPath"
    }
    Compress-Archive -LiteralPath $packageRoot -DestinationPath $zipPath -CompressionLevel Optimal
    Move-Item -LiteralPath $zipPath -Destination $outputPath
    Write-Output "Created: $outputPath"
}
finally {
    if (Test-Path -LiteralPath $buildRoot) {
        Remove-Item -LiteralPath $buildRoot -Recurse -Force
    }
}
