from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.cli import CLI
from mininet.log import setLogLevel, info


class MyTopo(Topo):
    def build(self):
        # Add hosts
        h1 = self.addHost('h1', ip='10.0.0.1/24')
        h2 = self.addHost('h2', ip='10.0.0.2/24')

        # Add a switch
        s1 = self.addSwitch('s1')

        # Add links between hosts and switch
        self.addLink(h1, s1)
        self.addLink(h2, s1)


if __name__ == '__main__':
    setLogLevel('info')
    topo = MyTopo()

    # Initialize Mininet with the custom topology. The controller is added
    # explicitly below, so pass controller=None to avoid a duplicate default.
    net = Mininet(topo=topo, controller=None, autoSetMacs=True)

    # Add the controller (assuming it's running on localhost)
    net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6633)

    # Start the network
    net.start()
    net.waitConnected()
    info('*** Running CLI\n')
    CLI(net)

    # Stop the network
    net.stop()
