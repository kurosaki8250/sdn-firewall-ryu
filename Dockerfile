FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

# Mininet + Open vSwitch, plus the tools the demo uses inside the hosts.
RUN apt-get update && apt-get install -y --no-install-recommends \
        mininet \
        openvswitch-switch \
        iproute2 \
        iputils-ping \
        netcat-openbsd \
        curl \
        procps \
        ca-certificates \
        python3 \
        python3-pip \
        python3-distutils \
    && rm -rf /var/lib/apt/lists/*

# Ryu 4.34's setup.py still calls setuptools' easy_install API, which was
# removed in setuptools 58. Building it with an older setuptools is the
# supported workaround. eventlet is pinned to a version Ryu 4.34 is known to
# work with.
RUN python3 -m pip install --no-cache-dir "setuptools<58" "pbr==5.11.1" wheel \
    && python3 -m pip install --no-cache-dir --no-build-isolation \
        "ryu==4.34" "eventlet==0.33.3" "dnspython==2.1.0"

WORKDIR /app
COPY firewall.py sdn_topology.py docker-entrypoint.sh demo.sh ./
COPY tools/patch_ryu_wsgi.py ./tools/
RUN sed -i 's/\r$//' ./*.sh && chmod +x ./*.sh \
    && python3 tools/patch_ryu_wsgi.py

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["bash"]
