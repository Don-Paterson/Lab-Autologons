#!/usr/bin/env python3
"""
ubrun.py - log into an Ubuntu (or other Linux) server over SSH, run a
command, and answer sudo password prompts along the way.

    py ubrun.py 192.168.13.101                     just log in and hand over
    py ubrun.py 192.168.13.101 sudo apt update     sudo password typed for you
    py ubrun.py 192.168.13.101 df -h

Logs in as cpadmin with the saved cpadmin password (SSH key first, if you
have one). "[sudo] password for ...:" is answered with the same password.
When a command finishes and the shell prompt comes back, the session closes.
"""
import argparse, re, shlex, shutil, socket, sys, threading

from labcreds import load, secret
from vsx import connect, pump_keys, raw_mode, restore

# Colour codes, window titles and bracketed-paste markers around the prompt
ANSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
# user@host:~/dir$  or  root@host:/# (as Ubuntu's default prompt)
PROMPT = re.compile(rb"[\w.-]+@[\w.-]+:[^\r\n]*[$#] $")
SUDO = re.compile(rb"\[sudo\] password for [\w.-]+: ?$")


def main():
    ap = argparse.ArgumentParser(description="Run a command on a Linux server with sudo answered.")
    ap.add_argument("host")
    ap.add_argument("command", nargs=argparse.REMAINDER, help="command to run (omit to just log in)")
    ap.add_argument("--user", default="cpadmin", help="SSH user (default cpadmin)")
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--pw", default="CP_PW",
                    help="saved password to use (default CP_PW, the cpadmin password)")
    a = ap.parse_args()

    cmd = shlex.join(a.command) if a.command else ""
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

            # sudo password, at most twice in a row (a wrong one would loop)
            if SUDO.search(plain) and sudo_tries < 2:
                chan.send(password() + "\r")
                sudo_tries += 1
                tail = b""
                continue

            if not PROMPT.search(plain):
                continue
            tail, sudo_tries = b"", 0
            if state == "login":                 # first prompt: run the command
                if cmd:
                    chan.send(cmd + "\r")
                    state = "cmd"
                else:
                    state = "interactive"
            elif state == "cmd":                 # prompt back: command finished
                break
    finally:
        restore(saved)
        client.close()
    print()


if __name__ == "__main__":
    main()
