#!/usr/bin/env python3
"""
ubrun.py - log into an Ubuntu (or other Linux) server over SSH, run a
command, and answer sudo password prompts along the way.

    py ubrun.py 192.168.13.101                       just log in and hand over
    py ubrun.py 192.168.13.101 sudo apt update       sudo password typed for you
    py ubrun.py 192.168.13.101 -c "ps aux | grep nginx; uptime"   sent as typed
    py ubrun.py 192.168.13.101 -f setup.sh a b       upload setup.sh, run with bash

Logs in as cpadmin with the saved cpadmin password (SSH key first, if you
have one). sudo's password prompt is answered with the same password -
both classic sudo ("[sudo] password for cpadmin:") and sudo-rs, the
default from Ubuntu 25.10 ("[sudo: authenticate] Password:").
When the command finishes and the shell prompt comes back, the session
closes. With -f the script is uploaded through the session, run with bash
from a temp file, then deleted.
"""
import argparse, base64, re, shlex, shutil, socket, sys, threading

from labcreds import load, secret
from vsx import connect, pump_keys, raw_mode, restore

# Colour codes, window titles and bracketed-paste markers around the prompt
ANSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
# user@host:~/dir$  or  root@host:/# (as Ubuntu's default prompt)
PROMPT = re.compile(rb"[\w.-]+@[\w.-]+:[^\r\n]*[$#] $")
# "[sudo] password for cpadmin: "  or  "[sudo: authenticate] Password: "
SUDO = re.compile(rb"\[sudo[^\]\r\n]*\][^\r\n]*: ?$")


def main():
    ap = argparse.ArgumentParser(description="Run a command on a Linux server with sudo answered.")
    ap.add_argument("host")
    ap.add_argument("command", nargs=argparse.REMAINDER,
                    help="command to run (omit to just log in; with -f: arguments for the script)")
    ap.add_argument("-c", dest="raw", help="command line sent exactly as written (; | && allowed)")
    ap.add_argument("-f", "--file", help="local bash script to upload and run")
    ap.add_argument("--user", default="cpadmin", help="SSH user (default cpadmin)")
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--pw", default="CP_PW",
                    help="saved password to use (default CP_PW, the cpadmin password)")
    a = ap.parse_args()
    # Options typed after the host land in the command; take them back.
    opts = {"-c": ("raw", str), "-f": ("file", str), "--file": ("file", str),
            "--user": ("user", str), "--port": ("port", int), "--pw": ("pw", str)}
    while len(a.command) >= 2 and a.command[0] in opts:
        name, conv = opts[a.command.pop(0)]
        setattr(a, name, conv(a.command.pop(0)))

    cmd = a.raw or (shlex.join(a.command) if a.command else "")
    upload = None
    if a.file:
        with open(a.file, "rb") as f:
            body = f.read().replace(b"\r\n", b"\n")      # Windows line endings break bash
        upload = base64.encodebytes(body).decode()
        cmd = 'bash "$f"' + (" " + shlex.join(a.command) if a.command else "") + '; rm -f "$f"'
    cache = {}

    def password():
        if "pw" not in cache:
            cache["pw"] = load(a.pw) or secret(a.pw, f"{a.user}@{a.host} password: ")
        return cache["pw"]

    client = connect(a.host, a.user, a.port, pw_name=a.pw)
    cols, rows = shutil.get_terminal_size()
    chan = client.invoke_shell(term="xterm", width=cols, height=rows)

    saved = raw_mode()
    threading.Thread(target=pump_keys, args=(chan,), daemon=True).start()
    out = sys.stdout.buffer
    state, tail, sudo_tries = "login", b"", 0
    try:
        while True:
            try:
                data = chan.recv(4096)
            except socket.timeout:
                continue
            except KeyboardInterrupt:          # Ctrl+C -> remote side
                chan.send("\x03")
                continue
            if not data:
                break
            out.write(data)
            out.flush()
            tail = (tail + data)[-2048:]
            plain = ANSI.sub(b"", tail)

            if state == "upload":
                if b"UBRUN_READY" in plain:      # base64 -d is now reading
                    chan.sendall(upload + "\x04")
                    state, tail = "uploaded", b""
                continue

            # sudo password, at most twice in a row (a wrong one would loop)
            if SUDO.search(plain) and sudo_tries < 2:
                chan.send(password() + "\r")
                sudo_tries += 1
                tail = b""
                continue

            if not PROMPT.search(plain):
                continue
            tail, sudo_tries = b"", 0
            if state == "login":                 # first prompt
                if upload:
                    chan.send('f=$(mktemp /tmp/ubrun.XXXXXX); stty -echo; '
                              'printf "UBRUN%sREADY\\n" _; base64 -d > "$f"; stty echo\r')
                    state = "upload"
                elif cmd:
                    chan.send(cmd + "\r")
                    state = "cmd"
                else:
                    state = "interactive"
            elif state == "uploaded":            # file is on the box: run it
                chan.send(cmd + "\r")
                state = "cmd"
            elif state == "cmd":                 # prompt back: command finished
                break
    finally:
        restore(saved)
        client.close()
    print()


if __name__ == "__main__":
    main()
