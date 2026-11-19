#!/usr/bin/env bash
# Removes PhantomRoute. Run `sudo phantomroute --panic` first if a session crashed.
set -u
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
$SUDO rm -rf /usr/local/share/phantomroute /usr/local/bin/phantomroute /var/lib/phantomroute
echo "[✓] PhantomRoute removed."
