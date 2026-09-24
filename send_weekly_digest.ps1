param(
    [string]$ProjectDir = "",
    [string]$Config = "config.labor_development_econ.json",
    [string]$OutputDir = "outputs_auto",
    [string]$PythonExe = ""
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
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_MODEL"
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

if (-not $PythonExe) {
    $candidates = @(
        "C:\Users\32887\AppData\Local\Python\bin\python.exe",
        "C:\Users\32887\AppData\Local\Programs\Python\Python312\python.exe",
        "C:\Users\32887\AppData\Local\Programs\Python\Python311\python.exe",
        "python"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -eq "python") {
            $command = Get-Command python -ErrorAction SilentlyContinue
            if ($command) {
                $PythonExe = $command.Source
                break
            }
        } elseif (Test-Path -LiteralPath $candidate) {
            $PythonExe = $candidate
            break
        }
    }
}

if (-not $PythonExe) {
    throw "Python executable not found. Set -PythonExe to a valid python.exe path."
}

$pythonArgs = @(
    "literature_digest_agent.py",
    "--config",
    $Config,
    "--output-dir",
    $OutputDir,
    "--send-email"
)

$process = Start-Process `
    -FilePath $PythonExe `
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
