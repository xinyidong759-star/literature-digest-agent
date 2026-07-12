param(
    [string]$ProjectDir = "",
    [string]$Config = "config.labor_development_econ.json",
    [string]$OutputDir = "outputs_auto"
)

$ErrorActionPreference = "Stop"
if (-not $ProjectDir) {
    $ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}
Set-Location -LiteralPath $ProjectDir

$envPath = "HKCU:\Environment"
foreach ($name in @(
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SMTP_FROM",
    "SMTP_USE_TLS",
    "SMTP_USE_SSL",
    "DIGEST_EMAIL_TO",
    "OPENAI_API_KEY",
    "OPENAI_MODEL"
)) {
    $value = (Get-ItemProperty -Path $envPath -Name $name -ErrorAction SilentlyContinue).$name
    if ($value) {
        Set-Item -Path "Env:$name" -Value $value
    }
}

$logDir = Join-Path $ProjectDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$stamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$logPath = Join-Path $logDir "weekly_digest_$stamp.log"
$stdoutPath = Join-Path $logDir "weekly_digest_$stamp.out.log"
$stderrPath = Join-Path $logDir "weekly_digest_$stamp.err.log"

$pythonArgs = @(
    "literature_digest_agent.py",
    "--config",
    $Config,
    "--output-dir",
    $OutputDir,
    "--send-email"
)

$process = Start-Process `
    -FilePath "python" `
    -ArgumentList $pythonArgs `
    -WorkingDirectory $ProjectDir `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -NoNewWindow `
    -Wait `
    -PassThru

@(
    "ExitCode: $($process.ExitCode)",
    "",
    "=== STDOUT ===",
    (Get-Content -LiteralPath $stdoutPath -Raw -ErrorAction SilentlyContinue),
    "",
    "=== STDERR ===",
    (Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue)
) | Set-Content -LiteralPath $logPath -Encoding UTF8

if ($process.ExitCode -ne 0) {
    throw "Weekly digest failed with exit code $($process.ExitCode). See $logPath"
}
