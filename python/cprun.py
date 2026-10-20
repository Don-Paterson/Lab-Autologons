#!/usr/bin/env python3
"""
cprun.py - log into a Gaia box over SSH, get to Expert mode, run a command,
and answer the password / Activation Key prompts along the way.

    py cprun.py 10.1.1.2 cpconfig        reset SIC: pick the menu option, keys are typed
    py cprun.py 10.1.1.101 vsx_util vsls  (vsx_util login prompts answered too)
    py cprun.py 10.1.1.2                 just log in (to Expert) and hand over
    py cprun.py 10.1.1.2 -f check.sh a b upload check.sh, run it with bash (args a b)
    py cprun.py 10.1.1.2 -c "fw stat; cphaprob state | head"   one string, sent as typed

With -f the script is sent through the SSH session (no SCP needed, works when
admin's shell is clish), saved to a temp file, run with bash in Expert mode,
then deleted - so ; | && loops and so on all work inside it.

Answered for you:
    Enter expert password:            Gaia admin password (EXPERT_PW if saved)
    ... Activation Key:               saved SIC key (Enter / Enter new / Retype / Confirm)
    vsx_util login prompts            localhost, cpadmin, cpadmin password
Everything else (menus, y/n) is yours. When the command finishes and the
shell prompt comes back, the session closes - just like vsx.py.
"""
import argparse, base64, re, shlex, shutil, socket, sys, threading, time

from labcreds import load, secret
from termclean import SEQ, Cleaner
from vsx import connect, pump_keys, raw_mode, restore

# Gaia prompts, matched on the output with terminal codes removed:
#   expert  "[Expert@A-GW-01:0]# "
#   clish   "A-GW-01> "   and VSNext / ElasticXL "[Global] A-Elastic-Cluster-s01-01:0> "
EXPERT = re.compile(rb"\[Expert@[^\]\r\n]+\]# ?$")
CLISH = re.compile(rb"(?:^|[\r\n])(?:\[[^\]\r\n]+\] )?[\w.-]+(?::\d+)?> ?$")


def main():
    ap = argparse.ArgumentParser(description="Run a command on a Gaia box with auto-answered prompts.")
    ap.add_argument("host")
    ap.add_argument("-f", "--file", help="local bash script to upload and run")
    ap.add_argument("-c", dest="raw", help="command line sent exactly as written (; | && allowed)")
    ap.add_argument("command", nargs=argparse.REMAINDER,
                    help="command to run in Expert mode (with -f: arguments for the script)")
    ap.add_argument("--user", default="admin", help="SSH user (Gaia)")
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--plain", action="store_true", help="strip colours and terminal codes from the output (default when output is not a console)")
    ap.add_argument("--cpuser", default="cpadmin", help="management admin (vsx_util)")
    a = ap.parse_args()
    # Options typed after the host ("cprun 10.1.1.2 -f x.sh") land in the
    # command; take them back while they lead it.
    opts = {"-f": ("file", str), "--file": ("file", str), "-c": ("raw", str), "--port": ("port", int),
            "--user": ("user", str), "--cpuser": ("cpuser", str)}
    while a.command and (a.command[0] == "--plain" or
                         (len(a.command) >= 2 and a.command[0] in opts)):
        if a.command[0] == "--plain":
            a.command.pop(0)
            a.plain = True
            continue
        name, conv = opts[a.command.pop(0)]
        setattr(a, name, conv(a.command.pop(0)))

    cmd = shlex.join(a.command) if a.command else ""
    if a.raw:
        cmd = a.raw
    upload = None
    if a.file:
        with open(a.file, "rb") as f:
            body = f.read().replace(b"\r\n", b"\n")      # Windows line endings break bash
        upload = base64.encodebytes(body).decode()          # 76-char lines
        # $f is set on the box by the upload line below
        cmd = 'bash "$f"' + (" " + shlex.join(a.command) if a.command else "") + '; rm -f "$f"'
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
    # any prompt ending in "Activation Key:" - cpconfig's "Enter/Retype ...",
    # reset_gw's "Enter new ...", etc. Only at the end of the output, so a
    # status line that merely mentions the key is not answered.
    always = [(re.compile(rb"Activation Key: ?$", re.I), lambda: sic_key() + "\r")]

    client = connect(a.host, a.user, a.port)
    cols, rows = shutil.get_terminal_size()
    chan = client.invoke_shell(term="xterm", width=cols, height=rows)

    saved = raw_mode()
    threading.Thread(target=pump_keys, args=(chan,), daemon=True).start()
    out = sys.stdout.buffer
    clean = Cleaner() if (a.plain or not sys.stdout.isatty()) else None
    state, tail, prompt, sent_expert, failed = "login", b"", None, False, False
    # The expert password is typed only once the prompt has been quiet for a
    # moment: VSNext discards input that arrives before it starts reading, so
    # an instant answer is lost. It is typed again only if the gateway shows
    # the prompt again (after a wrong password) - never on a timer, because
    # opening Expert mode can take several seconds.
    pw_wait, pw_tries, last_rx = False, 0, time.monotonic()
    chan.settimeout(0.2)
    try:
        while True:
            try:
                data = chan.recv(4096)
            except socket.timeout:
                idle = time.monotonic() - last_rx
                if pw_wait and idle > 0.5 and pw_tries < 2:
                    chan.send(expert_pw() + "\r")
                    pw_tries += 1
                    pw_wait, tail = False, b""   # forget this prompt: answered
                continue
            except KeyboardInterrupt:          # Ctrl+C -> remote side
                chan.send("\x03")
                continue
            if not data:
                break
            out.write(clean(data) if clean else data)
            out.flush()
            last_rx = time.monotonic()
            tail = (tail + data)[-2048:]

            if state == "login":
                plain = SEQ.sub(b"", tail)
                if plain.rstrip().endswith(b"Enter expert password:"):
                    pw_wait = True                   # answered from the timeout branch
                    continue
                pw_wait = False                      # something else came: the prompt has gone
                m = EXPERT.search(plain)
                if not m and CLISH.search(plain):       # clish -> expert
                    if sent_expert:                      # back at clish: refused
                        sys.stderr.write("\ncprun: 'expert' did not open Expert mode - wrong expert "
                                         "password, or none set (clish: set expert-password)\n")
                        failed = True
                        break
                    chan.send("expert\r")
                    sent_expert, tail = True, b""
                    continue
                if not m:
                    continue
                prompt = m.group(0).rstrip()             # at the Expert prompt
                tail = b""
                if upload:
                    # temp file, echo off, marker, then base64 -d reads what we send
                    chan.send('f=$(mktemp /tmp/cprun.XXXXXX); stty -echo; '
                              'printf "CPRUN%sREADY\\n" _; base64 -d > "$f"; stty echo\r')
                    state = "upload"
                    continue
                if cmd:
                    chan.send(cmd + "\r")
                    state = "cmd"
                else:
                    state = "interactive"
                continue

            if state == "upload":
                if b"CPRUN_READY" in tail:               # base64 -d is now reading
                    chan.sendall(upload + "\x04")          # data, then Ctrl+D (end of file)
                    state, tail = "uploaded", b""
                continue
            if state == "uploaded":                      # prompt back: file is on the box
                if SEQ.sub(b"", tail).rstrip().endswith(prompt):
                    chan.send(cmd + "\r")
                    state, tail = "cmd", b""
                continue

            if once and once[0][0] in tail:
                chan.send(once.pop(0)[1]())
                tail = b""
                continue
            for text, reply in always:
                if text.search(SEQ.sub(b"", tail)):
                    chan.send(reply())
                    tail = b""
                    break
            else:
                # command finished: its shell prompt is back
                if state == "cmd" and SEQ.sub(b"", tail).rstrip().endswith(prompt):
                    break
    finally:
        restore(saved)
        client.close()
    print()
    if failed:
        sys.exit(4)


if __name__ == "__main__":
    main()
