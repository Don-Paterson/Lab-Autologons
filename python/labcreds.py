#!/usr/bin/env python3
"""
labcreds.py - lab passwords kept in Windows Credential Manager.

Shared by vsx.py, vsx-prov-tool.py and autohotkey/SicFill.ahk, which all
read the same entries:

    Lab-Autologons:CP_PW        cpadmin (management) password
    Lab-Autologons:SMS_SSH_PW   Gaia admin password (SSH to the SMS)
    Lab-Autologons:SIC_KEY      SIC activation key

Entries are encrypted by Windows under the current user's logon.

    py labcreds.py set      ask for all three and save them
    py labcreds.py show     list which ones are saved (never the values)
    py labcreds.py clear    delete them

An environment variable of the same name (e.g. CP_PW) overrides a saved
entry. For unattended setup, LAB_PASSWORD is used for any entry that has
no LAB_SSH_PASSWORD / LAB_SIC_KEY of its own.
"""
import getpass, os, sys

PREFIX = "Lab-Autologons:"
ENTRIES = {
    "CP_PW": "cpadmin password",
    "SMS_SSH_PW": "Gaia admin (SSH) password",
    "SIC_KEY": "SIC activation key",
}


def _wincred():
    try:
        from win32ctypes.pywin32 import win32cred
        return win32cred
    except ImportError:
        return None


def load(name):
    """Env var, then Credential Manager. None if neither has it."""
    if os.environ.get(name):
        return os.environ[name]
    wc = _wincred()
    if wc:
        try:
            cred = wc.CredRead(PREFIX + name, wc.CRED_TYPE_GENERIC)
            return cred["CredentialBlob"].decode("utf-16-le")
        except Exception:
            pass
    return None


def save(name, value):
    wc = _wincred()
    if not wc:
        raise RuntimeError("Windows Credential Manager is not available (pip install pywin32-ctypes)")
    wc.CredWrite({
        "Type": wc.CRED_TYPE_GENERIC,
        "TargetName": PREFIX + name,
        "UserName": name,
        "CredentialBlob": value,
        "Persist": wc.CRED_PERSIST_LOCAL_MACHINE,
        "Comment": "Lab-Autologons",
    }, 0)


def delete(name):
    wc = _wincred()
    if wc:
        try:
            wc.CredDelete(PREFIX + name, wc.CRED_TYPE_GENERIC)
            return True
        except Exception:
            pass
    return False


def secret(name, prompt):
    """Saved value, or ask (and offer to save it)."""
    value = load(name)
    if value:
        return value
    value = getpass.getpass(prompt)
    if _wincred() and input("Save in Windows Credential Manager? [y/N] ").lower() == "y":
        save(name, value)
    return value


def setup():
    base = os.environ.get("LAB_PASSWORD")
    if base:
        cp = base
        ssh = os.environ.get("LAB_SSH_PASSWORD") or base
        sic = os.environ.get("LAB_SIC_KEY") or base
    else:
        while True:
            cp = getpass.getpass("cpadmin password: ")
            if cp and cp == getpass.getpass("cpadmin password (again): "):
                break
            print("Empty or did not match, try again.")
        ssh = getpass.getpass("Gaia admin (SSH) password [Enter = same]: ") or cp
        sic = getpass.getpass("SIC activation key [Enter = same as cpadmin]: ") or cp
    for name, value in (("CP_PW", cp), ("SMS_SSH_PW", ssh), ("SIC_KEY", sic)):
        save(name, value)
    print("Saved to Windows Credential Manager.")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "set":
        setup()
    elif cmd == "clear":
        for name in ENTRIES:
            delete(name)
        print("Cleared.")
    elif cmd == "show":
        for name, desc in ENTRIES.items():
            state = "saved" if load(name) else "not set"
            print(f"  {PREFIX + name:28} {desc:28} {state}")
    else:
        sys.exit("usage: labcreds.py [set|show|clear]")


if __name__ == "__main__":
    main()
