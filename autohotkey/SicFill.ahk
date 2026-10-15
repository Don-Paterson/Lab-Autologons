#Requires AutoHotkey v2.0
#SingleInstance Force

; ---------------------------------------------------------------------------
; SIC Autofill for Check Point SmartConsole (+ optional MobaXterm hotkeys)
;   - Auto-fills Activation Key / Confirm Activation Key when the dialog appears
;   - Auto-fills the cpadmin password in the SmartConsole login window
;   - Ctrl+Alt+S  in SmartConsole : re-fill SIC key (e.g. after Reset)
;   - Ctrl+Alt+S  in MobaXterm    : type SIC key + Enter
;   - Ctrl+Alt+P  in MobaXterm    : type cpadmin password + Enter
;   - Ctrl+Alt+V  in MobaXterm    : answer vsx_util login (localhost, cpadmin, password)
;   - Also works in Tera Term (ttermpro.exe) and fills the vsx_login.ttl password box
; Passwords come from Windows Credential Manager (saved by deploy.ps1 /
; lab-creds set). If they are not there, they are asked for at startup.
; ---------------------------------------------------------------------------

; Read a generic credential's password (UTF-16 blob) from Credential Manager.
CredReadPw(target) {
    pCred := 0
    if !DllCall("Advapi32\CredReadW", "Str", target, "UInt", 1, "UInt", 0, "Ptr*", &pCred)
        return ""
    size := NumGet(pCred, A_PtrSize = 8 ? 32 : 24, "UInt")   ; CredentialBlobSize
    blob := NumGet(pCred, A_PtrSize = 8 ? 40 : 28, "Ptr")    ; CredentialBlob
    pw := StrGet(blob, size // 2, "UTF-16")
    DllCall("Advapi32\CredFree", "Ptr", pCred)
    return pw
}

AdminPw := CredReadPw("Lab-Autologons:CP_PW")
SicKey  := CredReadPw("Lab-Autologons:SIC_KEY")
if SicKey = ""
    SicKey := AdminPw

if SicKey = "" {
    ib := InputBox("SIC activation key for this session:", "SIC Autofill", "Password")
    if ib.Result != "OK"
        ExitApp
    SicKey := ib.Value
}
if AdminPw = "" {
    ib2 := InputBox("cpadmin password for SmartConsole login + terminal hotkeys (Cancel to skip):", "SIC Autofill", "Password")
    AdminPw := ib2.Result = "OK" ? ib2.Value : ""
}

; [window, Activation Key control, Confirm control]  (from Window Spy)
Targets := [
    ["VSX Gateway Wizard ahk_exe SmartConsole.exe", "Edit4", "Edit5"],
    ["Member Properties ahk_exe SmartConsole.exe",  "Edit4", "Edit5"],
]

Filled := Map()          ; windows already filled, so we don't keep re-filling
SetTimer CheckSic, 500
TrayTip "Running. Open a SIC dialog in SmartConsole.", "SIC Autofill"

CheckSic() {
    for t in Targets {
        if !(hwnd := WinActive(t[1])) || Filled.Has(hwnd)
            continue
        try {
            ; The wizard keeps every page loaded; only act on the SIC page
            if !ControlGetVisible(t[2], hwnd)
                continue
            FillSic(hwnd, t[2], t[3])
        }
    }
    ; Forget windows that have closed
    for h in [Filled*]
        if !WinExist(h)
            Filled.Delete(h)
}

; --- SmartConsole login window ---------------------------------------------
; WPF window (no ClassNN controls), so click the Password box by position.
LoginTitle := "Check Point SmartConsole ahk_exe SmartConsole.exe"
LoginPwX := 448, LoginPwY := 108   ; Password box, window coords (Window Spy)
AutoLogin := false                 ; true = also press Enter to log in
SetTimer CheckLogin, 500

CheckLogin() {
    if AdminPw = "" || !(hwnd := WinActive(LoginTitle)) || Filled.Has(hwnd)
        return
    WinGetPos ,, &w, &h, hwnd
    if w > 800 || h > 450          ; main SmartConsole window, not the login box
        return
    Filled[hwnd] := true
    Sleep 700                      ; let the dialog finish drawing
    if !WinActive(hwnd)
        return
    CoordMode "Mouse", "Window"
    MouseGetPos &mx, &my
    Click LoginPwX, LoginPwY
    SendText AdminPw
    if AutoLogin
        Send "{Enter}"
    MouseMove mx, my, 0
    ToolTip "Password filled"
    SetTimer () => ToolTip(), -1500
}

; --- Tera Term macro password box (vsx_login.ttl) ----------------------------
SetTimer CheckTtlPw, 300

CheckTtlPw() {
    if AdminPw = "" || !(hwnd := WinActive("vsx_util ahk_exe ttpmacro.exe")) || Filled.Has(hwnd)
        return
    Filled[hwnd] := true
    try {
        ControlSetText AdminPw, "Edit1", hwnd
        ControlSend "{Enter}", "Edit1", hwnd
    }
}

FillSic(hwnd, keyCtl, confCtl) {
    ControlSetText SicKey, keyCtl, hwnd
    ControlSetText SicKey, confCtl, hwnd
    Filled[hwnd] := true
    ToolTip "SIC key filled"
    SetTimer () => ToolTip(), -1500
}

#HotIf WinActive("ahk_exe SmartConsole.exe")
^!s:: {
    for t in Targets
        if hwnd := WinActive(t[1])
            try FillSic(hwnd, t[2], t[3])
}
#HotIf

#HotIf WinActive("ahk_exe MobaXterm.exe") || WinActive("ahk_exe ttermpro.exe")
^!s:: TypeToTerminal(SicKey)
^!p:: TypeToTerminal(AdminPw)
^!v:: {   ; vsx_util login: localhost, cpadmin, password
    KeyWait "Ctrl"
    KeyWait "Alt"
    SendEvent "{Enter}"       ; server IP -> localhost
    Sleep 300
    TypeToTerminal("cpadmin") ; admin name
    Sleep 300
    TypeToTerminal(AdminPw)   ; password
}
#HotIf

; Terminals can mangle input while Ctrl/Alt are still held, or drop
; characters sent too fast, so wait for release and type slowly.
TypeToTerminal(text) {
    if text = ""
        return
    KeyWait "Ctrl"
    KeyWait "Alt"
    SetKeyDelay 20, 10
    SendEvent "{Text}" text
    SendEvent "{Enter}"
}
