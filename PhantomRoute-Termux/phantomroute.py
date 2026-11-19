#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PhantomRoute — Termux Edition v1.0
Tor identity rotation for Android/Termux (no root required).

Differences from Kali edition:
  • No systemd — runs tor as a direct child process
  • No iptables — relies on torsocks for traffic routing
  • No MAC change (Android restriction)
  • Uses $PREFIX paths for torrc
"""

import os
import sys
import time
import json
import random
import secrets
import signal
import shutil
import socket
import argparse
import subprocess
import urllib.request
from pathlib import Path
from datetime import datetime

APP        = "PhantomRoute"
VERSION    = "1.1"
PREFIX     = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
STATE_DIR  = Path.home() / ".config" / "phantomroute"
STATE_FILE = STATE_DIR / "state.json"
REPORT     = Path.home() / "phantomroute_report.txt"

TORRC      = PREFIX / "etc" / "tor" / "torrc"
TOR_BIN    = PREFIX / "bin" / "tor"
SOCKS_PORT = 9050
CTRL_PORT  = 9051
CHANGE_INTERVAL = 90
CHECK_INTERVAL  = 20
CTRL_PASS       = secrets.token_hex(16)   # in memory only

NEARBY = {
    "SA": ["AE","QA","TR","EG","JO","OM"], "AE": ["SA","QA","OM"],
    "EG": ["TR","IT","GR","SA"],           "MA": ["ES","FR","PT","DZ"],
    "DZ": ["FR","IT","ES","TN"],           "TN": ["IT","FR","DZ"],
    "IQ": ["TR","SA","JO"],                "JO": ["SA","TR","EG"],
    "US": ["CA","MX","GB","DE"],           "CA": ["US","GB"],
    "FR": ["BE","DE","CH","IT"],           "DE": ["NL","BE","CH","FR"],
    "GB": ["IE","FR","NL","BE"],           "NL": ["BE","DE","GB","FR"],
}
DEFAULTS = ["US","GB","DE","FR","NL","SE","CH","CA"]

R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'
B='\033[0;34m'; M='\033[0;35m'; C='\033[0;36m'
W='\033[1;37m'; N='\033[0m'
def col(c, t): return f"{c}{t}{N}"

# ─── State ─────────────────────────────────────────────────────
class State:
    def __init__(self): self.d = {}
    def load(self):
        if STATE_FILE.exists():
            try: self.d = json.loads(STATE_FILE.read_text())
            except Exception: self.d = {}
        return self.d
    def save(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(self.d, indent=2))
    def get(self, k, d=None): return self.d.get(k, d)
    def set(self, k, v): self.d[k] = v; self.save()
    def clear(self):
        self.d = {}
        try: STATE_FILE.unlink()
        except FileNotFoundError: pass

state = State()

# ─── Helpers ───────────────────────────────────────────────────
def run(cmd, timeout=15):
    try:
        return subprocess.run(cmd if isinstance(cmd, list) else cmd.split(),
                              capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None

def out(cmd, timeout=15):
    r = run(cmd, timeout)
    return r.stdout.strip() if r and r.returncode == 0 else ""

def check_deps():
    missing = [x for x in ("tor","curl") if not shutil.which(x)]
    if missing:
        print(col(R, f"✗ Missing: {', '.join(missing)}"))
        print(col(C, f"  Run: pkg install {' '.join(missing)}"))
        sys.exit(1)

def get_real_country():
    for url in ("https://ipapi.co/country/","https://ifconfig.co/country-iso"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                c = r.read().decode().strip()[:2].upper()
                if c.isalpha(): return c
        except Exception: pass
    return "US"

# ─── Tor process management ────────────────────────────────────
tor_proc = None

def start_tor():
    global tor_proc
    if tor_proc and tor_proc.poll() is None:
        return True
    print(col(Y, "▸ Starting tor..."))
    try:
        tor_proc = subprocess.Popen(
            [str(TOR_BIN), "-f", str(TORRC)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        time.sleep(2)
        return tor_proc.poll() is None
    except Exception as e:
        print(col(R, f"✗ Tor start failed: {e}"))
        return False

def stop_tor():
    global tor_proc
    if tor_proc and tor_proc.poll() is None:
        tor_proc.terminate()
        try: tor_proc.wait(timeout=5)
        except subprocess.TimeoutExpired: tor_proc.kill()
        print(col(G, "  ✓ Tor stopped"))
    tor_proc = None

def tor_control(commands, timeout=5):
    """Send commands to the (password protected) control port; True if all replies are 250."""
    try:
        sk = socket.create_connection(("127.0.0.1", CTRL_PORT), timeout=timeout)
        sk.settimeout(timeout)
        payload = f'AUTHENTICATE "{CTRL_PASS}"\r\n' + \
                  "".join(c + "\r\n" for c in commands) + "QUIT\r\n"
        sk.sendall(payload.encode())
        data = b""
        while True:
            chunk = sk.recv(4096)
            if not chunk: break
            data += chunk
        sk.close()
        lines = [l for l in data.decode(errors="replace").splitlines() if l.strip()]
        return len(lines) >= len(commands) + 1 and all(l.startswith("250") for l in lines)
    except Exception:
        return False

def tor_newnym():
    return tor_control(["SIGNAL NEWNYM"])

def hash_control_password():
    tor = str(TOR_BIN) if TOR_BIN.exists() else (shutil.which("tor") or "tor")
    o = out([tor, "--hash-password", CTRL_PASS])
    lines = [l.strip() for l in o.splitlines() if l.strip().startswith("16:")]
    return lines[-1] if lines else None

def get_tor_ip():
    r = run(["curl","-s","--max-time","20",
             "--socks5-hostname",f"127.0.0.1:{SOCKS_PORT}",
             "https://check.torproject.org/api/ip"], timeout=25)
    if r and r.returncode == 0 and r.stdout.strip():
        try:
            d = json.loads(r.stdout)
            if d.get("IsTor"): return d.get("IP")
        except Exception: pass
    return None

def wait_for_tor(timeout=120):
    print(col(Y, "▸ Waiting for Tor to bootstrap (up to %ds)..." % timeout))
    t0 = time.time()
    while time.time() - t0 < timeout:
        ip = get_tor_ip()
        if ip:
            print(col(G, f"  ✓ Tor is up — exit IP {ip}"))
            return True
        time.sleep(3)
    print(col(R, "  ✗ Tor did not come up in time (will keep retrying)"))
    return False

# ─── Configure tor ─────────────────────────────────────────────
def configure_tor(country):
    hashed = hash_control_password()
    if not hashed:
        print(col(R, "✗ Could not hash the control password"))
        return False
    TORRC.parent.mkdir(parents=True, exist_ok=True)
    content = f"""SocksPort 127.0.0.1:{SOCKS_PORT}
ControlPort 127.0.0.1:{CTRL_PORT}
HashedControlPassword {hashed}
ExitNodes {{{country}}}
StrictNodes 0
AvoidDiskWrites 1
SafeLogging 1
"""
    # remember the ORIGINAL torrc once (None = file did not exist)
    if "torrc_saved" not in state.d:
        try: state.set("torrc_content", TORRC.read_text())
        except FileNotFoundError: state.set("torrc_content", None)
        state.set("torrc_saved", True)
    TORRC.write_text(content)
    stop_tor()
    return start_tor()

def set_exit_country(country):
    """Switch exit country on the live Tor — no restart, circuits are not dropped."""
    ok = tor_control([f'SETCONF ExitNodes="{{{country.lower()}}}"', "SIGNAL NEWNYM"])
    if not ok:
        ok = configure_tor(country)
    return ok

def rotate(real, first=False):
    target = random.choice(NEARBY.get(real, DEFAULTS))
    print(col(M, f"⟳ Target: {target}"))
    if first: configure_tor(target)
    else:     set_exit_country(target)
    return target

# ─── Report ────────────────────────────────────────────────────
stats = {"checks":0,"ok":0,"fail":0,"rotations":0,"history":{}}

def write_report():
    if not stats["checks"] and not stats["rotations"]: return
    try:
        lines = [
            "═"*50,
            f"  {APP} v{VERSION} — Termux Report",
            "═"*50,
            f"Started:  {state.get('session')}",
            f"Finished: {datetime.now().isoformat()}",
            f"Checks:   {stats['checks']}  (ok={stats['ok']}, fail={stats['fail']})",
            f"Rotations: {stats['rotations']}",
            "",
            "Countries:",
        ]
        for c, n in stats["history"].items():
            lines.append(f"  • {c}: {n}×")
        REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(col(G, f"✓ Report → {REPORT}"))
    except Exception as e:
        print(col(R, f"Report error: {e}"))

# ─── Cleanup ───────────────────────────────────────────────────
def safe_cleanup(verbose=True):
    """Idempotent. Never skipped by an old flag, so crash-recovery really runs."""
    if verbose: print(col(Y, "\n▸ Restoring..."))
    stop_tor()
    try:
        if state.get("torrc_saved"):
            orig = state.get("torrc_content")
            if orig is not None:
                TORRC.write_text(orig)
            elif TORRC.exists():
                TORRC.unlink()
    except Exception: pass
    state.set("cleanup_pending", False)
    if verbose: print(col(G, "✓ Cleanup complete."))

_exiting = False
def on_signal(sig, frame):
    global _exiting
    if _exiting: return
    _exiting = True
    safe_cleanup()
    write_report()
    sys.exit(0)

signal.signal(signal.SIGINT, on_signal)
signal.signal(signal.SIGTERM, on_signal)
signal.signal(signal.SIGHUP, on_signal)

# ─── Banner ────────────────────────────────────────────────────
def banner():
    os.system("clear")
    print(col(C, "╔══════════════════════════════════════════╗"))
    print(col(C, "║                                          ║"))
    print(col(C, "║      ██████╗ ██╗  ██╗ █████╗ ███╗   ██╗ ║"))
    print(col(C, "║      ██╔══██╗██║  ██║██╔══██╗████╗  ██║ ║"))
    print(col(C, "║      ██████╔╝███████║███████║██╔██╗ ██║ ║"))
    print(col(C, "║      ██╔═══╝ ██╔══██║██╔══██║██║╚██╗██║ ║"))
    print(col(C, "║      ██║     ██║  ██║██║  ██║██║ ╚████║ ║"))
    print(col(C, "║      ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝ ║"))
    print(col(C, "║                                          ║"))
    print(col(C, f"║      R O U T E   v{VERSION}  (Termux)      ║"))
    print(col(C, "╚══════════════════════════════════════════╝"))
    print()

# ─── Main ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(prog=APP)
    parser.add_argument("--panic", action="store_true", help="Recover crashed session")
    parser.add_argument("--status", action="store_true", help="Show state")
    parser.add_argument("--interval", type=int, default=CHANGE_INTERVAL,
                        help="Seconds between rotations (min 10)")
    args = parser.parse_args()
    args.interval = max(10, args.interval)

    if args.panic:
        if state.load() and state.get("cleanup_pending"):
            print(col(Y, "Recovering..."))
            run(["pkill", "-f", f"{TOR_BIN} -f {TORRC}"])   # leftover tor from the crashed session
            safe_cleanup()
        print(col(G, "Done."))
        return

    if args.status:
        if state.load(): print(json.dumps(state.d, indent=2))
        else: print("No state.")
        return

    check_deps()

    if state.load() and state.get("cleanup_pending"):
        print(col(Y, "⚠ Previous crash detected — recovering..."))
        run(["pkill", "-f", f"{TOR_BIN} -f {TORRC}"])
        safe_cleanup(verbose=False)

    banner()

    state.clear()
    state.set("session", datetime.now().isoformat())
    state.set("cleanup_pending", True)
    state.set("platform", "termux")

    real = get_real_country()
    print(col(G, f"✓ Real country: {real}"))

    current = rotate(real, first=True)
    if not (tor_proc and tor_proc.poll() is None):
        print(col(R, "✗ Cannot start Tor"))
        safe_cleanup()
        sys.exit(1)
    stats["rotations"] = 1
    stats["history"][current] = 1
    wait_for_tor()
    last = time.time()

    print(col(G, "\n✅ PhantomRoute active."))
    print(col(C, f"  Route apps via SOCKS5 127.0.0.1:{SOCKS_PORT} (or torsocks).\n"))
    time.sleep(2)

    while True:
        os.system("clear")
        banner()
        stats["checks"] += 1
        ip = get_tor_ip()
        if ip:
            stats["ok"] += 1
            print(col(G, f"  ✓ Exit IP: {ip}"))
            print(col(C, f"  Target: {current}  |  Uptime: {int(time.time()-last)}s"))
        else:
            stats["fail"] += 1
            print(col(R, "  ✗ Tor unreachable — restarting..."))
            if not (tor_proc and tor_proc.poll() is None):
                start_tor()
            else:
                tor_newnym()

        if time.time() - last >= args.interval:
            current = rotate(real)
            stats["rotations"] += 1
            stats["history"][current] = stats["history"].get(current,0)+1
            last = time.time()

        nxt = max(0, int(args.interval - (time.time()-last)))
        print(col(W, f"\n  ⏱  Next rotation in {nxt}s  |  Ctrl+C to stop"))
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        on_signal(None, None)
    except Exception as e:
        print(col(R, f"\n✗ Error: {e}"))
        safe_cleanup()
        write_report()
        sys.exit(1)
