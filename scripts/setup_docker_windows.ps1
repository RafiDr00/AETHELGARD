$ErrorActionPreference = 'Stop'

Write-Host '=== AETHELGARD Docker Setup (Windows) ==='

# 1) Enable WSL backend prerequisites
wsl --install --no-distribution

# 2) Download installer (re-runnable)
$downloadDir = Join-Path $PSScriptRoot '..\tools\docker-installer'
New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null
winget download -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements --download-directory $downloadDir

$installer = Get-ChildItem $downloadDir -Filter '*Docker*Desktop*_exe_*.exe' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $installer) {
  throw 'Docker Desktop installer not found in download directory.'
}

Write-Host "Installer: $($installer.FullName)"

# 3) Run elevated installer
Start-Process -FilePath $installer.FullName -ArgumentList 'install --accept-license --backend=wsl-2 --always-run-service --no-windows-containers' -Verb RunAs -Wait

# 4) Ensure docker CLI in PATH for current session
$dockerBin = "$Env:ProgramFiles\Docker\Docker\resources\bin"
if (Test-Path $dockerBin) {
  $Env:Path = "$Env:Path;$dockerBin"
}

# 5) Start Docker Desktop if needed
$dockerDesktop = "$Env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
if (Test-Path $dockerDesktop) {
  Start-Process -FilePath $dockerDesktop
}

# 6) Wait for daemon
$max = 60
$ok = $false
for ($i = 1; $i -le $max; $i++) {
  try {
    docker info *> $null
    if ($LASTEXITCODE -eq 0) {
      $ok = $true
      break
    }
  } catch {}
  Start-Sleep -Seconds 2
}
if (-not $ok) {
  throw 'Docker daemon did not become ready in time.'
}

# 7) Required verification commands
docker version
docker info
docker ps
docker run --rm hello-world

# 8) Verify strict sandbox flags actually work
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 64 --memory 256m busybox:latest /bin/sh -c "echo sandbox-ok"

# 9) Project preflight + tests
Set-Location (Join-Path $PSScriptRoot '..')
$env:APP_ENV = 'production'
if (-not $env:AETHELGARD_API_KEY) { $env:AETHELGARD_API_KEY = 'prod-local-key-change-me' }
if (-not $env:OTEL_EXPORTER_OTLP_ENDPOINT) { $env:OTEL_EXPORTER_OTLP_ENDPOINT = 'http://localhost:4317' }
python -c "from core.config import get_settings; from core.preflight import run_startup_preflight; run_startup_preflight(get_settings()); print('PREFLIGHT_OK')"
python -m pytest tests/test_sandbox_hardening.py tests/test_preflight.py -q

Write-Host '=== Docker setup and verification complete ==='
