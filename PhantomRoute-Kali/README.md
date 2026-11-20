# PhantomRoute — Kali / Debian / Ubuntu Edition

Tor identity rotation with a kill switch, MAC and hostname changes, and full system restoration.

## Requirements

- Kali, Debian or Ubuntu (or derivatives) with `systemd` and `NetworkManager`
- root privileges (`sudo`)
- Python 3.8+
- Packages: `tor` `curl` `macchanger` `iptables` `iproute2`

## Installation

```bash
chmod +x install.sh
./install.sh
```

Or manually:

```bash
sudo apt update
sudo apt install -y tor curl macchanger iptables iproute2 python3
sudo python3 phantomroute.py
```

> During the `macchanger` install you may be asked whether to change the MAC automatically at boot. Choose **No** (`install.sh` answers this for you).

## Usage

```bash
phantomroute                    # start
phantomroute --interval 30      # faster rotation (minimum 10 s)
phantomroute --no-mac           # do not change the MAC
phantomroute --no-killswitch    # do not use iptables
phantomroute --status           # show saved state
phantomroute --panic            # emergency restore
```

## What happens when you start it

1. The original state (MAC, hostname, `resolv.conf`, `torrc`, service states) is saved to `/var/lib/phantomroute/state.json` (root-only).
2. Your real country is detected so nearby exit countries can be chosen.
3. MAC and hostname are changed.
4. The kill switch is enabled in two private chains, `PHANTOMR_OUT` (IPv4) and `PHANTOMR_OUT6` (IPv6). Only loopback, DHCP and the Tor user (`debian-tor`) may send traffic out.
5. DNS is pointed to `127.0.0.1` (Tor's DNSPort).
6. Tor is started and the tool waits until it really works, then rotates the exit country every `--interval` seconds (without restarting Tor), checking the connection and re-enforcing the DNS settings periodically.

## Configuring your applications

The tool does not redirect system traffic automatically. Point your applications at **SOCKS5 `127.0.0.1:9050`** or use:

```bash
torsocks curl https://check.torproject.org/api/ip
proxychains4 firefox        # after setting proxychains to: socks5 127.0.0.1 9050
```

Any connection outside Tor is blocked while the tool runs (unless you use `--no-killswitch`).

## Stopping and restoring

Press `Ctrl + C`. Everything returns to its original state and DNS/connectivity are verified.
After a crash: `sudo phantomroute --panic`.

## Uninstall

```bash
./uninstall.sh
```
