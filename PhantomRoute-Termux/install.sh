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

# Short commands:  phantom  and  phr
for name in phantom phr; do
    existing="$(command -v "$name" 2>/dev/null || true)"
    if [ -n "$existing" ] && [ "$(readlink -f "$existing")" != "$(readlink -f "$BIN_DIR/phantomroute")" ]; then
        echo "[!] '$name' already exists ($existing) — skipping that shortcut"
    else
        ln -sf "$BIN_DIR/phantomroute" "$BIN_DIR/$name"
    fi
done

# Termux:Widget shortcut (optional app from F-Droid; Android has no desktop-style menu icons)
mkdir -p "$HOME/.shortcuts"
cat > "$HOME/.shortcuts/PhantomRoute" << EOF
#!/data/data/com.termux/files/usr/bin/bash
exec "$BIN_DIR/phantomroute"
EOF
chmod 700 "$HOME/.shortcuts/PhantomRoute"

echo
echo "╔══════════════════════════════════════════════════╗"
echo "║  ✓ PhantomRoute installed on Termux              ║"
echo "║                                                  ║"
echo "║  Just type:                                      ║"
echo "║    phantom            # interactive menu        ║"
echo "║    phr                # same, even shorter      ║"
echo "║    phantom --start    # start immediately       ║"
echo "║    phantom --panic    # recover after a crash   ║"
echo "║                                                  ║"
echo "║  To route apps through Tor:                      ║"
echo "║    curl --socks5-hostname 127.0.0.1:9050 URL     ║"
echo "╚══════════════════════════════════════════════════╝"
