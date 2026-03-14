$ErrorActionPreference = 'Stop'
$log = "$PSScriptRoot\windows_postreboot_phases_2_7.log"
if (Test-Path $log) { Remove-Item $log -Force }

function Log($msg) {
    $msg | Tee-Object -FilePath $log -Append
}

function Run-Step {
    param(
        [string]$Name,
        [string]$Command,
        [switch]$AllowFailure
    )
    Log "`n=== $Name ==="
    Log "PS> $Command"
    cmd.exe /c $Command 2>&1 | Tee-Object -FilePath $log -Append
    $rc = $LASTEXITCODE
    Log "EXIT=$rc"
    if (-not $AllowFailure -and $rc -ne 0) {
        throw "Step failed: $Name (exit $rc)"
    }
}

# Must run elevated
$wid = [Security.Principal.WindowsIdentity]::GetCurrent()
$wp = New-Object Security.Principal.WindowsPrincipal($wid)
if (-not $wp.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Administrator token required"
}

# PHASE 2
Run-Step -Name "WSL status" -Command "wsl --status"
Run-Step -Name "Set default WSL version 2" -Command "wsl --set-default-version 2"
Run-Step -Name "WSL list verbose" -Command "wsl --list --verbose" -AllowFailure

# PHASE 3
Run-Step -Name "System virtualization section" -Command "systeminfo | findstr /I Virtualization"

# PHASE 4
Log "`n=== Install Docker Desktop ==="
$dockerCliPath = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
if (Test-Path $dockerCliPath) {
    Log "Docker Desktop already appears installed."
} else {
    $installer = "C:\Users\RAFI ABDENNOUR\OneDrive\Desktop\ALLPROJECTS\AETHELGARD\tools\docker-installer\Docker Desktop_4.63.0_Machine_X64_exe_en-US.exe"
    if (-not (Test-Path $installer)) {
        throw "Docker installer artifact not found at $installer"
    }
    Log "PS> \"$installer\" install --accept-license --backend=wsl-2 --always-run-service --no-windows-containers"
    $proc = Start-Process -FilePath $installer -ArgumentList "install --accept-license --backend=wsl-2 --always-run-service --no-windows-containers" -Wait -PassThru
    Log "EXIT=$($proc.ExitCode)"
}

if (Test-Path "C:\Program Files\Docker\Docker\resources\bin\docker.exe") {
    Log "DOCKER_PATH_PRESENT"
} else {
    Log "DOCKER_PATH_MISSING"
}

Get-Service com.docker.service -ErrorAction SilentlyContinue | Format-List Status,Name,DisplayName | Out-String | Tee-Object -FilePath $log -Append
Get-Process "Docker Desktop" -ErrorAction SilentlyContinue | Format-List ProcessName,Id,StartTime | Out-String | Tee-Object -FilePath $log -Append

if (-not (Get-Process "Docker Desktop" -ErrorAction SilentlyContinue)) {
    $desktopExe = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $desktopExe) {
        Start-Process -FilePath $desktopExe
        Start-Sleep -Seconds 15
    }
}

# ensure docker cli in path
$dockerBin = "C:\Program Files\Docker\Docker\resources\bin"
if (Test-Path $dockerBin) {
    $Env:Path = "$Env:Path;$dockerBin"
}

# wait for daemon
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        docker info *> $null
        if ($LASTEXITCODE -eq 0) {
            $ready = $true
            break
        }
    } catch {}
    Start-Sleep -Seconds 2
}
if (-not $ready) {
    throw "Docker daemon not ready"
}

# PHASE 5
Run-Step -Name "docker version" -Command "docker version"
Run-Step -Name "docker info" -Command "docker info"
Run-Step -Name "docker ps" -Command "docker ps"
Run-Step -Name "docker hello-world" -Command "docker run --rm hello-world"

# PHASE 6
Run-Step -Name "sandbox restricted container" -Command "docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m alpine echo SANDBOX_OK"

# PHASE 7
Set-Location "C:\Users\RAFI ABDENNOUR\OneDrive\Desktop\ALLPROJECTS\AETHELGARD"
if (-not $Env:AETHELGARD_API_KEY) { Write-Error 'AETHELGARD_API_KEY must be set before running phase 7'; exit 1 }
if (-not $Env:OTEL_EXPORTER_OTLP_ENDPOINT) { $Env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://localhost:4317" }
if (-not $Env:APP_ENV) { $Env:APP_ENV = "production" }
Run-Step -Name "project preflight" -Command "python -m core.preflight"

Log "`nALL_PHASES_COMPLETE"
