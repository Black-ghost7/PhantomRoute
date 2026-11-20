#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PhantomRoute — Kali Linux Edition v1.0
Safe identity rotation through Tor with guaranteed state restoration.

Key safety guarantees:
  • Never flushes global iptables — uses private chains PHANTOMR_OUT / PHANTOMR_OUT6
  • Kill switch lets ONLY loopback, DHCP and the Tor daemon's own traffic out
  • Always restores DNS, systemd-resolved, Tor, MAC, and Hostname
  • Persists crash state (/var/lib/phantomroute) so `--panic` works after a reboot
  • Tor control port is protected by a random per-session password
"""

import os
import sys
import time
import json
import signal
import shutil
import socket
import argparse
import subprocess
import pwd
import secrets
import random
import urllib.request
from pathlib import Path
from datetime import datetime

# ─── Constants ─────────────────────────────────────────────────
APP        = "PhantomRoute"
VERSION    = "1.2"
EDITION    = "Kali"
FEATURES   = {"mac", "hostname", "killswitch"}
STATE_DIR  = Path("/var/lib/phantomroute")      # fixed path: same under sudo or root
STATE_FILE = STATE_DIR / "state.json"

def user_home():
    u = os.environ.get("SUDO_USER")
    if u and u != "root":
        try: return Path(pwd.getpwnam(u).pw_dir)
        except KeyError: pass
    return Path.home()

REPORT     = user_home() / "phantomroute_report.txt"

CHANGE_INTERVAL = 60
CHECK_INTERVAL  = 15
CTRL_PORT       = 9051
SOCKS_PORT      = 9050
TOR_SERVICE     = "tor@default"
TORRC           = Path("/etc/tor/torrc")
RESOLV          = Path("/etc/resolv.conf")
CHAIN_OUT       = "PHANTOMR_OUT"
CHAIN_OUT6      = "PHANTOMR_OUT6"
TOR_USERS       = ("debian-tor", "tor", "_tor")
CTRL_PASS       = secrets.token_hex(16)         # lives in memory only
RESOLV_TEXT     = "nameserver 127.0.0.1\n"

NEARBY = {
    "SA": ["AE","QA","TR","EG","JO","OM","BH","KW"], "AE": ["SA","QA","OM","BH"],
    "EG": ["TR","IT","GR","SA","JO","LY"],           "MA": ["ES","FR","PT","DZ"],
    "DZ": ["FR","IT","ES","TN"],                     "TN": ["IT","FR","DZ"],
    "LY": ["IT","GR","EG"],                          "IQ": ["TR","SA","JO"],
    "SY": ["TR","JO","LB"],                          "LB": ["TR","GR","CY"],
    "JO": ["SA","TR","EG"],                          "OM": ["AE","SA","YE"],
    "KW": ["SA","IQ","AE"],                          "BH": ["SA","QA"],
    "QA": ["SA","AE"],                               "US": ["CA","MX","GB","DE"],
    "CA": ["US","GB"],                               "MX": ["US","ES"],
    "FR": ["BE","DE","CH","IT","GB","ES","NL"],      "DE": ["NL","BE","CH","FR","AT"],
    "GB": ["IE","FR","NL","BE"],                     "IT": ["FR","CH","GR","ES"],
    "ES": ["FR","PT","IT","MA"],                     "NL": ["BE","DE","GB","FR"],
    "SE": ["NO","FI","DK","DE"],                     "NO": ["SE","FI","DK"],
    "CH": ["DE","FR","IT","AT"],                     "AT": ["DE","CH","IT"],
}
DEFAULTS = ["US","GB","DE","FR","NL","SE","CH","CA","IT","ES"]

# ─── Colours ───────────────────────────────────────────────────
R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'
B='\033[0;34m'; M='\033[0;35m'; C='\033[0;36m'
W='\033[1;37m'; N='\033[0m'

def col(c, t): return f"{c}{t}{N}"

# ─── State manager ─────────────────────────────────────────────
class State:
    def __init__(self): self.d = {}
    def load(self):
        if STATE_FILE.exists():
            try: self.d = json.loads(STATE_FILE.read_text())
            except Exception: self.d = {}
        return self.d
    def save(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(STATE_DIR, 0o700)
        STATE_FILE.write_text(json.dumps(self.d, indent=2))
        os.chmod(STATE_FILE, 0o600)
    def get(self, k, d=None): return self.d.get(k, d)
    def set(self, k, v):
        self.d[k] = v
        self.save()
    def clear(self):
        self.d = {}
        try: STATE_FILE.unlink()
        except FileNotFoundError: pass

state = State()

# ─── Command runner ────────────────────────────────────────────
def run(cmd, timeout=15):
    try:
        return subprocess.run(cmd if isinstance(cmd, list) else cmd.split(),
                              capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return None

def run_ok(cmd, timeout=15):
    r = run(cmd, timeout)
    return r is not None and r.returncode == 0

def out(cmd, timeout=15):
    r = run(cmd, timeout)
    return r.stdout.strip() if r and r.returncode == 0 else ""

# ─── Platform checks ───────────────────────────────────────────
def require_root():
    if os.geteuid() != 0:
        print(col(R, "✗ This tool must run as root."))
        print(col(C, f"  sudo python3 {sys.argv[0]}"))
        sys.exit(1)

def check_deps():
    hard = [x for x in ("ip","systemctl","iptables","tor","curl") if not shutil.which(x)]
    if hard:
        print(col(R, f"✗ Required tools missing: {', '.join(hard)}"))
        print(col(C, "  Install: sudo apt install iproute2 systemd iptables tor curl"))
        sys.exit(1)
    missing = [x for x in ("macchanger",) if not shutil.which(x)]
    if missing:
        print(col(Y, f"⚠ Missing tools: {', '.join(missing)}"))
        print(col(C, f"  Install: sudo apt install {' '.join(missing)}"))

# ─── DNS / IP helpers ──────────────────────────────────────────
def get_real_country():
    for url in ("https://ipapi.co/country/", "https://ifconfig.co/country-iso"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                code = r.read().decode().strip()[:2].upper()
                if code.isalpha(): return code
        except Exception: pass
    return "US"

def get_tor_ip():
    r = run(["curl","-s","--max-time","15","--socks5-hostname",
             f"127.0.0.1:{SOCKS_PORT}","https://check.torproject.org/api/ip"], timeout=20)
    if r and r.returncode == 0 and r.stdout.strip():
        try:
            data = json.loads(r.stdout)
            if data.get("IsTor"): return data.get("IP")
        except Exception: pass
    return None

def wait_for_tor(timeout=120):
    """Block until Tor really works (bootstrapped), instead of guessing with sleep()."""
    print(col(Y, "▸ Waiting for Tor to bootstrap (up to %ds)..." % timeout))
    t0 = time.time()
    while time.time() - t0 < timeout:
        ip = get_tor_ip()
        if ip:
            print(col(G, f"  ✓ Tor is up — exit IP {ip}"))
            return True
        time.sleep(3)
    print(col(R, "  ✗ Tor did not come up in time (still retrying in the monitor loop)"))
    return False

# ─── Tor control (password protected) ──────────────────────────
def tor_control(commands, timeout=5):
    """Send commands to the control port. True only if every reply is 250."""
    try:
        s = socket.create_connection(("127.0.0.1", CTRL_PORT), timeout=timeout)
        s.settimeout(timeout)
        payload = f'AUTHENTICATE "{CTRL_PASS}"\r\n' + \
                  "".join(c + "\r\n" for c in commands) + "QUIT\r\n"
        s.sendall(payload.encode())
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk: break
            data += chunk
        s.close()
        lines = [l for l in data.decode(errors="replace").splitlines() if l.strip()]
        return len(lines) >= len(commands) + 1 and all(l.startswith("250") for l in lines)
    except Exception:
        return False

def tor_newnym():
    return tor_control(["SIGNAL NEWNYM"])

def hash_control_password():
    out_ = out(["tor", "--hash-password", CTRL_PASS])
    lines = [l.strip() for l in out_.splitlines() if l.strip().startswith("16:")]
    return lines[-1] if lines else None

# ─── Backup logic ──────────────────────────────────────────────
def backup_state():
    """Capture original state BEFORE any change. Idempotent."""
    state.clear()
    state.set("session", datetime.now().isoformat())
    state.set("cleanup_pending", True)

    # Network interface + MAC
    route = out("ip route show default").split()
    iface = route[route.index("dev")+1] if "dev" in route else None
    state.set("iface", iface)
    if iface:
        mac = out(f"cat /sys/class/net/{iface}/address")
        state.set("original_mac", mac)

    # Hostname
    state.set("original_hostname", out("hostname") or "kali")

    # resolv.conf
    if RESOLV.exists():
        state.set("resolv_existed", True)
        state.set("resolv_content", RESOLV.read_text())
        # Do NOT touch chattr — we never set +i so we don't need to unset it
    else:
        state.set("resolv_existed", False)

    # torrc
    if TORRC.exists():
        state.set("torrc_existed", True)
        state.set("torrc_content", TORRC.read_text())
    else:
        state.set("torrc_existed", False)

    # systemd-resolved state
    state.set("resolved_was_active",
              run_ok(["systemctl","is-active","--quiet","systemd-resolved"]))

    # Tor service state
    state.set("tor_was_running", run_ok(["systemctl","is-active","--quiet",TOR_SERVICE]))
    state.set("tor_was_enabled", run_ok(["systemctl","is-enabled","--quiet",TOR_SERVICE]))

    print(col(G, f"✓ State captured → {STATE_FILE}"))

# ─── Feature: MAC ──────────────────────────────────────────────
def change_mac():
    iface = state.get("iface")
    if not iface or not shutil.which("macchanger"):
        return
    print(col(Y, f"▸ Rotating MAC on {iface}..."))
    try:
        run(["ip","link","set",iface,"down"])
        time.sleep(0.3)
        run(["macchanger","-r",iface], timeout=10)
    finally:
        # ALWAYS bring interface back up
        run(["ip","link","set",iface,"up"])
    new_mac = out(f"cat /sys/class/net/{iface}/address")
    print(col(G, f"  ✓ New MAC: {new_mac}"))

# ─── Feature: Hostname ─────────────────────────────────────────
def change_hostname():
    new = f"phm-{os.urandom(2).hex()}"
    print(col(Y, f"▸ Hostname → {new}"))
    run(["hostnamectl","set-hostname",new])
    hosts = Path("/etc/hosts")
    if hosts.exists():
        try:
            lines = hosts.read_text().splitlines()
            lines = [f"127.0.1.1\t{new}" if "127.0.1.1" in l else l for l in lines]
            hosts.write_text("\n".join(lines) + "\n")
        except Exception: pass

# ─── Feature: Kill switch (safe private chains) ───────────────
def find_tor_user():
    for u in TOR_USERS:
        uid = out(["id", "-u", u])
        if uid.isdigit(): return u
    return None

def ipt(args, v6=False):
    tool = "ip6tables" if v6 else "iptables"
    if not shutil.which(tool): return False
    return run_ok([tool, "-w"] + args)

def kill_switch_on():
    """Only loopback, DHCP and the Tor daemon itself may leave the machine.
    Existing non-Tor connections are cut on purpose (otherwise they would leak)."""
    print(col(Y, "▸ Activating kill switch (private chains)..."))
    tor_user = find_tor_user()
    if not tor_user:
        print(col(R, "  ✗ Tor system user not found — kill switch NOT enabled (it would block Tor)."))
        return False

    for v6, chain in ((False, CHAIN_OUT), (True, CHAIN_OUT6)):
        ipt(["-N", chain], v6)
        ipt(["-F", chain], v6)
        ipt(["-A", chain, "-o", "lo", "-j", "ACCEPT"], v6)
        ipt(["-A", chain, "-m", "owner", "--uid-owner", tor_user, "-j", "ACCEPT"], v6)
        if not v6:   # DHCP renewals, so the lease does not expire during a long session
            ipt(["-A", chain, "-p", "udp", "--sport", "68", "--dport", "67", "-j", "ACCEPT"])
        ipt(["-A", chain, "-j", "DROP"], v6)
        ipt(["-D", "OUTPUT", "-j", chain], v6)          # idempotent
        hooked = ipt(["-I", "OUTPUT", "1", "-j", chain], v6)
        if not hooked and not v6:
            print(col(R, "  ✗ Could not hook the chain into OUTPUT — rolling back"))
            kill_switch_off(quiet=True)
            return False

    state.set("iptables_active", True)
    print(col(G, f"  ✓ Kill switch active (Tor user: {tor_user})"))
    return True

def kill_switch_off(quiet=False):
    """Remove ONLY our chains. Never touch global policy."""
    if not quiet: print(col(Y, "▸ Deactivating kill switch..."))
    for v6, chain in ((False, CHAIN_OUT), (True, CHAIN_OUT6)):
        for _ in range(10):
            if not ipt(["-D", "OUTPUT", "-j", chain], v6):
                break
        ipt(["-F", chain], v6)
        ipt(["-X", chain], v6)
    try: state.set("iptables_active", False)
    except Exception: pass
    if not quiet: print(col(G, "  ✓ Kill switch removed"))

# ─── Feature: DNS isolation ────────────────────────────────────
def isolate_dns():
    print(col(Y, "▸ Redirecting DNS to Tor's DNSPort..."))
    try:
        RESOLV.write_text(RESOLV_TEXT)
    except Exception as e:
        print(col(R, f"  ✗ Cannot write resolv.conf: {e}"))

def keep_dns_isolated():
    """NetworkManager/DHCP may rewrite resolv.conf mid-session — put ours back."""
    try:
        if RESOLV.read_text() != RESOLV_TEXT:
            RESOLV.write_text(RESOLV_TEXT)
    except Exception:
        pass

# ─── Feature: Tor config ───────────────────────────────────────
def configure_tor(country):
    hashed = hash_control_password()
    if not hashed:
        print(col(R, "✗ Could not hash the control password"))
        return False
    content = f"""SocksPort 127.0.0.1:{SOCKS_PORT}
DNSPort 127.0.0.1:53
ControlPort 127.0.0.1:{CTRL_PORT}
HashedControlPassword {hashed}
ExitNodes {{{country}}}
StrictNodes 0
AvoidDiskWrites 1
SafeLogging 1
"""
    try:
        TORRC.write_text(content)
    except Exception as e:
        print(col(R, f"✗ torrc write failed: {e}"))
        return False
    run(["systemctl","restart",TOR_SERVICE], timeout=30)
    return True

def set_exit_country(country):
    """Switch exit country on the live Tor (no restart, no dropped circuits)."""
    ok = tor_control([f'SETCONF ExitNodes="{{{country.lower()}}}"', "SIGNAL NEWNYM"])
    if not ok:   # fallback: rewrite torrc and restart
        ok = configure_tor(country)
    return ok

def rotate_country(real, cfg, first=False):
    target = pick_country(real, cfg)
    print(col(M, f"⟳ Exit country → {target}"))
    if first: configure_tor(target)
    else:     set_exit_country(target)
    return target

# ─── Cleanup (the critical part) ───────────────────────────────
def safe_cleanup(verbose=True):
    """Restore everything. Runs even on crash. Idempotent."""
    if verbose: print(col(Y, "\n▸ Restoring original state..."))

    # 1. Remove kill switch FIRST — most important for connectivity
    try: kill_switch_off(quiet=not verbose)
    except Exception: pass

    # 2. Restore resolv.conf
    try:
        if state.get("resolv_existed"):
            RESOLV.write_text(state.get("resolv_content",""))
            if verbose: print(col(G, "  ✓ resolv.conf restored"))
    except Exception as e:
        if verbose: print(col(R, f"  ✗ resolv.conf: {e}"))

    # 3. Restart systemd-resolved if it was active (regenerates its stub file)
    if state.get("resolved_was_active"):
        run(["systemctl","restart","systemd-resolved"])
        if verbose: print(col(G, "  ✓ systemd-resolved restarted"))

    # 4. Restore torrc, then bring Tor back to its previous state
    try:
        if state.get("torrc_existed"):
            TORRC.write_text(state.get("torrc_content",""))
        else:
            try: TORRC.unlink()
            except FileNotFoundError: pass
        if verbose: print(col(G, "  ✓ torrc restored"))
    except Exception: pass
    if state.get("tor_was_running"):
        run(["systemctl","restart",TOR_SERVICE], timeout=30)   # reload the ORIGINAL config
    else:
        run(["systemctl","stop",TOR_SERVICE], timeout=30)
        if verbose: print(col(G, "  ✓ Tor service stopped"))

    # 5. Ask NetworkManager to re-read DNS (no network off/on)
    if run_ok(["systemctl","is-active","--quiet","NetworkManager"]):
        run(["systemctl","reload","NetworkManager"], timeout=10)

    # 6. Restore MAC — with guaranteed link-up
    iface = state.get("iface")
    mac = state.get("original_mac")
    if iface and mac and shutil.which("macchanger") and \
       out(f"cat /sys/class/net/{iface}/address") != mac:
        try:
            run(["ip","link","set",iface,"down"])
            time.sleep(0.3)
            run(["macchanger","--mac",mac,iface], timeout=10)
        finally:
            run(["ip","link","set",iface,"up"])
        if verbose: print(col(G, f"  ✓ MAC restored: {mac}"))

    # 7. Restore hostname
    orig = state.get("original_hostname")
    if orig:
        run(["hostnamectl","set-hostname",orig])
        hosts = Path("/etc/hosts")
        if hosts.exists():
            try:
                lines = hosts.read_text().splitlines()
                lines = [f"127.0.1.1\t{orig}" if "127.0.1.1" in l else l for l in lines]
                hosts.write_text("\n".join(lines) + "\n")
            except Exception: pass
        if verbose: print(col(G, f"  ✓ Hostname restored: {orig}"))

    # 8. Verify connectivity
    if verbose: verify_connectivity()

    # 9. Mark state as clean
    state.set("cleanup_pending", False)

def verify_connectivity():
    print(col(Y, "▸ Verifying connectivity..."))
    dns_ok = False
    for _ in range(5):
        try:
            socket.gethostbyname("check.torproject.org")
            dns_ok = True
            break
        except Exception:
            time.sleep(2)
    print(col(G, "  ✓ DNS resolving") if dns_ok else
          col(R, "  ✗ DNS failing — run: sudo systemctl restart systemd-resolved NetworkManager"))
    net_ok = False
    for _ in range(5):
        try:
            s = socket.create_connection(("1.1.1.1", 443), timeout=3)
            s.close(); net_ok = True
            break
        except Exception:
            time.sleep(2)
    print(col(G, "  ✓ Outbound reachable") if net_ok else
          col(R, "  ✗ Outbound blocked — run: sudo phantomroute --panic"))
    return dns_ok and net_ok

# ─── Report ────────────────────────────────────────────────────
stats = {"checks":0,"ok":0,"fail":0,"rotations":0,"history":{}}

def write_report(stats=stats):
    if not stats["checks"] and not stats["rotations"]: return
    lines = [
        "═"*50,
        f"  {APP} v{VERSION} — Session Report",
        "═"*50,
        f"Started:        {state.get('session')}",
        f"Finished:       {datetime.now().isoformat()}",
        f"Total checks:   {stats['checks']}",
        f"Successful:     {stats['ok']}",
        f"Failed:         {stats['fail']}",
        f"Rotations:      {stats['rotations']}",
        "",
        "Countries visited:",
    ]
    for c, n in stats["history"].items():
        lines.append(f"  • {c}: {n}×")
    lines.append("═"*50)
    try:
        REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(col(G, f"✓ Report → {REPORT}"))
    except Exception as e:
        print(col(R, f"✗ Report failed: {e}"))

# ─── Signal handling ───────────────────────────────────────────
_cleaned = False
def on_signal(sig, frame):
    global _cleaned
    if _cleaned: return
    _cleaned = True
    stop_evt.set()                       # stop the monitor thread
    restore_terminal()                   # give the keyboard back
    print()
    if tor_lock.acquire(timeout=35):     # do not race a Tor restart in progress
        tor_lock.release()
    safe_cleanup()
    write_report()
    print(col(G, "\n✓ PhantomRoute stopped cleanly.\n"))
    sys.exit(0)

signal.signal(signal.SIGINT, on_signal)
signal.signal(signal.SIGTERM, on_signal)
signal.signal(signal.SIGHUP, on_signal)      # terminal closed

# ═══════════════════════════════════════════════════════════════
#  Interactive UI: banner, main menu, live dashboard, keyboard keys.
#  Standard library only. Identical in both editions.
# ═══════════════════════════════════════════════════════════════
import re
import threading
import select
import atexit
try:
    import termios, tty
except ImportError:                      # not a POSIX terminal
    termios = tty = None

DIM = '\033[2m'
GRADIENT = (87, 51, 45, 39, 33, 27)

LOGO = [
    "██████╗ ██╗  ██╗ █████╗ ███╗   ██╗████████╗ ██████╗ ███╗   ███╗",
    "██╔══██╗██║  ██║██╔══██╗████╗  ██║╚══██╔══╝██╔═══██╗████╗ ████║",
    "██████╔╝███████║███████║██╔██╗ ██║   ██║   ██║   ██║██╔████╔██║",
    "██╔═══╝ ██╔══██║██╔══██║██║╚██╗██║   ██║   ██║   ██║██║╚██╔╝██║",
    "██║     ██║  ██║██║  ██║██║ ╚████║   ██║   ╚██████╔╝██║ ╚═╝ ██║",
    "╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝    ╚═════╝ ╚═╝     ╚═╝",
]

COUNTRY_NAMES = {
    "AE":"UAE","AT":"Austria","BE":"Belgium","BH":"Bahrain","CA":"Canada",
    "CH":"Switzerland","CY":"Cyprus","DE":"Germany","DK":"Denmark","DZ":"Algeria",
    "EG":"Egypt","ES":"Spain","FI":"Finland","FR":"France","GB":"United Kingdom",
    "GR":"Greece","IE":"Ireland","IQ":"Iraq","IT":"Italy","JO":"Jordan",
    "KW":"Kuwait","LB":"Lebanon","LY":"Libya","MA":"Morocco","MX":"Mexico",
    "NL":"Netherlands","NO":"Norway","OM":"Oman","PT":"Portugal","QA":"Qatar",
    "SA":"Saudi Arabia","SE":"Sweden","SY":"Syria","TN":"Tunisia","TR":"Turkey",
    "US":"United States","YE":"Yemen",
}

class Cfg:
    """Session settings (menu / command-line)."""
    def __init__(self, interval):
        self.interval   = interval
        self.mac        = "mac" in FEATURES
        self.hostname   = "hostname" in FEATURES
        self.killswitch = "killswitch" in FEATURES
        self.country    = None            # None = automatic (nearby countries)

stop_evt = threading.Event()
tor_lock = threading.Lock()
_saved_term = None

def c256(n, t): return f"\033[38;5;{n}m{t}{N}"

def term_width():
    return shutil.get_terminal_size((80, 24)).columns

def banner_lines():
    if term_width() >= 66:
        lines = [c256(GRADIENT[i], row) for i, row in enumerate(LOGO)]
        lines.append(col(M, "   R  O  U  T  E") + col(W, f"   v{VERSION} · {EDITION} Edition"))
        lines.append(col(DIM, "   Tor identity rotation · safe state restoration"))
    else:                                 # narrow screens (phones)
        title = f" PHANTOMROUTE v{VERSION} · {EDITION} "
        lines = [col(C, "╔" + "═" * len(title) + "╗"),
                 col(C, "║") + col(W, title) + col(C, "║"),
                 col(C, "╚" + "═" * len(title) + "╝")]
    return lines

def clear_screen():
    sys.stdout.write("\033[H\033[2J"); sys.stdout.flush()

def banner():
    print("\n".join(banner_lines())); print()

# ─── Terminal mode (single-key input) ──────────────────────────
def term_cbreak():
    global _saved_term
    if termios and sys.stdin.isatty() and _saved_term is None:
        fd = sys.stdin.fileno()
        _saved_term = termios.tcgetattr(fd)
        tty.setcbreak(fd)                 # Ctrl+C still works
        sys.stdout.write("\033[?25l"); sys.stdout.flush()

def restore_terminal():
    global _saved_term
    if _saved_term is not None:
        try: termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _saved_term)
        except Exception: pass
        _saved_term = None
        try: sys.stdout.write("\033[?25h"); sys.stdout.flush()
        except Exception: pass

atexit.register(restore_terminal)

def read_key(timeout):
    if not sys.stdin.isatty():
        time.sleep(timeout); return ""
    try:
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        if r:
            return os.read(sys.stdin.fileno(), 1).decode(errors="ignore")
    except (OSError, ValueError):
        pass
    return ""

# ─── Country selection ─────────────────────────────────────────
def pick_country(real, cfg):
    return cfg.country or random.choice(NEARBY.get(real, DEFAULTS))

def ask_country(cfg):
    """Prompt for an exit country. Returns True if cfg.country changed."""
    clear_screen(); banner()
    print(col(W, "  Choose exit country\n"))
    items = [f"{c}  {n}" for c, n in sorted(COUNTRY_NAMES.items())]
    per_row = max(1, (term_width() - 2) // 24)
    for i in range(0, len(items), per_row):
        print("  " + "".join(col(Y, it[:2]) + it[2:].ljust(22) for it in items[i:i + per_row]))
    print(col(DIM, "\n  Any 2-letter code works. Enter = automatic (nearby countries)."))
    try:
        v = input(col(W, "\n  Country code » ")).strip().upper()
    except (EOFError, KeyboardInterrupt):
        return False
    if v == "":
        changed = cfg.country is not None
        cfg.country = None
        return changed
    if len(v) == 2 and v.isalpha():
        cfg.country = v
        return True
    print(col(R, "  ✗ Invalid code")); time.sleep(1.2)
    return False

# ─── Main menu ─────────────────────────────────────────────────
def settings_summary(cfg):
    parts = [f"interval {cfg.interval}s"]
    if "mac" in FEATURES:        parts.append("MAC " + ("on" if cfg.mac else "off"))
    if "hostname" in FEATURES:   parts.append("hostname " + ("on" if cfg.hostname else "off"))
    if "killswitch" in FEATURES: parts.append("kill switch " + ("on" if cfg.killswitch else "off"))
    parts.append("country " + (cfg.country or "auto"))
    return " · ".join(parts)

def menu_lines(cfg):
    L = banner_lines() + ["", col(W, "  Main menu"), ""]
    items = [("1", "Start  (current settings)")]
    if "killswitch" in FEATURES:
        items.append(("2", "Start  (Tor only — no kill switch)"))
    items += [("3", "Choose exit country"), ("4", "Settings"), ("5", "Status"),
              ("6", "Panic — restore the system after a crash"), ("0", "Exit")]
    for k, t in items:
        L.append(f"   {col(Y, '[' + k + ']')} {t}")
    L += ["", col(C, "  " + settings_summary(cfg))]
    return L

def settings_menu(cfg):
    while True:
        clear_screen(); banner()
        onoff = lambda b: col(G, "on") if b else col(R, "off")
        print(col(W, "  Settings\n"))
        print(f"   {col(Y,'[1]')} Rotation interval : {col(W, str(cfg.interval) + 's')}")
        if "mac" in FEATURES:        print(f"   {col(Y,'[2]')} Change MAC         : {onoff(cfg.mac)}")
        if "hostname" in FEATURES:   print(f"   {col(Y,'[3]')} Random hostname    : {onoff(cfg.hostname)}")
        if "killswitch" in FEATURES: print(f"   {col(Y,'[4]')} Kill switch        : {onoff(cfg.killswitch)}")
        print(f"   {col(Y,'[0]')} Back")
        try: ch = input(col(W, "\n  Select » ")).strip()
        except (EOFError, KeyboardInterrupt): return
        if ch == "1":
            try:
                v = int(input("  Seconds between rotations (min 10) » ").strip())
                cfg.interval = max(10, v)
            except (ValueError, EOFError, KeyboardInterrupt):
                pass
        elif ch == "2" and "mac" in FEATURES:        cfg.mac = not cfg.mac
        elif ch == "3" and "hostname" in FEATURES:   cfg.hostname = not cfg.hostname
        elif ch == "4" and "killswitch" in FEATURES: cfg.killswitch = not cfg.killswitch
        elif ch == "0": return

def run_menu(cfg, show_status, do_panic):
    """Returns True when the user chose Start, False to exit."""
    while True:
        clear_screen()
        print("\n".join(menu_lines(cfg)))
        try: ch = input(col(W, "\n  Select » ")).strip()
        except (EOFError, KeyboardInterrupt):
            print(); return False
        if ch == "1":
            return True
        if ch == "2" and "killswitch" in FEATURES:
            cfg.killswitch = False
            return True
        if ch == "3": ask_country(cfg)
        elif ch == "4": settings_menu(cfg)
        elif ch in ("5", "6"):
            clear_screen(); banner()
            (show_status if ch == "5" else do_panic)()
            try: input(col(DIM, "\n  Press Enter to return…"))
            except (EOFError, KeyboardInterrupt): pass
        elif ch == "0":
            return False

# ─── Live dashboard ────────────────────────────────────────────
_ANSI = re.compile(r"\033\[[0-9;?]*[A-Za-z]")

def wrap_items(items, width, indent="  ", sep="  "):
    """Pack items (which may contain colour codes) into lines no wider than `width`."""
    lines, cur, cur_len = [], [], 0
    for it in items:
        n = len(_ANSI.sub("", it))
        if cur and len(indent) + cur_len + len(sep) + n > width:
            lines.append(indent + sep.join(cur)); cur, cur_len = [], 0
        cur_len += n + (len(sep) if cur else 0)
        cur.append(it)
    if cur: lines.append(indent + sep.join(cur))
    return lines

def dashboard_lines(D, cfg, extra, width):
    narrow = width < 60
    ip = D["ip"]
    L = banner_lines() + [""]
    if ip:
        L.append(f"  {col(G,'●')} Tor {col(G,'CONNECTED')}")
        L.append(f"  Exit IP       {col(W, ip)}")
    else:
        L.append(f"  {col(R,'●')} Tor {col(R,'NO CONNECTION')} — retrying…")
    mode = "fixed" if cfg.country else "auto"
    name = COUNTRY_NAMES.get(D["country"], "")
    L.append(f"  Exit country  {col(W, D['country'])} {name} ({mode})")
    if D["paused"]:
        L.append(f"  Rotation      {col(Y, 'PAUSED')}")
    else:
        nxt = max(0, int(cfg.interval - (D["now"] - D["last_rot"])))
        L.append(f"  Next rotation in {col(W, str(nxt) + 's')}" + ("" if narrow else f"   (every {cfg.interval}s)"))
    checks = f"Checks {col(G, str(stats['ok']))} ok / {col(R if stats['fail'] else W, str(stats['fail']))} failed"
    rots = f"Rotations {col(W, str(stats['rotations']))}"
    if narrow:
        L += ["  " + checks, "  " + rots]
    else:
        L.append(f"  {checks}   ·   {rots}")
    for x in (extra or []):
        L.append("  " + x)
    L.append("")
    if D["msg"] and D["now"] - D["msg_t"] < 10:
        L.append(f"  {col(M, '›')} {D['msg']}")
    else:
        L.append("")
    keys = [("n", "new identity"), ("r", "rotate country"), ("c", "choose country"),
            ("p", "pause"), ("q", "quit")]
    L += wrap_items([f"{col(Y, '[' + k + ']')} {t}" for k, t in keys], width)
    return L

def run_dashboard(real, cfg, current, restart_tor, extra_lines=None, on_tick=None):
    D = {"ip": None, "msg": "", "msg_t": 0.0, "paused": False,
         "country": current, "last_rot": time.time(), "now": time.time()}

    def say(m): D["msg"], D["msg_t"] = m, time.time()

    def monitor():
        while not stop_evt.is_set():
            ip = get_tor_ip()
            if stop_evt.is_set(): break
            stats["checks"] += 1
            if ip:
                stats["ok"] += 1; D["ip"] = ip
            else:
                stats["fail"] += 1; D["ip"] = None
                if tor_lock.acquire(blocking=False):
                    try:
                        if not stop_evt.is_set():
                            say("Tor unreachable — restarting it…")
                            restart_tor()
                    finally:
                        tor_lock.release()
            stop_evt.wait(CHECK_INTERVAL)

    threading.Thread(target=monitor, daemon=True).start()

    def apply_country(cc):
        if not tor_lock.acquire(blocking=False):
            say("Tor is busy (restarting) — try again in a moment")
            return
        try:
            ok = set_exit_country(cc)
        finally:
            tor_lock.release()
        D["last_rot"] = time.time()
        if ok:
            D["country"] = cc
            stats["rotations"] += 1
            stats["history"][cc] = stats["history"].get(cc, 0) + 1
            say(f"Exit country → {cc} {COUNTRY_NAMES.get(cc, '')}")
        else:
            say("Could not change the exit country")

    def timed_rotation():
        if cfg.country:                   # fixed country: just build new circuits
            D["last_rot"] = time.time()
            stats["rotations"] += 1
            say(f"New circuit (country fixed to {cfg.country})" if tor_newnym()
                else "New identity failed")
        else:
            apply_country(pick_country(real, cfg))

    clear_screen()
    term_cbreak()
    try:
        while True:
            D["now"] = time.time()
            if on_tick: on_tick()
            if not D["paused"] and D["now"] - D["last_rot"] >= cfg.interval:
                timed_rotation()
            L = dashboard_lines(D, cfg, extra_lines() if extra_lines else None, term_width())
            sys.stdout.write("\033[H" + "".join(l + "\033[K\n" for l in L) + "\033[J")
            sys.stdout.flush()

            k = read_key(1.0).lower()
            if k == "q":
                break
            elif k == "n":
                say("New identity requested" if tor_newnym()
                    else "New identity failed (Tor limits it to once per ~10 s)")
            elif k == "r":
                cfg.country = None
                apply_country(pick_country(real, cfg))
            elif k == "p":
                D["paused"] = not D["paused"]
                D["last_rot"] = time.time()
                say("Rotation paused" if D["paused"] else "Rotation resumed")
            elif k == "c":
                restore_terminal()
                changed = ask_country(cfg)
                clear_screen(); term_cbreak()
                if changed:
                    apply_country(pick_country(real, cfg))
                else:
                    say("Country unchanged")
    finally:
        restore_terminal()


# ─── Panic recovery (after a crash) ────────────────────────────
def panic_mode():
    require_root()
    kill_switch_off(quiet=True)          # always safe: removes only our own chains
    if not state.load() or not state.get("cleanup_pending"):
        print(col(G, "✓ No pending state — system is clean."))
        return
    print(col(Y, f"⚠ Found crashed session from {state.get('session')}"))
    print(col(Y, "  Running emergency restoration..."))
    safe_cleanup()
    print(col(G, "\n✓ Emergency recovery complete."))

# ─── Status ────────────────────────────────────────────────────
def print_status():
    if os.geteuid() != 0:
        print(col(Y, "Run with sudo to read the saved state.")); return
    if not state.load():
        print(col(Y, "No saved state."))
    else:
        print(json.dumps(state.d, indent=2))

def kali_info():
    """Extra dashboard lines for the Kali edition."""
    ks = col(G, "ACTIVE") if state.get("iptables_active") else col(Y, "OFF")
    iface = state.get("iface")
    mac = out(f"cat /sys/class/net/{iface}/address") if iface else "-"
    host = socket.gethostname()
    return [f"Kill switch {ks}   ·   MAC {col(W, mac)}   ·   Host {col(W, host)}"]

# ─── Session ───────────────────────────────────────────────────
def start_session(cfg):
    require_root()
    check_deps()

    # Recover first if the previous session crashed
    if state.load() and state.get("cleanup_pending"):
        print(col(Y, "⚠ Previous session did not clean up. Recovering first..."))
        safe_cleanup(verbose=False)

    clear_screen(); banner()

    # 1. Backup originals
    backup_state()
    real_country = get_real_country()
    print(col(G, f"✓ Real country: {real_country}"))

    # 2. Apply changes
    if cfg.mac and "mac" in FEATURES:  change_mac()
    if cfg.hostname:                   change_hostname()
    if cfg.killswitch:                 kill_switch_on()
    isolate_dns()

    # 3. Start Tor and wait until it really works
    current = rotate_country(real_country, cfg, first=True)
    stats["rotations"] = 1
    stats["history"][current] = 1
    wait_for_tor()
    print(col(G, "\n✅ PhantomRoute is now active."))
    time.sleep(1.5)

    # 4. Live dashboard (keys: n r c p q)
    run_dashboard(
        real_country, cfg, current,
        restart_tor=lambda: run(["systemctl", "restart", TOR_SERVICE], timeout=30),
        extra_lines=kali_info,
        on_tick=keep_dns_isolated,
    )
    on_signal(None, None)                # 'q' pressed: restore everything and exit

# ─── Main ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        prog=APP,
        description="Run without options for the interactive menu.")
    parser.add_argument("--start", action="store_true",
                        help="Start immediately (skip the menu)")
    parser.add_argument("--panic", action="store_true",
                        help="Recover from a crashed session and exit")
    parser.add_argument("--status", action="store_true",
                        help="Show current state and exit")
    parser.add_argument("--interval", type=int, default=CHANGE_INTERVAL,
                        help="Seconds between country rotations (min 10)")
    parser.add_argument("--country", metavar="CC",
                        help="Fix the exit country (2-letter code, e.g. DE)")
    parser.add_argument("--no-mac", action="store_true", help="Skip MAC change")
    parser.add_argument("--no-hostname", action="store_true", help="Skip hostname change")
    parser.add_argument("--no-killswitch", action="store_true", help="Skip iptables")
    args = parser.parse_args()

    if args.panic:  return panic_mode()
    if args.status: return print_status()

    cfg = Cfg(max(10, args.interval))
    if args.no_mac:        cfg.mac = False
    if args.no_hostname:   cfg.hostname = False
    if args.no_killswitch: cfg.killswitch = False
    if args.country:
        cc = args.country.strip().upper()
        if len(cc) != 2 or not cc.isalpha():
            parser.error("--country needs a 2-letter code, e.g. DE")
        cfg.country = cc

    interactive = len(sys.argv) == 1 and sys.stdin.isatty() and sys.stdout.isatty()
    if interactive and not run_menu(cfg, print_status, panic_mode):
        return
    start_session(cfg)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        on_signal(None, None)
    except Exception as e:
        print(col(R, f"\n✗ Unexpected error: {e}"))
        safe_cleanup()
        write_report()
        sys.exit(1)
