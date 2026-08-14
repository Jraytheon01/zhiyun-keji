$ErrorActionPreference = 'Stop'
$rootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$platformScript = Join-Path $rootDir 'zhiyun-keji-interactive-prototype\start-platform.ps1'
$learningComposeFile = Join-Path $rootDir 'services\zhiyun-learning-mcp\compose.local.yaml'

Write-Host 'Starting Zhiyun Keji dependencies...'
if (Get-Command docker -ErrorAction SilentlyContinue) {
    $knownContainers = docker ps -a --format '{{.Names}}'
    foreach ($containerName in @('meeting-assistant-mysql-1', 'meeting-assistant-milvus-1')) {
        if ($knownContainers -contains $containerName) {
            docker start $containerName | Out-Null
        }
    }
    if ($knownContainers -contains 'meeting-assistant-mysql-1') {
        # Reuse the local MySQL engine only. Education data lives in its own database.
        'CREATE DATABASE IF NOT EXISTS zhiyun_learning CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;' |
            docker exec -i meeting-assistant-mysql-1 sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD"'
        if ($LASTEXITCODE -ne 0) {
            throw 'Failed to initialize the isolated zhiyun_learning database.'
        }
    }
    if (Test-Path -LiteralPath $learningComposeFile) {
        # MCP, ingest API and worker all use the isolated zhiyun_learning database
        # and zyk_learning_ Milvus collections.
        docker compose -f $learningComposeFile up -d --build
        docker compose -f $learningComposeFile exec -T zhiyun-learning-mcp `
            python -m zhiyun_learning_mcp.migrate
        if ($LASTEXITCODE -ne 0) {
            throw 'Failed to initialize the Zhiyun Learning schema.'
        }
    }
} else {
    Write-Warning 'Docker is unavailable; the platform will still start, but MySQL and Zhiyun Learning MCP must already be reachable.'
}

& $platformScript
