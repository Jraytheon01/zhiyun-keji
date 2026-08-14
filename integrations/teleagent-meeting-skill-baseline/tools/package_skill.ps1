param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$skillFile = Join-Path $projectRoot 'SKILL.md'
$skillName = 'toby-ai-recorder-assistant'
$distDir = Join-Path $projectRoot 'dist'

if (-not (Test-Path -LiteralPath $skillFile)) {
    throw "SKILL.md not found: $skillFile"
}

$content = Get-Content -LiteralPath $skillFile -Raw -Encoding UTF8
if ($content -notmatch '(?m)^name:\s+\S.+$') {
    throw 'SKILL.md frontmatter must contain a non-empty name'
}
if ($content -notmatch '(?m)^description:\s+.+$') {
    throw 'SKILL.md frontmatter must contain description'
}

$buildRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
        'toby-ai-recorder-assistant-build-' + [Guid]::NewGuid().ToString('N')
)
$packageRoot = Join-Path $buildRoot $skillName
$zipPath = Join-Path $buildRoot "$skillName-v$Version.zip"
$outputPath = Join-Path $distDir "$skillName-v$Version.skill"

try {
    New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null
    Copy-Item -LiteralPath $skillFile -Destination (Join-Path $packageRoot 'SKILL.md')

    foreach ($folder in @('agents', 'references', 'scripts', 'assets')) {
        $source = Join-Path $projectRoot $folder
        if (Test-Path -LiteralPath $source) {
            $files = Get-ChildItem -LiteralPath $source -File -Recurse
            if ($files) {
                Copy-Item -LiteralPath $source -Destination $packageRoot -Recurse
            }
        }
    }

    New-Item -ItemType Directory -Path $distDir -Force | Out-Null
    if (Test-Path -LiteralPath $outputPath) {
        throw "Package already exists; choose a new version: $outputPath"
    }
    Compress-Archive -LiteralPath $packageRoot -DestinationPath $zipPath -CompressionLevel Optimal
    Move-Item -LiteralPath $zipPath -Destination $outputPath
    Write-Host "Created: $outputPath"
}
finally {
    if (Test-Path -LiteralPath $buildRoot) {
        Remove-Item -LiteralPath $buildRoot -Recurse -Force
    }
}
