#!/usr/bin/env bash
# End-to-end demo of the SDN firewall.
#
#   1. starts the Ryu controller (firewall.py) on port 6633
#   2. boots the Mininet topology from sdn_topology.py
#   3. exercises the ICMP, port and IP blocking rules
#   4. prints the packets the controller dropped
#
# Must run as root, because Mininet creates network namespaces and switches.
set -u
cd "$(dirname "$0")"

if [ "$(id -u)" -ne 0 ]; then
    echo "Mininet needs root. Re-run with:  sudo $0" >&2
    exit 1
fi

LOG=/tmp/ryu-firewall.log
: >"$LOG"

# Mininet needs a running Open vSwitch. Docker's entrypoint does this too, but
# WSL2 and minimal Linux installs have no systemd to start it for us.
if ! ovs-vsctl show >/dev/null 2>&1; then
    service openvswitch-switch start >/dev/null 2>&1 || \
        ovs-ctl --system-id=random start >/dev/null 2>&1 || true
fi

echo "=== 1/3  Starting Ryu controller (firewall.py) ==="
ryu-manager --ofp-tcp-listen-port 6633 firewall.py >"$LOG" 2>&1 &
RYU_PID=$!

cleanup() {
    kill "$RYU_PID" 2>/dev/null
    wait "$RYU_PID" 2>/dev/null
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 40); do
    if (exec 3<>/dev/tcp/127.0.0.1/6633) 2>/dev/null; then
        exec 3>&-
        break
    fi
    sleep 0.5
done

if ! kill -0 "$RYU_PID" 2>/dev/null; then
    echo "Ryu failed to start. Controller log:" >&2
    cat "$LOG" >&2
    exit 1
fi
echo "    controller listening on 127.0.0.1:6633"

echo
echo "=== 2/3  Booting topology and running tests ==="
python3 sdn_topology.py <<'MININET'
h2 nohup python3 -m http.server 80 >/tmp/h2-80.log 2>&1 &
h2 nohup python3 -m http.server 8080 >/tmp/h2-8080.log 2>&1 &
h1 sleep 1
py print("\n--- ICMP: h1 ping h2 (expect 100% packet loss) ---")
h1 ping -c 2 -W 1 10.0.0.2
py print("\n--- TCP/80: blocked port (expect http_code=000 exit=28) ---")
h1 curl -s -m 3 -o /dev/null -w "http_code=%{http_code} exit=%{exitcode}\n" http://10.0.0.2/
py print("\n--- TCP/8080: allowed port (expect http_code=200 exit=0) ---")
h1 curl -s -m 3 -o /dev/null -w "http_code=%{http_code} exit=%{exitcode}\n" http://10.0.0.2:8080/
py print("\n--- pingall ---")
pingall
exit
MININET

echo
echo "=== 3/3  Packets dropped by the controller ==="
if grep -qF '[DROP' "$LOG"; then
    grep -F '[DROP' "$LOG" | sed 's/^.*\[DROP/[DROP/'
else
    echo "    (no drops logged)"
fi
echo
echo "Full controller log: $LOG"
