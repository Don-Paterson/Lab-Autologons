#!/usr/bin/env python3
"""
vsx.py - run vsx_util on A-SMS over SSH and answer its login prompts.

    py vsx.py show_interfaces          (any vsx_util command + args)
    py vsx.py vsls --host 10.1.1.101

SSH login:   SSH key if you have one, otherwise the Gaia admin password.
Passwords:   Windows Credential Manager (see labcreds.py), else asked.
Also answers "Enter/Retype Activation Key" with the saved SIC key.
After the login prompts are answered you drive vsx_util as normal.
Needs:  py -m pip install paramiko pywin32-ctypes
"""
import argparse, os, shlex, shutil, socket, sys, threading, time

import paramiko

from labcreds import load, secret
from termclean import Cleaner

def connect(host, user, port, pw_name="SMS_SSH_PW"):
    """SSH key first, then the saved password named pw_name."""
    def client():
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        return c
    c = client()
    try:
        c.connect(host, port=port, username=user, timeout=10)    # SSH key / agent
        return c
    except paramiko.SSHException:      # no key, or key not accepted
        c.close()
    except OSError as e:               # host down, wrong IP, port closed
        sys.exit(f"Could not connect to {host}:{port}: {e}")
    c = client()
    try:
        c.connect(host, port=port, username=user, timeout=10,
                  password=secret(pw_name, f"{user}@{host} SSH password: "),
                  look_for_keys=False, allow_agent=False)
    except paramiko.AuthenticationException:
        sys.exit(f"Login failed for {user}@{host}: wrong user or password.\n"
                 f"Check --user, or the saved password (lab-creds show / lab-creds set).")
    except (OSError, paramiko.SSHException) as e:
        sys.exit(f"Could not connect to {host}:{port}: {e}")
    return c


# ---- keyboard -> channel (Windows console, or POSIX tty for testing) --------
if os.name == "nt":
    import msvcrt
    os.system("")                      # turn on ANSI colours in the console
    ARROWS = {"H": "\x1b[A", "P": "\x1b[B", "M": "\x1b[C", "K": "\x1b[D",
              "G": "\x1b[H", "O": "\x1b[F", "S": "\x1b[3~"}

    def pump_keys(chan):
        while msvcrt.kbhit():          # drop keys left over from the y/N prompts
            msvcrt.getwch()
        while not chan.closed:
            if not msvcrt.kbhit():
                time.sleep(0.02)
                continue
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):               # arrow / function keys
                seq = ARROWS.get(msvcrt.getwch())
                if seq:
                    chan.send(seq)
            elif ch == "\r":
                chan.send("\r")
            else:
                chan.send(ch)

    def raw_mode():
        return None

    def restore(_):
        pass
else:
    import select, termios, tty

    def pump_keys(chan):
        while not chan.closed:
            r, _, _ = select.select([sys.stdin], [], [], 0.1)
            if r:
                data = os.read(sys.stdin.fileno(), 1024)
                if not data:
                    return
                chan.send(data)

    def raw_mode():
        if not sys.stdin.isatty():
            return None
        saved = termios.tcgetattr(0)
        tty.setraw(0)
        return saved

    def restore(saved):
        if saved:
            termios.tcsetattr(0, termios.TCSADRAIN, saved)


def main():
    ap = argparse.ArgumentParser(description="Run vsx_util on the SMS with auto-login.")
    ap.add_argument("command", nargs=argparse.REMAINDER, help="vsx_util command and args")
    ap.add_argument("--host", default="10.1.1.101")
    ap.add_argument("--user", default="admin", help="SSH user (Gaia)")
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--plain", action="store_true", help="strip colours and terminal codes from the output (default when output is not a console)")
    ap.add_argument("--cpuser", default="cpadmin", help="management admin")
    a = ap.parse_args()
    if not a.command:
        ap.error("give a vsx_util command, e.g.  vsx.py show_interfaces")

    cp_pw = secret("CP_PW", f"{a.cpuser} password: ")
    sic_key = load("SIC_KEY") or cp_pw
    answers = [
        (b"localhost", "\r"),                       # server IP -> localhost
        (b"Administrator Name:", a.cpuser + "\r"),
        (b"Administrator Password:", cp_pw + "\r"),
    ]
    # answered every time they appear (e.g. vsx_util reconfigure)
    always = [
        (b"Enter Activation Key:", sic_key + "\r"),
        (b"Retype Activation Key:", sic_key + "\r"),
    ]

    client = connect(a.host, a.user, a.port)
    cols, rows = shutil.get_terminal_size()
    chan = client.get_transport().open_session()
    chan.get_pty(term="xterm", width=cols, height=rows)
    # login shell so Check Point's environment (PATH, $FWDIR...) is loaded
    cmd = shlex.join(["vsx_util", *a.command])
    # echo the command after a Gaia-style prompt, as if typed by hand
    show = 'printf "[Expert@%s:0]# %s\\n" "$(hostname)" ' + shlex.quote(cmd)
    chan.exec_command("bash -lc " + shlex.quote(show + "; " + cmd))

    saved = raw_mode()
    threading.Thread(target=pump_keys, args=(chan,), daemon=True).start()
    out = sys.stdout.buffer
    clean = Cleaner() if (a.plain or not sys.stdout.isatty()) else None
    buf = b""
    try:
        while True:
            try:
                data = chan.recv(4096)
            except socket.timeout:
                continue
            except KeyboardInterrupt:          # Ctrl+C -> pass it to vsx_util
                chan.send("\x03")
                continue
            if not data:
                break
            out.write(clean(data) if clean else data)
            out.flush()
            buf = (buf + data)[-512:]
            if answers and answers[0][0] in buf:
                chan.send(answers.pop(0)[1])
                buf = b""
            else:
                for prompt, reply in always:
                    if prompt in buf:
                        chan.send(reply)
                        buf = b""
                        break
    finally:
        restore(saved)
        status = chan.recv_exit_status() if chan.exit_status_ready() else 0
        client.close()
    sys.exit(status)


if __name__ == "__main__":
    main()
