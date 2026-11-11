# Building and running the SDN firewall

This project is two Python programs, so there is no compile step. "Building" it
means giving it the Linux runtime it needs: **Mininet** (network emulator) and
**Ryu** (OpenFlow controller).

| File | Role |
| --- | --- |
| `firewall.py` | Ryu application: inspects `PacketIn` events and drops ICMP, blocked ports, and blocked IPs |
| `sdn_topology.py` | Mininet topology: `h1` -- `s1` -- `h2`, with a remote controller on `127.0.0.1:6633` |
| `Dockerfile` | Linux image with Mininet, Open vSwitch and Ryu |
| `demo.sh` | Starts the controller, boots the topology, runs the tests |
| `run.sh` / `Run Demo.bat` | One-command launchers (WSL2/Linux and Windows) |
| `run.ps1` | Docker Desktop launcher |
| `tools/patch_ryu_wsgi.py` | Patches Ryu 4.34 for modern eventlet (run automatically) |
| `tests/test_firewall_logic.py` | Offline unit tests for the blocking rules (no Linux needed) |

## Why this cannot run natively on Windows

Mininet is not a simulator in userspace. It builds real network namespaces,
`veth` pairs, and an Open vSwitch datapath, which requires a Linux kernel and
root. Ryu itself also fails to install on current Python/Windows builds
(its `setup.py` depends on a setuptools API removed in 2020).

So pick one of the three runtimes below. **WSL2 is the most reliable option on
Windows**, because the WSL2 kernel ships the `openvswitch` module that Mininet
needs. Docker Desktop is more convenient but its kernel may not provide it.

---

## Option A - WSL2 (already installed on this machine)

Double-click **`Run Demo.bat`** in this folder, or from PowerShell:

```powershell
wsl --cd "<path to this folder>" -d Ubuntu-22.04 -- bash run.sh
```

`run.sh` installs anything missing, patches Ryu for modern eventlet, and runs
the demo.

If WSL is missing on another machine: `wsl --install -d Ubuntu-22.04`, then
reboot.

## Option B - Docker Desktop

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/)
   and make sure it is using the **Linux** container engine.
2. In PowerShell, from this folder:

   ```powershell
   .\run.ps1
   ```

That builds the image from `Dockerfile` and runs `demo.sh` inside a privileged
container. The entrypoint starts Open vSwitch and warns you if the Docker
kernel cannot provide the OVS module - in that case use Option A.

To poke around by hand instead:

```powershell
docker run --rm -it --privileged sdn-firewall bash
# inside the container:
ryu-manager firewall.py &        # terminal 1
python3 sdn_topology.py          # terminal 2 (or use tmux)
```

## Option C - native Linux

Same as Option A: `bash run.sh`.

---

## Running it by hand (any Linux runtime)

Two terminals, both from this folder:

```bash
# terminal 1
ryu-manager firewall.py

# terminal 2
sudo python3 sdn_topology.py
```

Then at the Mininet prompt:

```
mininet> h1 ping h2          # blocked by the ICMP rule
mininet> pingall             # 100% dropped
mininet> h2 python3 -m http.server 80 &
mininet> h1 curl -m 3 http://10.0.0.2/      # blocked (port 80)
mininet> h2 python3 -m http.server 8080 &
mininet> h1 curl -m 3 http://10.0.0.2:8080/ # allowed
```

Drops are printed by the controller as `[DROP #n] ...`.

---

## Expected output of `demo.sh`

```
=== 1/3  Starting Ryu controller (firewall.py) ===
    controller listening on 127.0.0.1:6633

=== 2/3  Booting topology and running tests ===
--- ICMP: h1 ping h2 (expect 100% packet loss) ---
2 packets transmitted, 0 received, 100% packet loss
--- TCP/80: blocked port (expect http_code=000 exit=28) ---
http_code=000 exit=28
--- TCP/8080: allowed port (expect http_code=200 exit=0) ---
http_code=200 exit=0
--- pingall ---
*** Results: 100% dropped (2/2 lost)

=== 3/3  Packets dropped by the controller ===
[DROP #1] Blocked ICMP packet from 10.0.0.1 to 10.0.0.2
[DROP #2] Blocked ICMP packet from 10.0.0.1 to 10.0.0.2
[DROP #3] Blocked TCP packet on port 80 from 10.0.0.1 to 10.0.0.2
...
```

`http_code=200` on port 8080 proves the network itself is healthy - only the
configured rules are blocking traffic.

---

## Tuning the rules

Edit the lists at the top of `firewall.py`, then rebuild:

```python
self.blocked_ips = []        # e.g. ['10.0.0.1']
self.blocked_ports = [22, 80]
```

```powershell
docker build -t sdn-firewall .   # or: .\run.ps1
```

---

## Changes made to the upstream code

The upstream repo did not run as documented. Fixes applied:

1. **`blocked_ips` defaulted to `10.0.0.1`**, which is `h1`'s address in the
   topology. Every packet from `h1` was dropped by the IP rule, so the ICMP and
   port rules could never be observed. The list now defaults to empty, with an
   example in a comment.
2. **Added a `drop()` helper** that counts drops and logs `[DROP #n]`, so the
   audit trail is easy to follow.
3. **`sdn_topology.py`**: hosts get explicit addresses (`10.0.0.1/24`,
   `10.0.0.2/24`), deterministic MACs, and `net.waitConnected()` so the switch
   attaches before tests start. The topology also passed `controller=None` so
   Mininet does not silently add a second, duplicate controller alongside `c0`.
4. **Install instructions**: the README's `apt install python3-ryu` does not
   exist in any Ubuntu suite. `Dockerfile` / `requirements.txt` use the pinned
   pip route that works with Ryu 4.34.
5. **Added** `Dockerfile`, `docker-entrypoint.sh`, `demo.sh`, `run.ps1`,
   `run.sh`, and this file. The original `README.md` is untouched.
6. **`firewall.py` could not forward any packet.** The `OFPPacketOut` call never
   passed `data=msg.data`. Open vSwitch reports `n_buffers=0`, so packet-ins
   always arrive with `OFP_NO_BUFFER` and the switch had nothing to transmit.
   ARP never resolved and the network was dead, which made the ping "pass" for
   the wrong reason. The handler now echoes `msg.data` when the packet is
   unbuffered.
7. **Ryu 4.34 vs eventlet 0.31+**: `ryu/app/wsgi.py` imports
   `eventlet.wsgi.ALREADY_HANDLED`, which no longer exists, so `ryu-manager`
   crashed on start. `tools/patch_ryu_wsgi.py` makes that import optional and
   is applied by `Dockerfile` and `run.sh`. (eventlet <= 0.30.2 is not an
   option: it fails to import on Python 3.10.12+.)

---

## Quick logic check (works on Windows)

The firewall's decision logic can be tested without Mininet or Ryu:

```powershell
python tests\test_firewall_logic.py
```

It stubs the Ryu modules and asserts that ICMP, blocked ports and blocked IPs
are dropped while everything else is forwarded. 10 tests, all passing.

---

## Verification status

Verified end-to-end on this machine in **WSL2 (Ubuntu 22.04.5 LTS, kernel
6.18.33.2-microsoft-standard-WSL2)**:

- `python -m py_compile firewall.py sdn_topology.py` passes.
- `python tests\test_firewall_logic.py` passes (10/10), covering the ICMP,
  port, IP and packet-forwarding paths.
- `bash run.sh` exits 0 and produces:

  | Test | Result |
  | --- | --- |
  | `h1 ping h2` | 100% packet loss (ICMP blocked) |
  | `curl :80` | `http_code=000 exit=28` (port blocked, times out) |
  | `curl :8080` | `http_code=200 exit=0` (allowed) |
  | `pingall` | 100% dropped (2/2 lost) |
  | controller log | 7 `[DROP]` entries for ICMP and TCP/80 |

The Docker route was not exercised here (Docker is not installed), but it uses
the same code, packages and patch script.
