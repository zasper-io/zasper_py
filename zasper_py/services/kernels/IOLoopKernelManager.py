import typing as t

import zmq
from tornado.ioloop import IOLoop
from zmq.eventloop.zmqstream import ZMQStream

from zasper_py.services.kernels.kernelManager import KernelManager
from zasper_py.services.kernels.restarter import IOLoopKernelRestarter


def as_zmqstream(f: t.Any) -> t.Callable:
    """Convert a socket to a zmq stream."""

    def wrapped(self: t.Any, *args: t.Any, **kwargs: t.Any) -> t.Any:
        save_socket_class = None
        # zmqstreams only support sync sockets
        if self.context._socket_class is not zmq.Socket:
            save_socket_class = self.context._socket_class
            self.context._socket_class = zmq.Socket
        try:
            socket = f(self, *args, **kwargs)
        finally:
            if save_socket_class:
                # restore default socket class
                self.context._socket_class = save_socket_class
        return ZMQStream(socket, self.loop)

    return wrapped


class IOLoopKernelManager(KernelManager):
    """An io loop kernel manager."""

    loop = IOLoop.current()
    # Instance("tornado.ioloop.IOLoop")

    restarter_class = IOLoopKernelRestarter

    # _restarter = "jupyter_client.ioloop.IOLoopKernelRestarter"

    def __init__(self, **kwargs: t.Any):
        super().__init__(**kwargs)
        self.autorestart = True
        self.parent = kwargs['parent']

    def start_restarter(self) -> None:
        """Start the restarter."""
        self._restarter = IOLoopKernelRestarter(
            kernel_manager=self, loop=self.loop, parent=self
        )
        # if self.autorestart and self.has_kernel:
        #     if self._restarter is None:
        #         self._restarter = IOLoopKernelRestarter(
        #             kernel_manager=self, loop=self.loop, parent=self
        #         )
        self._restarter.start()

    def stop_restarter(self) -> None:
        """Stop the restarter."""
        if self.autorestart and self._restarter is not None:
            self._restarter.stop()

    connect_shell = as_zmqstream(KernelManager.connect_shell)
    connect_control = as_zmqstream(KernelManager.connect_control)
    connect_iopub = as_zmqstream(KernelManager.connect_iopub)
    connect_stdin = as_zmqstream(KernelManager.connect_stdin)
    connect_hb = as_zmqstream(KernelManager.connect_hb)
