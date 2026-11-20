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
VERSION    = "1.2"
EDITION    = "Termux"
FEATURES   = set()          # no MAC / hostname / kill switch without root
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

def rotate(real, cfg, first=False):
    target = pick_country(real, cfg)
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
    stop_evt.set()
    restore_terminal()
    if tor_lock.acquire(timeout=35):
        tor_lock.release()
    safe_cleanup()
    write_report()
    sys.exit(0)

signal.signal(signal.SIGINT, on_signal)
signal.signal(signal.SIGTERM, on_signal)
signal.signal(signal.SIGHUP, on_signal)

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


# ─── Status ────────────────────────────────────────────────────
def print_status():
    if state.load(): print(json.dumps(state.d, indent=2))
    else: print("No state.")

def panic():
    if state.load() and state.get("cleanup_pending"):
        print(col(Y, "Recovering..."))
        run(["pkill", "-f", f"{TOR_BIN} -f {TORRC}"])   # leftover tor from the crashed session
        safe_cleanup()
    print(col(G, "Done."))

def restart_tor():
    stop_tor()
    start_tor()

# ─── Session ───────────────────────────────────────────────────
def start_session(cfg):
    check_deps()

    if state.load() and state.get("cleanup_pending"):
        print(col(Y, "⚠ Previous crash detected — recovering..."))
        run(["pkill", "-f", f"{TOR_BIN} -f {TORRC}"])
        safe_cleanup(verbose=False)

    clear_screen(); banner()

    state.clear()
    state.set("session", datetime.now().isoformat())
    state.set("cleanup_pending", True)
    state.set("platform", "termux")

    real = get_real_country()
    print(col(G, f"✓ Real country: {real}"))

    current = rotate(real, cfg, first=True)
    if not (tor_proc and tor_proc.poll() is None):
        print(col(R, "✗ Cannot start Tor"))
        safe_cleanup()
        sys.exit(1)
    stats["rotations"] = 1
    stats["history"][current] = 1
    wait_for_tor()
    print(col(G, "\n✅ PhantomRoute active."))
    print(col(C, f"  Route apps via SOCKS5 127.0.0.1:{SOCKS_PORT} (or torsocks)."))
    time.sleep(2)

    run_dashboard(real, cfg, current, restart_tor=restart_tor)   # keys: n r c p q
    on_signal(None, None)

# ─── Main ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        prog=APP, description="Run without options for the interactive menu.")
    parser.add_argument("--start", action="store_true", help="Start immediately (skip the menu)")
    parser.add_argument("--panic", action="store_true", help="Recover crashed session")
    parser.add_argument("--status", action="store_true", help="Show state")
    parser.add_argument("--interval", type=int, default=CHANGE_INTERVAL,
                        help="Seconds between rotations (min 10)")
    parser.add_argument("--country", metavar="CC",
                        help="Fix the exit country (2-letter code, e.g. DE)")
    args = parser.parse_args()

    if args.panic:  return panic()
    if args.status: return print_status()

    cfg = Cfg(max(10, args.interval))
    if args.country:
        cc = args.country.strip().upper()
        if len(cc) != 2 or not cc.isalpha():
            parser.error("--country needs a 2-letter code, e.g. DE")
        cfg.country = cc

    interactive = len(sys.argv) == 1 and sys.stdin.isatty() and sys.stdout.isatty()
    if interactive and not run_menu(cfg, print_status, panic):
        return
    start_session(cfg)

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
