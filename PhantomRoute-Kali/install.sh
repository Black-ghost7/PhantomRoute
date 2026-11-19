#!/usr/bin/env bash
# PhantomRoute installer for Kali / Debian / Ubuntu
# Installs system-wide (root-owned) because the tool runs as root.
set -euo pipefail

APP_DIR="/usr/local/share/phantomroute"
BIN="/usr/local/bin/phantomroute"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v apt-get >/dev/null 2>&1; then
    echo "[✗] This installer supports apt-based systems (Kali/Debian/Ubuntu)."
    exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
    command -v sudo >/dev/null 2>&1 || { echo "[✗] Run as root or install sudo."; exit 1; }
else
    SUDO=""
fi

echo "[*] Installing dependencies: python3 tor curl macchanger iptables iproute2..."
# Answer macchanger's debconf question ("change MAC at boot?") with NO
echo "macchanger macchanger/automatically_run boolean false" | $SUDO debconf-set-selections 2>/dev/null || true
$SUDO apt-get update -y
$SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y python3 tor curl macchanger iptables iproute2

echo "[*] Installing files..."
$SUDO install -d -m 755 "$APP_DIR"
$SUDO install -m 755 "$SCRIPT_DIR/phantomroute.py" "$APP_DIR/phantomroute.py"

# Launcher (root-owned, so a normal user cannot tamper with code that runs as root)
$SUDO tee "$BIN" >/dev/null <<LAUNCH
#!/usr/bin/env bash
if [ "\$(id -u)" -ne 0 ]; then exec sudo python3 "$APP_DIR/phantomroute.py" "\$@"; fi
exec python3 "$APP_DIR/phantomroute.py" "\$@"
LAUNCH
$SUDO chmod 755 "$BIN"

echo
echo "╔══════════════════════════════════════════════════╗"
echo "║  ✓ PhantomRoute installed successfully           ║"
echo "║                                                  ║"
echo "║  Usage:                                          ║"
echo "║    phantomroute             # Start              ║"
echo "║    phantomroute --panic     # Recover crash      ║"
echo "║    phantomroute --status    # Show state         ║"
echo "║    phantomroute --help      # All options        ║"
echo "╚══════════════════════════════════════════════════╝"
