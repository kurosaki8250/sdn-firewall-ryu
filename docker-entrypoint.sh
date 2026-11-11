#!/usr/bin/env bash
# Bring up Open vSwitch before handing control to the requested command.
# Mininet needs a working OVS datapath; in a container that requires
# --privileged and a kernel that provides the openvswitch module.
set -e

if ! ovs-vsctl show >/dev/null 2>&1; then
    modprobe openvswitch 2>/dev/null || true
    service openvswitch-switch start >/dev/null 2>&1 || true
fi

if ! ovs-vsctl show >/dev/null 2>&1; then
    ovs-ctl --system-id=random start >/dev/null 2>&1 || true
fi

if ! ovs-vsctl show >/dev/null 2>&1; then
    echo "WARNING: Open vSwitch did not start." >&2
    echo "Docker Desktop's kernel may not provide the 'openvswitch' module." >&2
    echo "If Mininet fails below, use the WSL2 route instead - see BUILD.md." >&2
fi

exec "$@"
