$ErrorActionPreference = 'Continue'
$log = "$PSScriptRoot\windows_phase2b_enable_features.log"
if (Test-Path $log) { Remove-Item $log -Force }

function Run-Step {
    param([string]$Name, [string]$Cmd)
    "`n=== $Name ===" | Tee-Object -FilePath $log -Append
    "PS> $Cmd" | Tee-Object -FilePath $log -Append
    cmd.exe /c $Cmd 2>&1 | Tee-Object -FilePath $log -Append
    "EXIT=$LASTEXITCODE" | Tee-Object -FilePath $log -Append
}

Run-Step -Name "Enable Microsoft-Windows-Subsystem-Linux" -Cmd "dism /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all"
Run-Step -Name "Enable HypervisorPlatform" -Cmd "dism /online /enable-feature /featurename:HypervisorPlatform /all"
Run-Step -Name "Set WSL default version" -Cmd "wsl --set-default-version 2"
Run-Step -Name "WSL status" -Cmd "wsl --status"
Run-Step -Name "Virtualization section" -Cmd "systeminfo | findstr /I Virtualization"

"`nDONE" | Tee-Object -FilePath $log -Append
