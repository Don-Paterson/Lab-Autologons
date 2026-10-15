#!/usr/bin/env python3
"""
vsx-prov-tool.py - run vsx_provisioning_tool on A-SMS over SSH.

Uses the same SSH login and saved cpadmin password as vsx.py
(keep vsx.py in the same folder).

    py vsx-prov-tool.py -f a-app-gw.txt
    py vsx-prov-tool.py "add vd name A-APP-GW vsx A-VSX-Cluster main_ip 203.0.113.13, add route ..."

Command file: one transaction per line; blank lines and # comments are
ignored. Lines are joined with ", " into a single -o (one transaction set).
The password is sent over the SSH session's input, not on the SSH command line.
"""
import argparse, shlex, sys

from labcreds import secret
from vsx import connect


def load_commands(a):
    if a.file:
        with open(a.file, encoding="utf-8") as f:
            lines = [l.strip().rstrip(",") for l in f]
        return ", ".join(l for l in lines if l and not l.startswith("#"))
    return " ".join(a.commands)


def main():
    ap = argparse.ArgumentParser(description="Run vsx_provisioning_tool on the SMS.")
    ap.add_argument("commands", nargs="*", help="transactions, comma separated")
    ap.add_argument("-f", "--file", help="file with one transaction per line")
    ap.add_argument("-y", "--yes", action="store_true", help="don't ask before running")
    ap.add_argument("--host", default="10.1.1.101")
    ap.add_argument("--user", default="admin", help="SSH user (Gaia)")
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--cpuser", default="cpadmin", help="management admin")
    a = ap.parse_args()

    ops = load_commands(a)
    if not ops:
        ap.error("give transactions, or -f FILE")

    shown = (f"vsx_provisioning_tool -s localhost -u {a.cpuser} -p '********' -o {ops}")
    if not a.yes:
        print(shown)
        if input("Run this on %s? [y/N] " % a.host).lower() != "y":
            sys.exit("Cancelled.")

    cp_pw = secret("CP_PW", f"{a.cpuser} password: ")
    client = connect(a.host, a.user, a.port)
    chan = client.get_transport().open_session()
    chan.set_combine_stderr(True)

    # Same as doing it by hand: read the password, then pass it with -p.
    # ops is split by the remote shell exactly as when typed (no quoting).
    remote = (
        'IFS= read -r PW; '
        'printf "[Expert@%s:0]# %s\\n" "$(hostname)" ' + shlex.quote(shown) + '; '
        f'vsx_provisioning_tool -s localhost -u {shlex.quote(a.cpuser)} -p "$PW" -o {ops}'
    )
    chan.exec_command("bash -lc " + shlex.quote(remote))
    chan.sendall(cp_pw + "\n")
    chan.shutdown_write()

    out = sys.stdout.buffer
    while True:
        data = chan.recv(4096)
        if not data:
            break
        out.write(data)
        out.flush()
    status = chan.recv_exit_status()
    client.close()
    if status:
        print(f"\nvsx_provisioning_tool exited with status {status}", file=sys.stderr)
    sys.exit(status)


if __name__ == "__main__":
    main()
