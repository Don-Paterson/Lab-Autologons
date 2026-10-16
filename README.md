# Lab-Autologons

Password and SIC-key autofill for Check Point lab work, installed onto a fresh
lab Windows machine with one command.

| Where | What gets filled in |
|---|---|
| SmartConsole login | cpadmin password |
| SmartConsole VSX Gateway / Cluster wizards | SIC Activation Key + Confirm |
| SmartConsole gateway *Trusted Communication* | One-time password (SIC key) |
| `vsx_util` (any command) | SMS IP (localhost), `cpadmin`, password, Activation Key |
| `vsx_provisioning_tool` | password (`-p`), from a command file |
| `cpconfig` on a gateway (SIC reset) | expert password, Activation Key + Retype |
| Ubuntu / Linux servers (`ubrun`) | SSH login as cpadmin, `sudo` password |
| MobaXterm / Tera Term | hotkeys for password, SIC key and `vsx_util` login |

## Deploy to a new lab machine

Open **PowerShell as Administrator** and run:

```powershell
irm https://raw.githubusercontent.com/Don-Paterson/Lab-Autologons/main/deploy.ps1 | iex
```

You'll be asked once for the cpadmin password, the Gaia admin (SSH) password
and the SIC activation key (press Enter on the last two to reuse the cpadmin
password). The script then:

1. Downloads this repo to `C:\LabAutologons`
2. Installs Python 3.13 (if missing) plus `paramiko` and `pywin32-ctypes`
3. Installs AutoHotkey v2 (if missing; falls back to the portable zip)
4. Adds `C:\LabAutologons\bin` to PATH: `vsx`, `vsx-prov`, `cprun`, `ubrun`, `lab-creds`
5. Saves the passwords in **Windows Credential Manager**
6. Starts `SicFill.ahk` now and adds it to Startup

Running it again updates the files and skips anything already installed.

### No prompts

```powershell
$env:LAB_PASSWORD = 'secret'     # used for all three unless overridden:
# $env:LAB_SSH_PASSWORD = '...'; $env:LAB_SIC_KEY = '...'
irm https://raw.githubusercontent.com/Don-Paterson/Lab-Autologons/main/deploy.ps1 | iex
```

### Options

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/Don-Paterson/Lab-Autologons/main/deploy.ps1))) -ResetCredentials
```

| Option | Meaning |
|---|---|
| `-ResetCredentials` | Ask for the passwords again even if they are saved |
| `-NoAutoStart` | Don't start `SicFill.ahk` or add it to Startup |
| `-InstallDir` | Install somewhere other than `C:\LabAutologons` |
| `-PythonVersion` | Python to install if none is present (default 3.13.1) |

## Use

Open a **new** PowerShell window after deploying (so PATH is refreshed).

```powershell
vsx show_interfaces            # vsx_util on A-SMS, login answered for you
vsx reconfigure                # ... and the Activation Key prompts too
vsx vsls --host 10.1.1.101     # other SMS

vsx-prov -f C:\LabAutologons\examples\a-app-gw.txt
vsx-prov -y -f my-vs.txt       # no "Run this?" confirmation

cprun 10.1.1.2 cpconfig        # reset SIC on a gateway (you pick the menu option)
cprun 10.1.1.2                 # just log in, straight to Expert mode

ubrun 192.168.13.101 sudo apt update   # Ubuntu: sudo password typed for you
ubrun 192.168.13.101                   # just log in as cpadmin

lab-creds show                 # which passwords are saved
lab-creds set                  # change them
lab-creds clear                # remove them
```

`vsx` connects over SSH as `admin` (SSH key if you have one, otherwise the
saved Gaia password), runs `vsx_util`, answers the login prompts, then hands
the session to you. The output looks the same as typing it by hand.

`cprun` works on any Gaia box. It logs in as `admin`; if that lands in clish it
types `expert` and the expert password (the saved Gaia password, or
`Lab-Autologons:EXPERT_PW` if you save one with that name). It then runs the
command, answers `Enter/Retype Activation Key` with the saved SIC key (and the
`vsx_util` login prompts, if the command is `vsx_util`), and closes when the
command finishes. Menus and y/n questions are left to you.

`ubrun` is for ordinary Linux servers (not Check Point). It logs in as
`cpadmin` with the saved cpadmin password (`--user` / `--pw CP_PW` to change),
runs the command, answers `[sudo] password for ...:` with the same password
(at most twice, so a wrong one doesn't loop), and closes when the prompt
returns.

`vsx-prov` takes one transaction per line (see `examples/a-app-gw.txt`) and runs
`vsx_provisioning_tool -s localhost -u cpadmin -p ... -o <lines joined with ", ">`.
The password goes over the SSH session's input, not the command line.

### SicFill.ahk

Runs in the tray (green **H**). It reads the passwords from Credential Manager.

* **SmartConsole**: fills the login password, the SIC Activation Key in the
  VSX Gateway Wizard and Cluster *Member Properties* dialogs, and the
  One-time password in a gateway's *Trusted Communication* dialog. It only
  fills when that label is showing and the box is usable, so existing objects
  (e.g. *Cluster Member Properties - A-VSX-02*) are left alone.
  **Ctrl+Alt+S** re-fills after **Reset**.
* **MobaXterm / Tera Term**: **Ctrl+Alt+P** cpadmin password, **Ctrl+Alt+S**
  SIC key, **Ctrl+Alt+V** answers the `vsx_util` login prompts.

If SmartConsole is run as administrator, `SicFill.ahk` must be too.

## Other files

| Path | Purpose |
|---|---|
| `sms/vsxu` | Same prompt answering, run **on** the SMS: `read -rs CP_PW; export CP_PW; ~/vsxu vsls` |
| `teraterm/vsx_login.ttl` | Tera Term macro that waits for the `vsx_util` prompts |
| `python/labcreds.py` | Credential Manager helper used by everything above |

Lab use: passwords are stored per Windows user, encrypted by Windows.
