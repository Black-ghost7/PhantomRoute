#!/usr/bin/env bash
# Removes PhantomRoute. Run `sudo phantom --panic` first if a session crashed.
set -u
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

$SUDO rm -rf /usr/local/share/phantomroute /var/lib/phantomroute
for name in phantomroute phantom phr; do
    f="/usr/local/bin/$name"
    # remove only our own launcher / symlinks
    if [ -L "$f" ] || grep -q "phantomroute.py" "$f" 2>/dev/null; then $SUDO rm -f "$f"; fi
done

# icon + menu entry
$SUDO rm -f /usr/share/applications/phantomroute.desktop
$SUDO find /usr/share/icons/hicolor -name phantomroute.png -delete 2>/dev/null || true
command -v gtk-update-icon-cache   >/dev/null 2>&1 && $SUDO gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
command -v update-desktop-database >/dev/null 2>&1 && $SUDO update-desktop-database /usr/share/applications >/dev/null 2>&1 || true

# desktop shortcut of the user who runs this script
if [ "$(id -u)" -eq 0 ]; then TARGET_USER="${SUDO_USER:-}"; else TARGET_USER="$(id -un)"; fi
if [ -n "$TARGET_USER" ]; then
    T_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
    DESK="$T_HOME/Desktop"
    if command -v xdg-user-dir >/dev/null 2>&1; then
        d="$(if [ "$(id -u)" -eq 0 ]; then runuser -u "$TARGET_USER" -- xdg-user-dir DESKTOP 2>/dev/null; else xdg-user-dir DESKTOP 2>/dev/null; fi || true)"
        [ -n "$d" ] && DESK="$d"
    fi
    rm -f "$DESK/phantomroute.desktop"
fi
echo "[✓] PhantomRoute removed."
