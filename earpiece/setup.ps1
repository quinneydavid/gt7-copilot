# GT7 Copilot PC earpiece - installer for the sim PC. Downloaded from the copilot page (address and token already filled in).
# Run in an ADMIN PowerShell as the user who drives:
#     powershell -ExecutionPolicy Bypass -File "$HOME\Downloads\gt7copilot-earpiece-setup.ps1"
# It installs Python if missing, puts the earpiece in %LOCALAPPDATA%\GT7Copilot and runs it as the scheduled task
# "GT7 Copilot earpiece" (SYSTEM, from boot). Not inside your sign-in on purpose: in a Remote Desktop or other remote session
# Windows hides the PC's own sound devices (only "Remote Audio" is left), a system task keeps them.
# The task runs as SYSTEM from this folder, which the installing user can write: on a shared PC install it from an
# administrator account that others do not use (docs/earpiece.md).
# Run it again any time to update. Remove: Unregister-ScheduledTask "GT7 Copilot earpiece", delete the GT7Copilot folder.
$ErrorActionPreference = 'Stop'
$Url   = '__GT7C_URL__'
$Token = '__GT7C_TOKEN__'
$Dir   = Join-Path $env:LOCALAPPDATA 'GT7Copilot'
$Cfg   = Join-Path $Dir 'earpiece.json'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this in an ADMIN PowerShell (right-click PowerShell -> Run as administrator): the earpiece is installed as a system task.'
}
New-Item -ItemType Directory -Force -Path $Dir | Out-Null

function Find-Python {
    foreach ($c in @('py -3', 'python')) {
        try {
            $exe, $rest = $c -split ' '
            $p = & $exe @($rest + @('-c', 'import sys; print(sys.executable)')) 2>$null
            if ($LASTEXITCODE -eq 0 -and $p -and (Test-Path $p)) { return $p }
        } catch {}
    }
    $g = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
    if ($g) { return $g.FullName }
    return $null
}

Write-Host '== 1. Python'
$py = Find-Python
if (-not $py) {
    Write-Host 'not found - installing with winget (per-user)'
    winget install -e --id Python.Python.3.13 --scope user --silent --accept-package-agreements --accept-source-agreements
    $py = Find-Python
    if (-not $py) { throw 'Python is still not found. Install it from python.org, then run this again.' }
}
Write-Host "using $py"

Write-Host '== 2. earpiece program'
$venv = Join-Path $Dir 'venv'
if (-not (Test-Path "$venv\Scripts\python.exe")) { & $py -m venv $venv }
& "$venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check --upgrade sounddevice numpy pycaw comtypes psutil
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
Invoke-WebRequest -UseBasicParsing -Uri "$Url/earpiece/earpiece.py" -Headers @{ 'X-GT7C-Earpiece' = $Token } -OutFile (Join-Path $Dir 'earpiece.py')

Write-Host '== 3. settings'
$old = $null
if (Test-Path $Cfg) { try { $old = Get-Content $Cfg -Raw | ConvertFrom-Json } catch {} }
$device = if ($old -and $old.device) { $old.device } else { 'AirPods' }
$ans = Read-Host "Name of the headset or earbud as Windows shows it under Sound (part of the name is enough) [$device]"
if ($ans) { $device = $ans }
$simhub = if ($old -and $old.simhub_path) { $old.simhub_path } else { 'C:\Program Files (x86)\SimHub\SimHubWPF.exe' }
if (-not (Test-Path $simhub)) { Write-Host "note: SimHub not found at $simhub - edit simhub_path in $Cfg if it lives elsewhere" }
$connect = if ($old -and $old.connect_when) { $old.connect_when } else { 'always' }
$volume = if ($old -and ($null -ne $old.volume)) { $old.volume } else { 0.6 }
$voice = if ($old -and ($null -ne $old.voice)) { [bool]$old.voice } else { '__GT7C_VOICE__' -eq '1' }   # new install: as Voice control is set on the server
$start = if ($old -and ($null -ne $old.start_simhub)) { [bool]$old.start_simhub } else { $false }   # new install: off (as SYSTEM it cannot start SimHub anyway)
[ordered]@{ url = $Url; token = $Token; device = $device; volume = $volume; voice = $voice; simhub_path = $simhub; start_simhub = $start; connect_when = $connect } |
    ConvertTo-Json | Set-Content -Path $Cfg -Encoding UTF8

Write-Host '== 4. system task (from boot)'
Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*.exe' -and $_.CommandLine -like '*earpiece.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
$act = New-ScheduledTaskAction -Execute "$venv\Scripts\python.exe" -Argument "`"$Dir\earpiece.py`" --home `"$Dir`" supervise" -WorkingDirectory $Dir
$trg = New-ScheduledTaskTrigger -AtStartup
$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'GT7 Copilot earpiece' -Action $act -Trigger $trg -Settings $set -User 'SYSTEM' -RunLevel Highest -Force | Out-Null
Start-ScheduledTask -TaskName 'GT7 Copilot earpiece'

Write-Host ''
Write-Host "DONE: the earpiece runs as the system task 'GT7 Copilot earpiece' and starts at every boot. Log: $Dir\earpiece.log"
Write-Host 'The copilot page (Live tab) shows a "Earpiece" tile within 10 seconds: device connected or not.'
Write-Host 'SimHub: the earpiece only reports whether it runs. Use SimHub''s own "start with Windows" setting to start it.'
