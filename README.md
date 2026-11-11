# SDN Firewall with Ryu and Mininet

An SDN-based firewall that runs as an OpenFlow controller. Instead of filtering
traffic on a host or in a middlebox, the policy lives in the controller: the
switch forwards nothing on its own, and every decision — allow, drop, log — is
made in `firewall.py`.

Built with **Ryu 4.34**, **Mininet 2.3.0** and **Open vSwitch 2.17** on
**Ubuntu 22.04**.

---

## What it does

| Rule | Implementation | Verified |
| --- | --- | --- |
| Block ICMP (ping) | `ipv4.proto == 1` | ✅ 100% packet loss |
| Block TCP/UDP ports | `tcp.dst_port` / `udp.dst_port` in `blocked_ports` | ✅ port 80 times out, 8080 works |
| Block IP addresses | `src_ip` / `dst_ip` in `blocked_ips` | ✅ bidirectional |
| Log dropped packets | `[DROP #n]` entries on the controller | ✅ 7 drops recorded |

Rules are plain Python lists at the top of `firewall.py`, so changing policy is
a one-line edit.

---

## Verified output

Real output from `bash run.sh` on Ubuntu 22.04 (WSL2, kernel
`6.18.33.2-microsoft-standard-WSL2`):

```text
=== 1/3  Starting Ryu controller (firewall.py) ===
    controller listening on 127.0.0.1:6633

=== 2/3  Booting topology and running tests ===
*** Creating network
*** Adding hosts: h1 h2
*** Adding switches: s1
*** Adding links: (h1, s1) (h2, s1)
*** Starting controller c0
*** Starting 1 switches: s1 ...
*** Waiting for switches to connect: s1

--- ICMP: h1 ping h2 (expect 100% packet loss) ---
2 packets transmitted, 0 received, 100% packet loss, time 1027ms

--- TCP/80: blocked port (expect http_code=000 exit=28) ---
http_code=000 exit=28

--- TCP/8080: allowed port (expect http_code=200 exit=0) ---
http_code=200 exit=0

--- pingall ---
*** Results: 100% dropped (0/2 received)

=== 3/3  Packets dropped by the controller ===
[DROP #1] Blocked ICMP packet from 10.0.0.1 to 10.0.0.2
[DROP #2] Blocked ICMP packet from 10.0.0.1 to 10.0.0.2
[DROP #3] Blocked TCP packet on port 80 from 10.0.0.1 to 10.0.0.2
[DROP #4] Blocked TCP packet on port 80 from 10.0.0.1 to 10.0.0.2
[DROP #5] Blocked TCP packet on port 80 from 10.0.0.1 to 10.0.0.2
[DROP #6] Blocked ICMP packet from 10.0.0.1 to 10.0.0.2
[DROP #7] Blocked ICMP packet from 10.0.0.2 to 10.0.0.1
```

The important comparison is **port 80 vs port 8080**: same host, same cable,
same switch. Port 8080 returns `http_code=200`, which proves the network is
healthy and only the configured rules are blocking traffic.

`exit=28` is curl's timeout — the SYN was *silently dropped*. A closed port
would have produced `exit=7` (connection refused, an RST from the kernel).

---

## Architecture

```text
        +----------------------------------+
        |  Ryu controller                  |
        |  firewall.py                     |
        |  control plane                   |
        |  127.0.0.1:6633                  |
        +---------------+------------------+
                        |  OpenFlow 1.3
                        |
                +-------+--------+
                |      s1        |  Open vSwitch
                |  flow table    |  data plane
                +--+----------+--+
                   |          |
              +----+----+ +---+-----+
              |   h1    | |   h2    |
              | 10.0.0.1| | 10.0.0.2|
              +---------+ +---------+
```

Two hosts, one switch, one controller. The switch has **no forwarding rules of
its own** — it asks the controller about every packet.

### The packet lifecycle

1. `s1` connects to Ryu and sends `OFPSwitchFeatures`.
2. Ryu installs a single **table-miss** flow: *anything unmatched → send to the
   controller, do not buffer* (`priority=0`, `OFPP_CONTROLLER`,
   `OFPCML_NO_BUFFER`).
3. Every packet now arrives as `EventOFPPacketIn`.
4. `packet_in_handler` parses it and applies the rules in order: blocked IP →
   blocked port → ICMP.
5. A blocked packet is dropped by **not replying**. The switch kept no copy, so
   silence is the drop.
6. An allowed packet is flooded out with `OFPPacketOut` and `data=msg.data`.

A full walkthrough — including the OpenFlow handshake, why ARP must be allowed,
and the buffer bug that broke the original code — is in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Quick start

### Windows (WSL2) — recommended

WSL2's kernel ships the `openvswitch` module that Mininet needs. Double-click
**`Run Demo.bat`**, or:

```powershell
wsl --cd "C:\Users\purus\OneDrive\Desktop\SDN-Firewall" -d Ubuntu-22.04 -- bash run.sh
```

`run.sh` installs anything missing, patches Ryu for modern eventlet, and runs
the demo. If WSL is missing: `wsl --install -d Ubuntu-22.04`, then reboot.

### Docker

```powershell
.\run.ps1
```

Builds the image from `Dockerfile` and runs the demo in a privileged container.
Docker Desktop's kernel may not provide the `openvswitch` module; the entrypoint
warns you if so.

### Native Linux

```bash
bash run.sh
```

### Manual, two terminals

```bash
# terminal 1 — controller
ryu-manager firewall.py

# terminal 2 — network
sudo python3 sdn_topology.py
```

Then at the `mininet>` prompt:

```text
mininet> h1 ping h2                              # blocked
mininet> h2 python3 -m http.server 80 &
mininet> h1 curl -m 3 http://10.0.0.2/           # blocked, times out
mininet> h2 python3 -m http.server 8080 &
mininet> h1 curl -m 3 http://10.0.0.2:8080/      # allowed, HTTP 200
mininet> pingall
mininet> exit
```

---

## Changing the policy

Edit the top of `firewall.py`:

```python
self.blocked_ips = []          # e.g. ['10.0.0.1'] to block h1 entirely
self.blocked_ports = [22, 80]  # SSH and HTTP
```

Re-run the launcher. No rebuild is needed for the WSL/Linux route.

---

## Testing

The firewall's decision logic is plain Python, so it can be tested without
Mininet or Ryu on any OS:

```bash
python tests/test_firewall_logic.py
```

```text
Ran 10 tests in 0.001s
OK
```

The suite stubs the Ryu modules and asserts that ICMP, blocked TCP/UDP ports and
blocked source/destination IPs are dropped, that ARP and allowed traffic are
forwarded, and that the packet-out carries its payload when the switch does not
buffer.

CI runs the same suite on Python 3.10–3.12 — see
[`.github/workflows/tests.yml`](.github/workflows/tests.yml).

---

## Project structure

```text
.
├── firewall.py                 Ryu application — the firewall itself
├── sdn_topology.py             Mininet topology (h1, h2, s1, remote controller)
├── demo.sh                     End-to-end demo: controller + topology + tests
├── run.sh                      One-command launcher for WSL2 / Linux
├── Run Demo.bat                Double-click launcher for Windows
├── run.ps1                     Docker Desktop launcher
├── Dockerfile                  Ubuntu 22.04 + Mininet + OVS + Ryu
├── docker-entrypoint.sh        Starts OVS inside the container
├── requirements.txt            Pinned Ryu / eventlet / dnspython
├── tools/
│   └── patch_ryu_wsgi.py       Compatibility patch for Ryu 4.34 + eventlet
├── tests/
│   └── test_firewall_logic.py  Offline unit tests (no Linux required)
├── docs/
│   └── ARCHITECTURE.md         Deep dive: SDN, OpenFlow, the bugs
├── BUILD.md                    Setup details and changelog
└── LICENSE                     MIT
```

---

## Design notes and limitations

This is a teaching implementation. It is correct, but deliberately simple, and
these are the trade-offs worth knowing:

1. **Reactive, not proactive.** Every packet is punted to the controller. A real
   firewall would install high-priority *drop* flows so the switch discards
   blocked traffic at line rate and the controller is never consulted.
2. **It is a hub, not a switch.** `OFPP_FLOOD` is used and `mac_to_port` is never
   populated, so there is no MAC learning.
3. **Destination-only port matching.** `tcp.dst_port` only — traffic *from* a
   blocked port is not filtered.
4. **Stateless.** It cannot distinguish a solicited reply from an unsolicited
   connection, so it cannot express "allow responses to outbound flows".
5. **Rules are in memory.** Restarting Ryu resets the policy.
6. **IPv4 only.** IPv6 has no `ipv4` header and therefore falls through
   unfiltered.
7. **ARP must stay allowed.** Without it the hosts cannot resolve each other and
   nothing works — including the tests that are supposed to succeed.

---

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `Cannot import name 'ALREADY_HANDLED'` | Ryu 4.34 vs eventlet ≥ 0.31 — run `tools/patch_ryu_wsgi.py` |
| `ryu-manager: command not found` | Ryu not installed — use `run.sh`, which installs it |
| Mininet hangs at "Waiting for switches to connect" | Controller not listening on 6633 |
| `openvswitch` module missing | Kernel without OVS — use WSL2 rather than Docker Desktop |
| Everything drops, no `[DROP]` lines | Packet-out without `data=` — see `docs/ARCHITECTURE.md` |

---

## Why this cannot run natively on Windows

Mininet is not a userspace simulator. It builds real network namespaces, `veth`
pairs and an Open vSwitch datapath, which needs a Linux kernel and root. Ryu
also fails to install on current Python/Windows builds because its `setup.py`
depends on a setuptools API removed in 2020.

Use WSL2, Docker, or Linux. WSL2 is the most reliable on Windows.

---

## Credits

Based on [ebongemma007/SDN-Firewall](https://github.com/ebongemma007/SDN-Firewall)
by Emmanuel Ebong (MIT).

The original code did not run as documented. This repository fixes three real
defects and adds the runtime harness, tests and documentation:

1. **`blocked_ips` defaulted to `10.0.0.1`** — that is `h1`'s own address, so
   every packet was dropped by the IP rule and the ICMP/port rules could never
   be observed.
2. **`OFPPacketOut` never passed `data=msg.data`** — OVS reports `n_buffers=0`,
   so packet-ins arrive with `OFP_NO_BUFFER`. Without the payload the switch had
   nothing to transmit, ARP never resolved, and the network was dead. The ping
   "passed" for entirely the wrong reason.
3. **A duplicate controller** was created by passing `controller=RemoteController`
   *and* calling `addController()`.

Also fixed: the README's `apt install python3-ryu` package does not exist in any
Ubuntu suite, and Ryu 4.34 crashes on modern eventlet (`ALREADY_HANDLED`).
See [`BUILD.md`](BUILD.md) for the full changelog.

---

## License

MIT — see [LICENSE](LICENSE). Original work © Emmanuel Ebong; modifications
© the contributors of this repository.
