<p align="center">
  <img src="../assets/banner.svg" alt="PhantomRoute" width="640">
</p>

# PhantomRoute — Termux (Android) Edition

Tor exit-country rotation on Android. No root required.

## Requirements

- **Termux** (preferably from F-Droid)
- Internet connection

## Installation

```bash
pkg update -y && pkg install -y git
git clone https://github.com/Black-ghost7/PhantomRoute.git
cd PhantomRoute/PhantomRoute-Termux
chmod +x install.sh
./install.sh
```

## One-tap shortcut (optional)

Android has no desktop-style application menu. Install the free **Termux:Widget** app from F-Droid, add its widget to your home screen, and the **PhantomRoute** shortcut created by `install.sh` appears in it.

## Usage

Just type the name (`phr` is an even shorter alias):

```bash
phantom                         # interactive menu
phantom --start                 # start immediately
phantom --country DE            # fix the exit country
phantom --interval 60           # rotate every 60 seconds (minimum 10)
phantom --status                # show saved state
phantom --panic                 # recover after a crash
```

Dashboard keys: `n` new identity · `r` rotate country · `c` choose country · `p` pause · `q` quit.
The layout adapts to the narrow phone screen automatically.

## Routing commands through Tor

While the tool runs, Tor listens on `127.0.0.1:9050`:

```bash
pkg install torsocks
torsocks curl https://check.torproject.org/api/ip

# or
curl --socks5-hostname 127.0.0.1:9050 https://check.torproject.org/api/ip
```

## Differences from the Kali edition

- No `systemd`: Tor runs as a child process, and `torrc` is restored on exit.
- No kill switch (Android restriction): apps are **not** routed through Tor automatically, only what you point at the proxy.
- No MAC or hostname changes.
- DNS leak protection is limited without root.
