#!/usr/bin/env python3
"""
cprun.py - log into a Gaia box over SSH, get to Expert mode, run a command,
and answer the password / Activation Key prompts along the way.

    py cprun.py 10.1.1.2 cpconfig        reset SIC: pick the menu option, keys are typed
    py cprun.py 10.1.1.101 vsx_util vsls  (vsx_util login prompts answered too)
    py cprun.py 10.1.1.2                 just log in (to Expert) and hand over

Answered for you:
    Enter expert password:            Gaia admin password (EXPERT_PW if saved)
    Enter / Retype Activation Key:    saved SIC key
    vsx_util login prompts            localhost, cpadmin, cpadmin password
Everything else (menus, y/n) is yours. When the command finishes and the
shell prompt comes back, the session closes - just like vsx.py.
"""
import argparse, re, shlex, shutil, socket, sys, threading

from labcreds import load, secret
from vsx import connect, pump_keys, raw_mode, restore

# Gaia prompts: clish "A-GW-01> " and expert "[Expert@A-GW-01:0]# "
PROMPT = re.compile(rb"(\[Expert@[^\]\r\n]+\]# |[\w.-]+> )$")


def main():
    ap = argparse.ArgumentParser(description="Run a command on a Gaia box with auto-answered prompts.")
    ap.add_argument("host")
    ap.add_argument("command", nargs=argparse.REMAINDER, help="command to run in Expert mode")
    ap.add_argument("--user", default="admin", help="SSH user (Gaia)")
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--cpuser", default="cpadmin", help="management admin (vsx_util)")
    a = ap.parse_args()

    cmd = shlex.join(a.command) if a.command else ""
    cache = {}

    def sic_key():
        if "sic" not in cache:
            cache["sic"] = load("SIC_KEY") or secret("CP_PW", f"{a.cpuser} password: ")
        return cache["sic"]

    def cp_pw():
        if "cp" not in cache:
            cache["cp"] = secret("CP_PW", f"{a.cpuser} password: ")
        return cache["cp"]

    def expert_pw():
        return load("EXPERT_PW") or secret("SMS_SSH_PW", "Gaia expert password: ")

    # prompts answered once, in order (only for vsx_util)
    once = []
    if a.command and a.command[0] == "vsx_util":
        once = [(b"localhost", lambda: "\r"),
                (b"Administrator Name:", lambda: a.cpuser + "\r"),
                (b"Administrator Password:", lambda: cp_pw() + "\r")]
    always = [(b"Enter Activation Key:", lambda: sic_key() + "\r"),
              (b"Retype Activation Key:", lambda: sic_key() + "\r")]

    client = connect(a.host, a.user, a.port)
    cols, rows = shutil.get_terminal_size()
    chan = client.invoke_shell(term="xterm", width=cols, height=rows)

    saved = raw_mode()
    threading.Thread(target=pump_keys, args=(chan,), daemon=True).start()
    out = sys.stdout.buffer
    state, tail, prompt, sent_expert = "login", b"", None, False
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

            if state == "login":
                if b"Enter expert password:" in tail:
                    chan.send(expert_pw() + "\r")
                    tail = b""
                    continue
                m = PROMPT.search(tail)
                if not m:
                    continue
                if m.group(1).endswith(b"> "):          # clish -> expert
                    if sent_expert:
                        continue
                    chan.send("expert\r")
                    sent_expert, tail = True, b""
                    continue
                prompt = m.group(1)                      # at the Expert prompt
                tail = b""
                if cmd:
                    chan.send(cmd + "\r")
                    state = "cmd"
                else:
                    state = "interactive"
                continue

            if once and once[0][0] in tail:
                chan.send(once.pop(0)[1]())
                tail = b""
                continue
            for text, reply in always:
                if text in tail:
                    chan.send(reply())
                    tail = b""
                    break
            else:
                # command finished: its shell prompt is back
                if state == "cmd" and tail.endswith(prompt):
                    break
    finally:
        restore(saved)
        client.close()
    print()


if __name__ == "__main__":
    main()
