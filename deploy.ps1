<#
  Lab-Autologons - lab deployment script

  Run from an elevated (Administrator) PowerShell window:

    irm https://raw.githubusercontent.com/Don-Paterson/Lab-Autologons/main/deploy.ps1 | iex

  You will be asked for the lab passwords once. To run without prompts, set:

    $env:LAB_PASSWORD = 'secret'          # cpadmin, Gaia admin and SIC key
    # optional, if they differ:  $env:LAB_SSH_PASSWORD / $env:LAB_SIC_KEY

  Or pass parameters:

    & ([scriptblock]::Create((irm https://raw.githubusercontent.com/Don-Paterson/Lab-Autologons/main/deploy.ps1))) -ResetCredentials

  What it does:
    1. Downloads this repo to C:\LabAutologons
    2. Installs Python 3.13 (if missing) and the Python packages
    3. Installs AutoHotkey v2 (if missing)
    4. Puts C:\LabAutologons\bin on PATH  (vsx, vsx-prov, lab-creds commands)
    5. Saves the lab passwords in Windows Credential Manager
    6. Starts SicFill.ahk now and at every logon
#>
param(
    [string]$InstallDir = 'C:\LabAutologons',
    [string]$Repo = 'Don-Paterson/Lab-Autologons',
    [string]$Branch = 'main',
    [string]$PythonVersion = '3.13.1',
    # Ask for the passwords again even if they are already saved.
    [switch]$ResetCredentials,
    # Don't start SicFill.ahk or add it to Startup.
    [switch]$NoAutoStart
)

& {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
    function Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }
    function Warn($msg) { Write-Host "    $msg" -ForegroundColor Yellow }

    function Update-SessionPath {
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                    [Environment]::GetEnvironmentVariable('Path', 'User')
    }

    function Test-PythonOK {
        try {
            $v = & py -3 --version 2>$null
            if ($LASTEXITCODE -eq 0 -and $v -match 'Python (\d+)\.(\d+)') {
                $maj = [int]$Matches[1]; $min = [int]$Matches[2]
                return ($maj -gt 3 -or ($maj -eq 3 -and $min -ge 11))
            }
        } catch { }
        return $false
    }

    function Find-AutoHotkey {
        $candidates = @(
            "$env:ProgramFiles\AutoHotkey\v2\AutoHotkey64.exe",
            "$env:LOCALAPPDATA\Programs\AutoHotkey\v2\AutoHotkey64.exe",
            (Join-Path $InstallDir 'AutoHotkey\AutoHotkey64.exe')
        )
        $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    }

    # --- 0. Must be admin (installs software, writes to C:\ and machine PATH) ---
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
               ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-Host "Please run this from PowerShell opened with 'Run as administrator'." -ForegroundColor Red
        return
    }

    # --- 1. Download the repo ---------------------------------------------------
    Step "Downloading $Repo ($Branch) to $InstallDir"
    $tmp = Join-Path $env:TEMP ('lab-autologons-' + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $tmp | Out-Null
    $zip = Join-Path $tmp 'repo.zip'
    Invoke-WebRequest -UseBasicParsing "https://github.com/$Repo/archive/refs/heads/$Branch.zip" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $src = Get-ChildItem $tmp -Directory | Select-Object -First 1
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    foreach ($item in 'python', 'autohotkey', 'bin', 'examples', 'sms', 'teraterm', 'README.md') {
        $from = Join-Path $src.FullName $item
        if (Test-Path $from) { Copy-Item $from $InstallDir -Recurse -Force }
    }
    Remove-Item $tmp -Recurse -Force
    Ok "Files in $InstallDir"

    # --- 2. Python ----------------------------------------------------------------
    Step 'Python'
    Update-SessionPath
    if (Test-PythonOK) {
        Ok "Already installed: $(py -3 --version)"
    } else {
        $url = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe"
        $exe = Join-Path $env:TEMP "python-$PythonVersion-amd64.exe"
        Write-Host "    Downloading $url"
        Invoke-WebRequest -UseBasicParsing $url -OutFile $exe
        Write-Host '    Installing (about a minute)'
        Start-Process $exe -Wait -ArgumentList '/quiet', 'InstallAllUsers=1', 'PrependPath=1',
            'Include_pip=1', 'Include_test=0', 'Include_launcher=1'
        Remove-Item $exe -Force -ErrorAction SilentlyContinue
        Update-SessionPath
        if (-not (Test-PythonOK)) { throw "Python installed but 'py -3' does not work." }
        Ok "Installed: $(py -3 --version)"
    }

    Write-Host '    Installing Python packages (paramiko, pywin32-ctypes)'
    & py -3 -m pip install --quiet --disable-pip-version-check -r (Join-Path $InstallDir 'python\requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'pip install failed.' }
    Ok 'Packages installed'

    # --- 3. AutoHotkey v2 ---------------------------------------------------------
    Step 'AutoHotkey v2'
    $ahk = Find-AutoHotkey
    if ($ahk) {
        Ok "Already installed: $ahk"
    } else {
        $setup = Join-Path $env:TEMP 'ahk-v2-setup.exe'
        Invoke-WebRequest -UseBasicParsing 'https://www.autohotkey.com/download/ahk-v2.exe' -OutFile $setup
        Start-Process $setup -ArgumentList '/silent' -Wait
        Remove-Item $setup -Force -ErrorAction SilentlyContinue
        for ($i = 0; $i -lt 10 -and -not ($ahk = Find-AutoHotkey); $i++) { Start-Sleep -Seconds 1 }

        if (-not $ahk) {
            Warn 'Installer did not finish; using the portable version instead'
            $azip = Join-Path $env:TEMP 'ahk-v2.zip'
            Invoke-WebRequest -UseBasicParsing 'https://www.autohotkey.com/download/ahk-v2.zip' -OutFile $azip
            Expand-Archive $azip -DestinationPath (Join-Path $InstallDir 'AutoHotkey') -Force
            Remove-Item $azip -Force
            $ahk = Find-AutoHotkey
        }
        if (-not $ahk) { throw 'AutoHotkey v2 could not be installed.' }
        Ok "Installed: $ahk"
    }

    # --- 4. PATH --------------------------------------------------------------------
    Step "Adding $InstallDir\bin to PATH"
    $bin = Join-Path $InstallDir 'bin'
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    if (($machinePath -split ';') | Where-Object { $_.TrimEnd('\') -eq $bin }) {
        Ok 'Already on PATH'
    } else {
        [Environment]::SetEnvironmentVariable('Path', "$machinePath;$bin", 'Machine')
        Ok 'Added (new windows will have vsx, vsx-prov and lab-creds)'
    }
    Update-SessionPath

    # --- 5. Passwords -----------------------------------------------------------------
    Step 'Lab passwords (Windows Credential Manager)'
    $labcreds = Join-Path $InstallDir 'python\labcreds.py'
    $saved = & py -3 $labcreds show
    if (-not $ResetCredentials -and -not ($saved -match 'not set')) {
        Ok 'Already saved (use -ResetCredentials to change them)'
    } else {
        & py -3 $labcreds set
        if ($LASTEXITCODE -ne 0) { throw 'Saving the passwords failed.' }
    }

    # --- 6. SicFill.ahk ---------------------------------------------------------------
    if ($NoAutoStart) {
        Warn 'Skipping SicFill.ahk autostart (-NoAutoStart)'
    } else {
        Step 'Starting SicFill.ahk (and at every logon)'
        $script = Join-Path $InstallDir 'autohotkey\SicFill.ahk'
        $lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'SIC Autofill.lnk'
        $shell = New-Object -ComObject WScript.Shell
        $sc = $shell.CreateShortcut($lnk)
        $sc.TargetPath = $ahk
        $sc.Arguments = "`"$script`""
        $sc.WorkingDirectory = Split-Path $script
        $sc.Save()
        Start-Process $ahk -ArgumentList "`"$script`""    # #SingleInstance Force replaces a running copy
        Ok "Running. Startup shortcut: $lnk"
    }

    Step 'Done'
    Write-Host @"

    Open a NEW PowerShell window, then:

      vsx show_interfaces                      vsx_util with auto-login
      vsx reconfigure                          ... also fills the Activation Key
      vsx-prov -f $InstallDir\examples\a-app-gw.txt
      lab-creds show | set | clear             manage the saved passwords

    SmartConsole: SIC key and login password fill in automatically.
    MobaXterm / Tera Term: Ctrl+Alt+P password, Ctrl+Alt+S SIC key, Ctrl+Alt+V vsx_util login.

"@ -ForegroundColor Yellow
}
