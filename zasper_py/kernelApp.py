"""An application to launch a kernel by name in a local subprocess."""

import os
import signal
import typing as t
import uuid

from tornado.ioloop import IOLoop

from zasper_backend._version import __version__
from zasper_backend.core.paths import jupyter_runtime_dir
from zasper_backend.services.kernels.kernelManager import KernelManager
from zasper_backend.services.kernelspec.kernelSpecManager import \
    KernelSpecManager

# from .kernelspec import NATIVE_KERNEL_NAME, KernelSpecManager


class KernelApp:
    """Launch a kernel by name in a local subprocess."""

    version = __version__
    description = "Run a kernel locally in a subprocess"

    classes = [KernelManager, KernelSpecManager]

    aliases = {
        "kernel": "KernelApp.kernel_name",
        "ip": "KernelManager.ip",
    }
    # flags = {"debug": base_flags["debug"]}

    kernel_name = ""  # NATIVE_KERNEL_NAME

    def __init__(self, argv: t.Union[str, t.Sequence[str], None] = None) -> None:
        """Initialize the application."""

        cf_basename = "kernel-%s.json" % uuid.uuid4()
        self.runtime_dir = jupyter_runtime_dir()
        config = {"connection_file": os.path.join(self.runtime_dir, cf_basename)}
        self.km = KernelManager(kernel_name=self.kernel_name, config=config)

        self.loop = IOLoop.current()
        self.loop.add_callback(self._record_started)

    def setup_signals(self) -> None:
        """Shutdown on SIGTERM or SIGINT (Ctrl-C)"""
        if os.name == "nt":
            return

        def shutdown_handler(signo: int, frame: t.Any) -> None:
            self.loop.add_callback_from_signal(self.shutdown, signo)

        for sig in [signal.SIGTERM, signal.SIGINT]:
            signal.signal(sig, shutdown_handler)

    def shutdown(self, signo: int) -> None:
        """Shut down the application."""
        print("Shutting down on signal %d", signo)
        self.km.shutdown_kernel()
        self.loop.stop()

    def log_connection_info(self) -> None:
        """Log the connection info for the kernel."""
        cf = self.km.connection_file
        print("Connection file: %s", cf)
        print("To connect a client: --existing %s", os.path.basename(cf))

    def _record_started(self) -> None:
        """For tests, create a file to indicate that we've started

        Do not rely on this except in our own tests!
        """
        fn = os.environ.get("JUPYTER_CLIENT_TEST_RECORD_STARTUP_PRIVATE")
        if fn is not None:
            with open(fn, "wb"):
                pass

    def start(self) -> None:
        """Start the application."""
        print("Starting kernel %r", self.kernel_name)
        try:
            self.km.start_kernel()
            self.log_connection_info()
            self.setup_signals()
            self.loop.start()
        finally:
            self.km.cleanup_resources()


if __name__ == "__main__":
    ka = KernelApp()
    ka.start()
