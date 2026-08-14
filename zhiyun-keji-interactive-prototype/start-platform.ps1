$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $projectDir
$receiverDir = Join-Path $rootDir 'integrations\teleagent-local-receiver'
$receiverScript = Join-Path $receiverDir 'scripts\auto_ppt_service.py'
$receiverConfig = Join-Path $receiverDir 'config.zhiyun-keji.json'
$dataDir = Join-Path $projectDir 'data'
$envFile = Join-Path $projectDir '.env'
$venvPython = Join-Path $projectDir '.venv\Scripts\python.exe'
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

function Find-PythonRuntime {
    try {
        $command = Get-Command python -ErrorAction Stop
        & $command.Source --version *> $null
        if ($LASTEXITCODE -eq 0) { return $command.Source }
    } catch {}

    $runtimeRoot = Join-Path $env:USERPROFILE '.cache\codex-runtimes'
    if (Test-Path -LiteralPath $runtimeRoot) {
        $candidate = Get-ChildItem -LiteralPath $runtimeRoot -Recurse -Filter python.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -like '*\dependencies\python\python.exe' } |
            Select-Object -First 1
        if ($candidate) { return $candidate.FullName }
    }
    return $null
}

$bootstrapPython = Find-PythonRuntime
if (-not $bootstrapPython) {
    throw 'No Python runtime is available for the project TeleAgent Receiver.'
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host 'Creating the project Python environment...'
    & $bootstrapPython -m venv (Join-Path $projectDir '.venv')
    & $venvPython -m pip install -r (Join-Path $projectDir 'requirements.txt')
}
$pythonExe = $venvPython

$receiverProcess = $null
$receiverListening = Get-NetTCPConnection -LocalPort 18768 -State Listen -ErrorAction SilentlyContinue
if (-not $receiverListening) {
    $receiverOut = Join-Path $dataDir 'receiver.stdout.log'
    $receiverErr = Join-Path $dataDir 'receiver.stderr.log'
    $receiverProcess = Start-Process -WindowStyle Hidden -PassThru -FilePath $pythonExe `
        -WorkingDirectory $receiverDir `
        -ArgumentList @($receiverScript, '--config', $receiverConfig) `
        -RedirectStandardOutput $receiverOut -RedirectStandardError $receiverErr
    Start-Sleep -Milliseconds 900
    if (-not (Get-NetTCPConnection -LocalPort 18768 -State Listen -ErrorAction SilentlyContinue)) {
        throw "Project TeleAgent Receiver failed to start. Check $receiverErr"
    }
    Write-Host 'Zhiyun Keji TeleAgent Receiver is ready on 127.0.0.1:18768.'
} else {
    Write-Host 'Using the Receiver already listening on 127.0.0.1:18768.'
}

if (-not (Test-Path -LiteralPath $envFile)) {
    Write-Host 'Using demo defaults. Copy .env.example to .env to connect MySQL and AI.'
}

Write-Host 'Opening platform at http://127.0.0.1:18910'
try {
    $mysqlLine = Get-Content -LiteralPath $envFile -ErrorAction SilentlyContinue | Where-Object { $_ -match '^\ufeff?MYSQL_HOST=' } | Select-Object -First 1
    if ($mysqlLine -and (($mysqlLine -split '=', 2)[1].Trim() -eq 'mysql')) {
        $env:MYSQL_HOST = '127.0.0.1'
        $env:MYSQL_PORT = '3307'
    }
    $env:TELEAGENT_RECEIVER_URL = 'http://127.0.0.1:18768'
    $env:PLATFORM_PUBLIC_URL = 'http://127.0.0.1:18910'
    & $pythonExe (Join-Path $projectDir 'server.py') --host 127.0.0.1 --port 18910
} finally {
    if ($receiverProcess -and -not $receiverProcess.HasExited) {
        Stop-Process -Id $receiverProcess.Id
        Write-Host 'Project TeleAgent Receiver stopped.'
    }
}
