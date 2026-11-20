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

# Short commands:  phantom  and  phr
for name in phantom phr; do
    target="/usr/local/bin/$name"
    existing="$(command -v "$name" 2>/dev/null || true)"
    if [ -n "$existing" ] && [ "$(readlink -f "$existing")" != "$(readlink -f "$BIN")" ]; then
        echo "[!] '$name' already exists ($existing) — skipping that shortcut"
    else
        $SUDO ln -sf "$BIN" "$target"
    fi
done

# ─── Desktop icon + application-menu entry ───────────────────
ICON_SRC="$SCRIPT_DIR/icons/hicolor"
DESKTOP_SRC="$SCRIPT_DIR/phantomroute.desktop"
if [ -d "$ICON_SRC" ] && [ -f "$DESKTOP_SRC" ]; then
    echo "[*] Installing icon and application-menu entry..."
    while IFS= read -r f; do
        $SUDO install -D -m 644 "$f" "/usr/share/icons/hicolor/${f#"$ICON_SRC"/}"
    done < <(find "$ICON_SRC" -type f -name '*.png')
    $SUDO install -D -m 644 "$DESKTOP_SRC" /usr/share/applications/phantomroute.desktop
    command -v gtk-update-icon-cache  >/dev/null 2>&1 && $SUDO gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
    command -v update-desktop-database >/dev/null 2>&1 && $SUDO update-desktop-database /usr/share/applications >/dev/null 2>&1 || true

    # Optional shortcut on the user's desktop (the user who ran the installer)
    if [ "$(id -u)" -eq 0 ]; then TARGET_USER="${SUDO_USER:-}"; else TARGET_USER="$(id -un)"; fi
    if [ -n "$TARGET_USER" ]; then
        as_user() { if [ "$(id -u)" -eq 0 ]; then runuser -u "$TARGET_USER" -- "$@"; else "$@"; fi; }
        T_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
        DESK="$(as_user xdg-user-dir DESKTOP 2>/dev/null || true)"
        { [ -n "$DESK" ] && [ -d "$DESK" ]; } || DESK="$T_HOME/Desktop"
        if [ -d "$DESK" ]; then
            SHORTCUT="$DESK/phantomroute.desktop"
            as_user cp /usr/share/applications/phantomroute.desktop "$SHORTCUT"
            as_user chmod +x "$SHORTCUT"
            # mark as trusted (GNOME / Xfce) — harmless if gio is unavailable
            as_user gio set "$SHORTCUT" metadata::trusted true >/dev/null 2>&1 || true
            as_user gio set "$SHORTCUT" metadata::xfce-exe-checksum "$(sha256sum "$SHORTCUT" | cut -d' ' -f1)" >/dev/null 2>&1 || true
            echo "[✓] Desktop shortcut: $SHORTCUT"
            echo "    (if it shows a warning icon: right-click → Allow Launching)"
        fi
    fi
fi

echo
echo "╔══════════════════════════════════════════════════╗"
echo "║  ✓ PhantomRoute installed successfully           ║"
echo "║                                                  ║"
echo "║  Click the PhantomRoute icon in the app menu,    ║"
echo "║  or just type:                                   ║"
echo "║    phantom            # interactive menu        ║"
echo "║    phr                # same, even shorter      ║"
echo "║    phantom --start    # start immediately       ║"
echo "║    phantom --panic    # recover after a crash   ║"
echo "║    phantom --help     # all options             ║"
echo "╚══════════════════════════════════════════════════╝"
