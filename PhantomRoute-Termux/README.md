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

## Usage

```bash
phantomroute                    # start
phantomroute --interval 60      # rotate every 60 seconds (minimum 10)
phantomroute --status           # show saved state
phantomroute --panic            # recover after a crash
```

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
