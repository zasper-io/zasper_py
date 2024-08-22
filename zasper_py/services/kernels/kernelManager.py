from __future__ import annotations

import asyncio
import functools
import logging
import os
import re
import sys
import typing as t
import uuid
from asyncio.futures import Future
from concurrent.futures import Future as CFuture
from enum import Enum
from typing import Any, Generator, NewType, Sequence

import zmq

from zasper_py.services.kernels.connect import ConnectionFileMixin
from zasper_py.services.kernelspec.kernelSpecManager import (
    NATIVE_KERNEL_NAME, KernelSpecManager)
from zasper_py.services.provisioner.factory import \
    KernelProvisionerFactory as KPF
from zasper_py.utils import ApiPath, run_sync, to_os_path

ApiPath = NewType("ApiPath", str)


logger = logging.getLogger(__name__)

F = t.TypeVar("F", bound=t.Callable[..., t.Any])


def in_pending_state(method: F) -> F:
    """Sets the kernel to a pending state by
    creating a fresh Future for the KernelManager's `ready`
    attribute. Once the method is finished, set the Future's results.
    """

    @t.no_type_check
    @functools.wraps(method)
    async def wrapper(self: t.Any, *args: t.Any, **kwargs: t.Any) -> t.Any:
        """Create a future for the decorated method."""
        if self._attempted_start or not self._ready:
            self._ready = _get_future()
        try:
            # call wrapped method, await, and set the result or exception.
            out = await method(self, *args, **kwargs)
            # Add a small sleep to ensure tests can capture the state before done
            await asyncio.sleep(0.01)
            if self.owns_kernel:
                self._ready.set_result(None)
            return out
        except Exception as e:
            self._ready.set_exception(e)
            logger.exception(self._ready.exception())
            raise e

    return t.cast(F, wrapper)


def _get_future() -> t.Union[Future, CFuture]:
    """Get an appropriate Future object"""
    try:
        asyncio.get_running_loop()
        return Future()
    except RuntimeError:
        # No event loop running, use concurrent future
        return CFuture()


class _ShutdownStatus(Enum):
    """

    This is so far used only for testing in order to track the internal state of
    the shutdown logic, and verifying which path is taken for which
    missbehavior.

    """

    Unset = None
    ShutdownRequest = "ShutdownRequest"
    SigtermRequest = "SigtermRequest"
    SigkillRequest = "SigkillRequest"


class KernelManager(ConnectionFileMixin):
    provisioner = None
    kernel_id = None
    _kernel_spec = None
    kernel_spec_manager = None
    kernel_name: None
    cache_ports = False

    # cache_ports: Bool = Bool(
    #     False,
    #     config=True,
    #     help="True if the MultiKernelManager should cache ports for this KernelManager instance",
    # )

    def __init__(self, **kwargs: t.Any):
        """Initialize a kernel manager."""

        self._owns_kernel = kwargs.pop("owns_kernel", True)
        super().__init__(**kwargs)
        self._shutdown_status = _ShutdownStatus.Unset
        self._attempted_start = False
        self._ready = None
        self.kernel_name = NATIVE_KERNEL_NAME
        self.kernel_spec_manager = KernelSpecManager()
        self._control_socket = None
        self._restarter = None
        self.parent = kwargs['parent']

        if "config" in kwargs:
            self.connection_file = kwargs["config"]["connection_file"]

    @property
    def kernel_spec(self):
        if self._kernel_spec is None and self.kernel_name != "":
            self._kernel_spec = self.kernel_spec_manager.get_kernel_spec(
                self.kernel_name
            )
        return self._kernel_spec

    def _context_default(self) -> zmq.Context:
        self._created_context = True
        return zmq.Context()

    @property
    def ipykernel(self) -> bool:
        return self.kernel_name in {"python", "python2", "python3"}

    @property
    def owns_kernel(self) -> bool:
        return self._owns_kernel

    @property
    def has_kernel(self) -> bool:
        """Has a kernel process been started that we are actively managing."""
        return self.provisioner is not None and self.provisioner.has_process


    @property
    def ready(self) -> t.Union[CFuture, Future]:
        """A future that resolves when the kernel process has started for the first time"""
        if not self._ready:
            self._ready = _get_future()
        return self._ready

    @in_pending_state
    async def _async_start_kernel(self, **kw: t.Any) -> None:
        """Starts a kernel on this host in a separate process.

        If random ports (port=0) are being used, this method must be called
        before the channels are created.

        Parameters
        ----------
        `**kw` : optional
             keyword arguments that are passed down to build the kernel_cmd
             and launching the kernel (e.g. Popen kwargs).
        """
        self._attempted_start = True
        print("Prestarting a kernel")
        kernel_cmd, kw = await self._async_pre_start_kernel(**kw)

        # launch the kernel subprocess
        logger.info("Starting kernel: %s", kernel_cmd)
        await self._async_launch_kernel(kernel_cmd, **kw)
        await self._async_post_start_kernel(**kw)

    start_kernel = run_sync(_async_start_kernel)

    # --------------------------------------------------------------------------
    # Kernel restarter
    # --------------------------------------------------------------------------

    def start_restarter(self) -> None:
        """Start the kernel restarter."""
        pass

    def stop_restarter(self) -> None:
        """Stop the kernel restarter."""
        pass

    def add_restart_callback(self, callback: t.Callable, event: str = "restart") -> None:
        """Register a callback to be called when a kernel is restarted"""
        if self._restarter is None:
            return
        self._restarter.add_callback(callback, event)

    def remove_restart_callback(self, callback: t.Callable, event: str = "restart") -> None:
        """Unregister a callback to be called when a kernel is restarted"""
        if self._restarter is None:
            return
        self._restarter.remove_callback(callback, event)

    def _connect_control_socket(self) -> None:
        if self._control_socket is None:
            self._control_socket = self._create_connected_socket("control")
            self._control_socket.linger = 100

    def _close_control_socket(self) -> None:
        if self._control_socket is None:
            return
        self._control_socket.close()
        self._control_socket = None

    async def _async_pre_start_kernel(
        self, **kw: t.Any
    ) -> t.Tuple[t.List[str], t.Dict[str, t.Any]]:
        """Prepares a kernel for startup in a separate process.

        If random ports (port=0) are being used, this method must be called
        before the channels are created.

        Parameters
        ----------
        `**kw` : optional
             keyword arguments that are passed down to build the kernel_cmd
             and launching the kernel (e.g. Popen kwargs).
        """
        self.shutting_down = False
        self.kernel_id = self.kernel_id or kw.pop("kernel_id", str(uuid.uuid4()))
        # save kwargs for use in restart
        # assigning Traitlets Dicts to Dict make mypy unhappy but is ok
        self._launch_args = kw.copy()  # type:ignore [assignment]
        if self.provisioner is None:  # will not be None on restarts
            self.provisioner = KPF().create_provisioner_instance(
                self.kernel_id,
                self.kernel_spec,
                parent=self,
            )
        print("Provisioner is of type ", type(self.provisioner))
        kw = await self.provisioner.pre_launch(**kw)
        kernel_cmd = kw.pop("cmd")
        return kernel_cmd, kw

    pre_start_kernel = run_sync(_async_pre_start_kernel)

    async def _async_post_start_kernel(self, **kw: t.Any) -> None:
        """Performs any post startup tasks relative to the kernel.

        Parameters
        ----------
        `**kw` : optional
             keyword arguments that were used in the kernel process's launch.
        """
        self.start_restarter()
        self._connect_control_socket()
        assert self.provisioner is not None
        await self.provisioner.post_launch(**kw)

    post_start_kernel = run_sync(_async_post_start_kernel)

    async def _async_cleanup_resources(self, restart: bool = False) -> None:
        """Clean up resources when the kernel is shut down"""
        if not restart:
            self.cleanup_connection_file()

        self.cleanup_ipc_files()
        self._close_control_socket()
        self.session.parent = None

        if self._created_context and not restart:
            self.context.destroy(linger=100)

        if self.provisioner:
            await self.provisioner.cleanup(restart=restart)

    cleanup_resources = _async_cleanup_resources

    def format_kernel_cmd(
        self, extra_arguments: t.Optional[t.List[str]] = None
    ) -> t.List[str]:
        """Replace templated args (e.g. {connection_file})"""
        extra_arguments = extra_arguments or []
        assert self.kernel_spec is not None
        cmd = self.kernel_spec.argv + extra_arguments

        if cmd and cmd[0] in {
            "python",
            "python%i" % sys.version_info[0],
            "python%i.%i" % sys.version_info[:2],
        }:
            # executable is 'python' or 'python3', use sys.executable.
            # These will typically be the same,
            # but if the current process is in an env
            # and has been launched by abspath without
            # activating the env, python on PATH may not be sys.executable,
            # but it should be.
            cmd[0] = sys.executable

        # Make sure to use the realpath for the connection_file
        # On windows, when running with the store python, the connection_file path
        # is not usable by non python kernels because the path is being rerouted when
        # inside of a store app.
        # See this bug here: https://bugs.python.org/issue41196
        ns: t.Dict[str, t.Any] = {
            "connection_file": os.path.realpath(self.connection_file),
            "prefix": sys.prefix,
        }

        if self.kernel_spec:  # type:ignore[truthy-bool]
            ns["resource_dir"] = self.kernel_spec.resource_dir
        assert isinstance(self._launch_args, dict)

        ns.update(self._launch_args)

        pat = re.compile(r"\{([A-Za-z0-9_]+)\}")

        def from_ns(match: t.Any) -> t.Any:
            """Get the key out of ns if it's there, otherwise no change."""
            return ns.get(match.group(1), match.group())

        return [pat.sub(from_ns, arg) for arg in cmd]

    async def _async_launch_kernel(self, kernel_cmd: t.List[str], **kw: t.Any) -> None:
        """actually launch the kernel

        override in a subclass to launch kernel subprocesses differently
        Note that provisioners can now be used to customize kernel environments
        and
        """
        assert self.provisioner is not None
        connection_info = await self.provisioner.launch_kernel(kernel_cmd, **kw)
        assert self.provisioner.has_process
        # Provisioner provides the connection information.  Load into kernel manager
        # and write the connection file, if not already done.
        self._reconcile_connection_info(connection_info)

    _launch_kernel = run_sync(_async_launch_kernel)

    async def _async_signal_kernel(self, signum: int) -> None:
        """Sends a signal to the process group of the kernel (this
        usually includes the kernel and any subprocesses spawned by
        the kernel).

        Note that since only SIGTERM is supported on Windows, this function is
        only useful on Unix systems.
        """
        if self.has_kernel:
            assert self.provisioner is not None
            await self.provisioner.send_signal(signum)
        else:
            msg = "Cannot signal kernel. No kernel is running!"
            raise RuntimeError(msg)

    signal_kernel = run_sync(_async_signal_kernel)

    async def _async_is_alive(self) -> bool:
        """Is the kernel process still running?"""
        if not self.owns_kernel:
            return True

        if self.has_kernel:
            assert self.provisioner is not None
            ret = await self.provisioner.poll()
            if ret is None:
                return True
        return False

    is_alive = run_sync(_async_is_alive)

    async def _async_wait(self, pollinterval: float = 0.1) -> None:
        # Use busy loop at 100ms intervals, polling until the process is
        # not alive.  If we find the process is no longer alive, complete
        # its cleanup via the blocking wait().  Callers are responsible for
        # issuing calls to wait() using a timeout (see _kill_kernel()).
        while await self._async_is_alive():
            await asyncio.sleep(pollinterval)



