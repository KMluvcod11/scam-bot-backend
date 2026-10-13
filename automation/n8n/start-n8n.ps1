param([string]$NodeExecutable = "node")

$ErrorActionPreference = "Stop"
$nodeVersion = & $NodeExecutable -p "process.versions.node"
if ([version]$nodeVersion -lt [version]"24.0.0") {
    throw "n8n requires Node.js 24 or newer. Pass -NodeExecutable with the path to Node.js 24."
}
$n8nEntry = Join-Path $PSScriptRoot "node_modules/n8n/bin/n8n"
if (-not (Test-Path -LiteralPath $n8nEntry)) {
    throw "Install the dependencies in this folder before starting n8n."
}

# แยกข้อมูล workflow/credentials ออกจากซอร์สโค้ด และเปิดเฉพาะเครื่องนี้
$env:N8N_USER_FOLDER = Join-Path $PSScriptRoot ".runtime"
$env:N8N_LISTEN_ADDRESS = "127.0.0.1"
$env:GENERIC_TIMEZONE = "Asia/Bangkok"
$env:TZ = "Asia/Bangkok"
$env:N8N_DIAGNOSTICS_ENABLED = "false"

& $NodeExecutable $n8nEntry start
exit $LASTEXITCODE
