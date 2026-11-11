#!/usr/bin/env bash
# Native Linux / WSL2 launcher (no Docker).
# Installs Mininet + Ryu if they are missing, then runs the demo.
set -euo pipefail
cd "$(dirname "$0")"

if [ "$(id -u)" -eq 0 ]; then
    echo "Run this script as a normal user; it calls sudo where needed." >&2
    exit 1
fi

need=()
command -v mn >/dev/null 2>&1 || need+=(mininet openvswitch-switch)
command -v ryu-manager >/dev/null 2>&1 || need+=(python3-pip python3-distutils)

if [ ${#need[@]} -gt 0 ]; then
    echo "Installing: ${need[*]}"
    sudo apt-get update
    sudo apt-get install -y "${need[@]}" curl
fi

if ! command -v ryu-manager >/dev/null 2>&1; then
    echo "Installing Ryu 4.34 (pinned setuptools, eventlet and dnspython)"
    sudo -H python3 -m pip install "setuptools<58" "pbr==5.11.1" wheel
    sudo -H python3 -m pip install --no-build-isolation \
        "ryu==4.34" "eventlet==0.33.3" "dnspython==2.1.0"
fi

# Ryu 4.34 imports an eventlet API that was removed in eventlet 0.31.
# Idempotent, so it is safe to run on every launch.
sudo python3 tools/patch_ryu_wsgi.py

sudo bash demo.sh
