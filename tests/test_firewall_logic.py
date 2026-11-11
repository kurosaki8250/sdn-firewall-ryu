"""Offline verification of firewall.py's packet decisions.

Ryu and Mininet only run on Linux, but the firewall's rules are plain Python.
This test stubs the Ryu modules so the drop/forward logic can be checked on any
OS:

    python tests/test_firewall_logic.py
"""

import logging
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


# --------------------------------------------------------------------------
# Minimal Ryu stubs
# --------------------------------------------------------------------------

class RyuApp:
    def __init__(self, *args, **kwargs):
        self.logger = logging.getLogger('firewall-test')


class Proto:
    """Stand-in for ryu.lib.packet protocol objects."""

    def __init__(self, **fields):
        self.__dict__.update(fields)


class Ethernet(Proto):
    pass


class IPv4(Proto):
    pass


class TCP(Proto):
    pass


class UDP(Proto):
    pass


class ICMP(Proto):
    pass


class Packet:
    def __init__(self, protocols=None):
        self._protocols = protocols or {}

    def get_protocol(self, cls):
        return self._protocols.get(cls.__name__)


def set_ev_cls(*args, **kwargs):
    def decorator(fn):
        return fn
    return decorator


class EventOFPSwitchFeatures:
    pass


class EventOFPPacketIn:
    pass


class FakeOfproto:
    OFPP_FLOOD = 0xFFFFFFFB
    OFPP_CONTROLLER = 0xFFFFFFFD
    OFPCML_NO_BUFFER = 0xFFFF
    OFPIT_APPLY_ACTIONS = 4
    OFP_NO_BUFFER = 0xFFFFFFFF


class FakeParser:
    def OFPActionOutput(self, port, max_len=None):
        return ('output', port)

    def OFPPacketOut(self, **kwargs):
        return ('packetout', kwargs)

    def OFPFlowMod(self, **kwargs):
        return ('flowmod', kwargs)

    def OFPMatch(self, **kwargs):
        return ('match', kwargs)

    def OFPInstructionActions(self, itype, actions):
        return ('instructions', itype, actions)


class FakeDatapath:
    ofproto = FakeOfproto()
    ofproto_parser = FakeParser()

    def __init__(self):
        self.sent = []

    def send_msg(self, msg):
        self.sent.append(msg)


class FakeMsg:
    def __init__(self, protocols, in_port=1, buffer_id=0xFFFFFFFF):
        self.data = protocols
        self.match = {'in_port': in_port}
        self.buffer_id = buffer_id
        self.datapath = FakeDatapath()


class FakeEvent:
    def __init__(self, msg):
        self.msg = msg


def _install_stubs():
    def module(name, **attrs):
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        sys.modules[name] = mod
        return mod

    module('ryu')
    module('ryu.base')
    module('ryu.base.app_manager', RyuApp=RyuApp)
    module('ryu.controller')
    module('ryu.controller.ofp_event',
           EventOFPSwitchFeatures=EventOFPSwitchFeatures,
           EventOFPPacketIn=EventOFPPacketIn)
    module('ryu.controller.handler',
           MAIN_DISPATCHER=1,
           CONFIG_DISPATCHER=2,
           set_ev_cls=set_ev_cls)
    module('ryu.ofproto')
    module('ryu.ofproto.ofproto_v1_3', OFP_VERSION=0x04)
    module('ryu.lib')
    # In real Ryu these are submodules, e.g. ryu.lib.packet.ethernet.ethernet
    module('ryu.lib.packet',
           packet=types.SimpleNamespace(Packet=Packet),
           ethernet=types.SimpleNamespace(ethernet=Ethernet),
           ipv4=types.SimpleNamespace(ipv4=IPv4),
           tcp=types.SimpleNamespace(tcp=TCP),
           udp=types.SimpleNamespace(udp=UDP),
           icmp=types.SimpleNamespace(icmp=ICMP))


_install_stubs()

import firewall  # noqa: E402  (import after stubs are installed)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def ip_packet(src='10.0.0.1', dst='10.0.0.2', proto=6, **extra):
    protocols = {
        'Ethernet': Ethernet(),
        'IPv4': IPv4(src=src, dst=dst, proto=proto),
    }
    protocols.update(extra)
    return protocols


class FirewallTestCase(unittest.TestCase):
    def setUp(self):
        self.app = firewall.AdvancedFirewall()
        self.app.logger.setLevel(logging.CRITICAL)

    def run_packet(self, protocols):
        msg = FakeMsg(protocols)
        self.app.packet_in_handler(FakeEvent(msg))
        return msg.datapath.sent

    def test_icmp_is_dropped(self):
        sent = self.run_packet(ip_packet(proto=1, ICMP=ICMP()))
        self.assertEqual(sent, [])
        self.assertEqual(self.app.dropped, 1)

    def test_blocked_tcp_port_is_dropped(self):
        sent = self.run_packet(ip_packet(TCP=TCP(src_port=50000, dst_port=80)))
        self.assertEqual(sent, [])

    def test_blocked_udp_port_is_dropped(self):
        sent = self.run_packet(ip_packet(UDP=UDP(src_port=50000, dst_port=22)))
        self.assertEqual(sent, [])

    def test_allowed_tcp_port_is_flooded(self):
        sent = self.run_packet(ip_packet(TCP=TCP(src_port=50000, dst_port=8080)))
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], 'packetout')

    def test_forwarded_packet_carries_payload_when_unbuffered(self):
        # OVS reports n_buffers=0, so the packet-out must echo msg.data or the
        # switch has nothing to transmit (this was the upstream bug).
        protocols = ip_packet(TCP=TCP(src_port=50000, dst_port=8080))
        sent = self.run_packet(protocols)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][1]['data'], protocols)

    def test_forwarded_packet_uses_buffer_id_when_buffered(self):
        msg = FakeMsg(ip_packet(TCP=TCP(src_port=50000, dst_port=8080)), buffer_id=7)
        self.app.packet_in_handler(FakeEvent(msg))
        self.assertEqual(len(msg.datapath.sent), 1)
        self.assertNotIn('data', msg.datapath.sent[0][1])

    def test_blocked_source_ip_is_dropped(self):
        self.app.blocked_ips = ['10.0.0.1']
        sent = self.run_packet(ip_packet(TCP=TCP(src_port=50000, dst_port=8080)))
        self.assertEqual(sent, [])

    def test_blocked_destination_ip_is_dropped(self):
        self.app.blocked_ips = ['10.0.0.2']
        sent = self.run_packet(ip_packet(TCP=TCP(src_port=50000, dst_port=8080)))
        self.assertEqual(sent, [])

    def test_arp_is_flooded(self):
        sent = self.run_packet({'Ethernet': Ethernet()})
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], 'packetout')

    def test_drop_counter_accumulates(self):
        for _ in range(3):
            self.run_packet(ip_packet(proto=1, ICMP=ICMP()))
        self.assertEqual(self.app.dropped, 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
