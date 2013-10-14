from fabric.state import env, default_channel
from fabric.network import needs_host

import pushy
import pushy.transport
from pushy.transport.ssh import WrappedChannelFile

class FabricPopen(pushy.transport.BaseTransport):
    """
    Pushy transport for Fabric, piggy-backing the Paramiko SSH connection
    managed by Fabric.
    """

    def __init__(self, command, address):
        pushy.transport.BaseTransport.__init__(self, address)

        # Join arguments into a string
        args = command
        for i in range(len(args)):
            if " " in args[i]:
                args[i] = "'%s'" % args[i]
        command = " ".join(args)

        self.__channel = default_channel()
        self.__channel.exec_command(command)
        self.stdin  = WrappedChannelFile(self.__channel.makefile("wb"), 1)
        self.stdout = WrappedChannelFile(self.__channel.makefile("rb"), 0)
        self.stderr = self.__channel.makefile_stderr("rb")

    def __del__(self):
        self.close()

    def close(self):
        if hasattr(self, "stdin"):
            self.stdin.close()
            self.stdout.close()
            self.stderr.close()
        self.__channel.close()

# Add a "fabric" transport", which piggy-backs the existing SSH connection, but
# otherwise operates the same way as the built-in Paramiko transport.
class pseudo_module:
    Popen = FabricPopen
pushy.transports["fabric"] = pseudo_module

###############################################################################

# Pushy connection cache
connections = {}

@needs_host
def remote_import(name, python="python"):
    """
    A Fabric operation for importing and returning a reference to a remote
    Python package.
    """

    if (env.host_string, python) in connections:
        conn = connections[(env.host_string, python)]
    else:
        conn = pushy.connect("fabric:", python=python)
        connections[(env.host_string, python)] = conn
    m = getattr(conn.modules, name)
    if "." in name:
        for p in name.split(".")[1:]:
            m = getattr(m, p)
    return m