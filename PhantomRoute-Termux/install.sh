#!/usr/bin/env bash
# PhantomRoute installer for Termux
set -e

APP_DIR="$PREFIX/share/phantomroute"
BIN_DIR="$PREFIX/bin"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -z "$PREFIX" ] || [ ! -d "/data/data/com.termux" ]; then
    echo "[✗] This installer is for Termux only."
    echo "    On Kali/Debian use PhantomRoute-Kali/install.sh"
    exit 1
fi

echo "[*] Installing PhantomRoute for Termux..."

# Update + install deps
pkg update -y
pkg install -y python tor curl

# Copy script
mkdir -p "$APP_DIR" "$BIN_DIR"
cp "$SCRIPT_DIR/phantomroute.py" "$APP_DIR/"
chmod +x "$APP_DIR/phantomroute.py"

# Create launcher
cat > "$BIN_DIR/phantomroute" << EOF
#!/data/data/com.termux/files/usr/bin/bash
exec python3 "$APP_DIR/phantomroute.py" "\$@"
EOF
chmod +x "$BIN_DIR/phantomroute"

echo
echo "╔══════════════════════════════════════════════════╗"
echo "║  ✓ PhantomRoute installed on Termux             ║"
echo "║                                                  ║"
echo "║  Usage:                                          ║"
echo "║    phantomroute             # Start              ║"
echo "║    phantomroute --panic     # Recover crash      ║"
echo "║    phantomroute --status    # Show state         ║"
echo "║                                                  ║"
echo "║  To route apps through Tor:                      ║"
echo "║    curl --socks5-hostname 127.0.0.1:9050 URL     ║"
echo "╚══════════════════════════════════════════════════╝"
