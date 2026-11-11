# Architecture and internals

This document explains how the firewall works, why it is built this way, and the
specific defects that made the original implementation non-functional.

---

## 1. What SDN changes

In a traditional network every switch forwards packets and a separate device
(or `iptables` on a host) inspects them. SDN splits the two:

| Plane | Component here | Job |
| --- | --- | --- |
| **Data plane** | Open vSwitch `s1` | Move packets, very fast, no opinions |
| **Control plane** | Ryu + `firewall.py` | Decide what is allowed |

The switch has a **flow table** and no forwarding policy of its own. When a
packet does not match a flow, the switch asks the controller. That question —
`OFPPacketIn` — is the hook this firewall uses.

The protocol between them is **OpenFlow 1.3** (`OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]`,
wire version `0x04`).

---

## 2. The topology

`sdn_topology.py` builds:

```text
h1 (10.0.0.1/24) ── s1 ── h2 (10.0.0.2/24)
                      │
                      └── c0: RemoteController 127.0.0.1:6633
```

```python
class MyTopo(Topo):
    def build(self):
        h1 = self.addHost('h1', ip='10.0.0.1/24')
        h2 = self.addHost('h2', ip='10.0.0.2/24')
        s1 = self.addSwitch('s1')
        self.addLink(h1, s1)
        self.addLink(h2, s1)
```

Two details matter:

```python
net = Mininet(topo=topo, controller=None, autoSetMacs=True)
net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6633)
net.start()
net.waitConnected()
```

- `controller=None` prevents Mininet from silently adding a *second* controller
  in addition to `c0`. The original code passed `RemoteController` **and**
  called `addController()`, producing two connections to the same Ryu instance.
- `waitConnected()` blocks until `s1` has actually attached, so tests never race
  the OpenFlow handshake.

`autoSetMacs=True` gives deterministic MAC addresses, which makes captures and
logs reproducible.

---

## 3. The OpenFlow handshake

Ryu dispatches events in phases, and the decorator's second argument selects the
phase:

| Dispatcher | Phase | Used for |
| --- | --- | --- |
| `CONFIG_DISPATCHER` | Handshake complete, switch not yet forwarding | Installing the initial flow table |
| `MAIN_DISPATCHER` | Normal operation | Handling traffic |

When `s1` connects it sends `OFPSwitchFeatures`, handled at `CONFIG_DISPATCHER`:

```python
@set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
def switch_features_handler(self, ev):
    datapath = ev.msg.datapath
    ofproto  = datapath.ofproto
    parser   = datapath.ofproto_parser

    match   = parser.OFPMatch()   # empty match = wildcard everything
    actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                      ofproto.OFPCML_NO_BUFFER)]
    self.add_flow(datapath, 0, match, actions)
```

### The table-miss rule

| Field | Value | Meaning |
| --- | --- | --- |
| `priority` | `0` | Lowest possible — anything specific wins |
| `match` | empty | Matches every packet |
| `actions` | `OFPP_CONTROLLER` | Send the packet to the controller |
| `max_len` | `OFPCML_NO_BUFFER` | Send the **whole** packet, keep no copy |

In OpenFlow 1.3 the table-miss is *defined* as the all-wildcard, priority-0
entry. This one rule is what puts the switch entirely under the controller's
control: there is no other flow, so **every** packet is punted upward.

`OFPCML_NO_BUFFER` is the detail that later explains both the drop mechanism and
the bug in section 6.

### Installing a flow

```python
def add_flow(self, datapath, priority, match, actions):
    ofproto = datapath.ofproto
    parser  = datapath.ofproto_parser

    inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
    mod  = parser.OFPFlowMod(datapath=datapath, priority=priority,
                             match=match, instructions=inst)
    datapath.send_msg(mod)
```

`OFPIT_APPLY_ACTIONS` means "execute these actions immediately" (as opposed to
`OFPIT_WRITE_ACTIONS`, which stages them for the action set).

---

## 4. Handling a packet

```python
@set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
def packet_in_handler(self, ev):
    msg      = ev.msg
    datapath = msg.datapath
    in_port  = msg.match['in_port']

    pkt = packet.Packet(msg.data)
    ip  = pkt.get_protocol(ipv4.ipv4)

    if ip:
        if ip.src in self.blocked_ips or ip.dst in self.blocked_ips:
            self.drop(f"Blocked IP packet from {ip.src} to {ip.dst}")
            return

        tcp_pkt = pkt.get_protocol(tcp.tcp)
        udp_pkt = pkt.get_protocol(udp.udp)

        if tcp_pkt and tcp_pkt.dst_port in self.blocked_ports:
            self.drop(f"Blocked TCP packet on port {tcp_pkt.dst_port} ...")
            return
        elif udp_pkt and udp_pkt.dst_port in self.blocked_ports:
            self.drop(f"Blocked UDP packet on port {udp_pkt.dst_port} ...")
            return

        if ip.proto == 1:                      # ICMP
            self.drop(f"Blocked ICMP packet from {ip.src} to {ip.dst}")
            return
```

### Why `return` is a drop

The switch was told `OFPCML_NO_BUFFER`, so it kept **no copy** of the packet —
the payload in `msg.data` is all that exists. If the controller does not send an
`OFPPacketOut`, the packet simply ceases to exist.

Silence *is* the drop. This is also why the sender sees a **timeout** rather
than a rejection: nothing replies, not even with an error.

### The rules, in evaluation order

| Order | Rule | Check |
| --- | --- | --- |
| 1 | Blocked IP | `ip.src in blocked_ips or ip.dst in blocked_ips` |
| 2 | Blocked TCP port | `tcp.dst_port in blocked_ports` |
| 3 | Blocked UDP port | `udp.dst_port in blocked_ports` |
| 4 | ICMP | `ip.proto == 1` |
| — | Otherwise | Flood |

Because the IP check tests both source *and* destination, and the ICMP check
ignores direction entirely, the policy is **bidirectional**.

---

## 5. Why ARP must be allowed

Before `h1` can send an IP packet to `10.0.0.2`, it must resolve that address to
a MAC address with **ARP**. ARP has no IPv4 header, so:

```python
ip = pkt.get_protocol(ipv4.ipv4)   # None for ARP
if ip:                             # skipped entirely
    ...
# falls through to flood
```

ARP is flooded and therefore works. That is deliberate and necessary: if ARP
were blocked, the hosts would never learn each other's MAC addresses and *every*
test would fail — including the ones that are supposed to succeed. The port-8080
success is the proof that the network is genuinely healthy.

---

## 6. The bug that made the network dead

The original forwarding path was:

```python
actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                          in_port=in_port, actions=actions)   # ← no data
datapath.send_msg(out)
```

`OFPPacketOut` says *"forward the packet identified by `buffer_id`"*. Because the
table-miss rule used `OFPCML_NO_BUFFER`, Open vSwitch does not buffer, and
`msg.buffer_id` is `OFP_NO_BUFFER` (`0xffffffff`) — *"I kept no copy, here is the
whole packet."*

So the controller asked the switch to forward a buffer that **did not exist**,
and supplied **no payload**. The switch had nothing to send. Every allowed packet
evaporated.

The correct idiom:

```python
if msg.buffer_id != ofproto.OFP_NO_BUFFER:
    out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                              in_port=in_port, actions=actions)
else:
    out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                              in_port=in_port, actions=actions, data=msg.data)
```

### Why this was so hard to see

The failure mode masqueraded as success:

| Observation | Wrong conclusion | Reality |
| --- | --- | --- |
| `ping` fails | "ICMP blocking works" | ARP never resolved, no ICMP was ever sent |
| `pingall` 100% dropped | "Firewall works" | Nothing was ever forwarded |
| No `[DROP]` lines | "Logging is broken" | The handler never saw an IP packet |

The giveaway is the **absence** of drop logs. A working firewall that blocks ICMP
*must* log the ICMP it blocked. Silence meant the packets never got that far.

`tests/test_firewall_logic.py` now asserts that the packet-out carries
`data=msg.data` when unbuffered, and omits it when a real buffer id is present.

---

## 7. Reading the demo results

```text
--- ICMP: h1 ping h2 (expect 100% packet loss) ---
2 packets transmitted, 0 received, 100% packet loss, time 1027ms

--- TCP/80: blocked port (expect http_code=000 exit=28) ---
http_code=000 exit=28

--- TCP/8080: allowed port (expect http_code=200 exit=0) ---
http_code=200 exit=0
```

| Result | Interpretation |
| --- | --- |
| `100% packet loss` | ICMP dropped by rule 4 |
| `exit=28` | curl timeout — the SYN was **silently dropped**, not rejected |
| `http_code=200` | HTTP works on an allowed port; the network is healthy |

A *closed* port returns `exit=7` (connection refused) because the kernel sends an
RST. A *filtered* port returns `exit=28` because nothing answers. The distinction
is what separates "firewall" from "broken service".

The three TCP drops are curl's SYN retries, each a separate `PacketIn`. Drop #7
(`10.0.0.2 → 10.0.0.1`) is `h2`'s ping reply attempt during `pingall`, which
confirms the rule is bidirectional.

---

## 8. From reactive to proactive (an exercise)

This implementation is **reactive**: every packet goes to the controller. That is
simple and easy to audit, but the controller becomes the bottleneck for the whole
network.

A production design installs **drop flows** so the switch discards blocked traffic
at line rate and the controller is never consulted:

```python
# Inside packet_in_handler, instead of just returning:
match = parser.OFPMatch(
    eth_type=0x0800,
    ipv4_src=ip.src, ipv4_dst=ip.dst,
    ip_proto=ip.proto,
)
self.add_flow(datapath, 100, match, [])   # empty actions = drop
return
```

The first offending packet is logged; every subsequent one is dropped by the
switch. The same pattern with a *lower* priority allows known-good flows, turning
the design into a cache.

Two things to watch when you try this:

- **Priorities must not collide.** The table-miss is `priority=0`; drop rules
  should be higher (e.g. `100`).
- **Timeouts.** Add `hard_timeout` / `idle_timeout` to `OFPFlowMod` or drop rules
  accumulate forever.

---

## 9. Quick reference

| Constant | Value | Used for |
| --- | --- | --- |
| `OFPP_CONTROLLER` | `0xfffffffd` | Send to controller |
| `OFPP_FLOOD` | `0xfffffffb` | Flood to all ports except ingress |
| `OFPCML_NO_BUFFER` | `0xffff` | Send whole packet, do not buffer |
| `OFP_NO_BUFFER` | `0xffffffff` | "No buffer id" sentinel |
| `OFPIT_APPLY_ACTIONS` | `4` | Execute actions immediately |

| Tool | Version |
| --- | --- |
| Ryu | 4.34 |
| Mininet | 2.3.0 |
| Open vSwitch | 2.17.12 |
| OpenFlow | 1.3 |
| Ubuntu | 22.04.5 LTS |
