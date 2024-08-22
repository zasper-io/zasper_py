# https://github.com/jupyter/jupyter_client/blob/main/jupyter_client/multikernelmanager.py
# https://github.com/jupyter-server/jupyter_server/blob/main/jupyter_server/services/kernels/kernelmanager.py => mapped kernel
from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
import typing as t
import uuid
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from functools import wraps, partial

import zmq
from tornado import web
from tornado.ioloop import IOLoop, PeriodicCallback

from zasper_backend.services.kernels.IOLoopKernelManager import \
    IOLoopKernelManager
from zasper_backend.services.kernels.kernelManager import KernelManager
from zasper_backend.services.kernels.session import Session
from zasper_backend.services.kernelspec.kernelSpecManager import \
    KernelSpecManager
from zasper_backend.services.metrics.metrics import \
    KERNEL_CURRENTLY_RUNNING_TOTAL
from zasper_backend.utils import ApiPath, to_os_path, ensure_async
from zasper_backend.utils.timeUtils import utcnow

logger = logging.getLogger(__name__)


def isoformat(dt: datetime) -> str:
    """Return iso-formatted timestamp

    Like .isoformat(), but uses Z for UTC instead of +00:00
    """
    return dt.isoformat().replace("+00:00", "Z")


class DuplicateKernelError(Exception):
    pass


def kernel_method(f: t.Callable) -> t.Callable:
    """decorator for proxying MKM.method(kernel_id) to individual KMs by ID"""

    @wraps(f)
    def wrapped(
            self: t.Any, kernel_id: str, *args: t.Any, **kwargs: t.Any
    ) -> t.Callable | t.Awaitable:
        # get the kernel
        km = self.get_kernel(kernel_id)
        print("In wrapped, km is ", km)
        method = getattr(km, f.__name__)
        # call the kernel's method
        r = method(*args, **kwargs)
        # last thing, call anything defined in the actual class method
        # such as logging messages
        f(self, kernel_id, *args, **kwargs)
        # return the method result
        return r

    return wrapped


NATIVE_KERNEL_NAME = "python3"


class MultiKernelManager:
    context = None
    _kernel_connections = {}
    _kernels = {}
    _pending_kernels = {}
    connection_dir = ""
    external_connection_dir = None
    shared_context = False
    default_kernel_name = NATIVE_KERNEL_NAME
    _kernel_buffers = None
    allow_tracebacks = True

    # from the client
    cull_interval_default = 300  # 5 minutes
    cull_interval = cull_interval_default

    cull_connected = False

    cull_busy = False


    buffer_offline_messages = True
    kernel_info_timeout = 60

    allowed_message_types = []

    # @default("_kernel_buffers")
    def _default_kernel_buffers(self):
        return defaultdict(lambda: {"buffer": [], "session_key": "", "channels": {}})

    def _context_default(self) -> zmq.Context:
        self._created_context = True
        return zmq.Context()

    def new_kernel_id(self, **kwargs: t.Any) -> str:
        """
        Returns the id to associate with the kernel for this request. Subclasses may override
        this method to substitute other sources of kernel ids.
        :param kwargs:
        :return: string-ized version 4 uuid
        """
        return str(uuid.uuid4())

    def __init__(self):
        # self.kernel_manager_factory = self._create_kernel_manager_factory()
        self.kernel_manager = None
        self._pending_kernel_tasks = {}
        self.root_dir = self._default_root_dir()
        self.kernel_spec_manager = KernelSpecManager()
        self._kernel_ports = {}
        self.use_pending_kernels = True
        self._initialized_culler = False
        self.cull_idle_timeout = 0
        self._culler_callback = None
        self.cull_interval_default = 300
        self.cull_connected = False
        self.cull_busy = False
        self._kernel_buffers = self._default_kernel_buffers()

    def _default_root_dir(self):
        return os.getcwd()
        # if not self.parent:
        #     return os.getcwd()
        # return self.parent.root_dir

    def create_kernel_manager(self, *args: t.Any, **kwargs: t.Any) -> KernelManager:
        if self.shared_context:
            if self.context.closed:
                # recreate context if closed
                self.context = self._context_default()
            kwargs.setdefault("context", self.context)
        return KernelManager(*args, **kwargs)

    def pre_start_kernel(
            self, kernel_name: str | None, kwargs: t.Any
    ) -> tuple[KernelManager, str, str]:
        # kwargs should be mutable, passing it as a dict argument.
        kernel_id = kwargs.pop("kernel_id", self.new_kernel_id(**kwargs))
        if kernel_id in self:
            raise DuplicateKernelError("Kernel already exists: %s" % kernel_id)

        if kernel_name is None:
            kernel_name = self.default_kernel_name
        # kernel_manager_factory is the constructor for the KernelManager
        # subclass we are using. It can be configured as any Configurable,
        # including things like its transport and ip.
        constructor_kwargs = {}
        if self.kernel_spec_manager:
            constructor_kwargs["kernel_spec_manager"] = self.kernel_spec_manager
        km = IOLoopKernelManager(
            connection_file=os.path.join(
                self.connection_dir, "kernel-%s.json" % kernel_id
            ),
            parent=self,
            kernel_name=kernel_name,
            **constructor_kwargs,
        )
        logger.info(km)
        return km, kernel_name, kernel_id

    # Implemetation of MappingKernelManager
    async def _async_start_kernel(  # type:ignore[override]
            self,
            *,
            kernel_id: str | None = None,
            path: ApiPath | None = None,
            **kwargs: str,
    ) -> str:
        """Start a kernel for a session and return its kernel_id.

        Parameters
        ----------
        kernel_id : uuid (str)
            The uuid to associate the new kernel with. If this
            is not None, this kernel will be persistent whenever it is
            requested.
        path : API path
            The API path (unicode, '/' delimited) for the cwd.
            Will be transformed to an OS path relative to root_dir.
        kernel_name : str
            The name identifying which kernel spec to launch. This is ignored if
            an existing kernel is returned, but it may be checked in the future.
        """
        if kernel_id is None or kernel_id not in self:
            if path is not None:
                kwargs["cwd"] = self.cwd_for_path(path, env=kwargs.get("env", {}))
            if kernel_id is not None:
                assert kernel_id is not None, "Never Fail, but necessary for mypy "
                kwargs["kernel_id"] = kernel_id
            kernel_id = await self.multikm_async_start_kernel(**kwargs)
            self._kernel_connections[kernel_id] = 0

            task = asyncio.create_task(self._finish_kernel_start(kernel_id))
            if not getattr(self, "use_pending_kernels", None):
                await task
            else:
                self._pending_kernel_tasks[kernel_id] = task
            # add busy/activity markers:
            kernel = self.get_kernel(kernel_id)
            kernel.execution_state = "starting"  # type:ignore[attr-defined]
            kernel.reason = ""  # type:ignore[attr-defined]
            kernel.last_activity = utcnow()  # type:ignore[attr-defined]
            logger.info("Kernel started: %s", kernel_id)
            logger.debug("Kernel args: %r", kwargs)

            # Increase the metric of number of kernels running
            # for the relevant kernel type by 1
            KERNEL_CURRENTLY_RUNNING_TOTAL.labels(
                type=self._kernels[kernel_id].kernel_name
            ).inc()

        else:
            self.log.info("Using existing kernel: %s", kernel_id)

        # Initialize culling if not already
        if not self._initialized_culler:
            self.initialize_culler()
        assert kernel_id is not None
        return kernel_id

    def notify_connect(self, kernel_id):
        """Notice a new connection to a kernel"""
        if kernel_id in self._kernel_connections:
            self._kernel_connections[kernel_id] += 1

    def notify_disconnect(self, kernel_id):
        """Notice a disconnection from a kernel"""
        if kernel_id in self._kernel_connections:
            self._kernel_connections[kernel_id] -= 1

    # THe below one is implementation from MultiKernelManager
    async def multikm_async_start_kernel(
            self, *, kernel_name: str | None = None, **kwargs: t.Any
    ) -> str:
        """Start a new kernel.

        The caller can pick a kernel_id by passing one in as a keyword arg,
        otherwise one will be generated using new_kernel_id().

        The kernel ID for the newly started kernel is returned.
        """
        logger.info("Running inside Async start kernel ")
        km, kernel_name, kernel_id = self.pre_start_kernel(kernel_name, kwargs)
        # logger.info("km =>", km)
        if not isinstance(km, KernelManager):
            logger.warning(  # type:ignore[unreachable]
                "Kernel manager class ({km_class}) is not an instance of 'KernelManager'!".format(
                    km_class=self.kernel_manager_class.__class__
                )
            )
        kwargs["kernel_id"] = (
            kernel_id  # Make kernel_id available to manager and provisioner
        )

        starter = km.start_kernel(**kwargs)
        logging.info("adding kernel to _kernels dicts")
        print("_kernel_connections => ", self._kernel_connections)
        print("pending kernel => ", self._pending_kernels)
        task = asyncio.create_task(self._add_kernel_when_ready(kernel_id, km, starter))
        self._pending_kernels[kernel_id] = task
        # Handling a Pending Kernel
        # self._kernels[kernel_id] = km
        # """
        # TODO      TODO     TODO
        # TODO      TODO     TODO
        # TODO      TODO     TODO
        # TODO      TODO     TODO
        # """
        if self._using_pending_kernels():
            # If using pending kernels, do not block
            # on the kernel start.
            self._kernels[kernel_id] = km
        else:
            await task
            # raise an exception if one occurred during kernel startup.
            # if km.ready.exception():
            #     raise km.ready.exception()  # type: ignore[misc]
        # logger.info("_kernels => ", self._kernels)
        # logger.info("_pending_kernels => ", self._pending_kernels)
        return kernel_id

    start_kernel = _async_start_kernel

    def _using_pending_kernels(self) -> bool:
        """Returns a boolean; a clearer method for determining if
        this multikernelmanager is using pending kernels or not
        """
        return getattr(self, "use_pending_kernels", False)

    def _create_kernel_manager_factory(self) -> t.Callable:
        kernel_manager_ctor = IOLoopKernelManager

        def create_kernel_manager(*args: t.Any, **kwargs: t.Any) -> KernelManager:
            if self.shared_context:
                if self.context.closed:
                    # recreate context if closed
                    self.context = self._context_default()
                kwargs.setdefault("context", self.context)
            km = kernel_manager_ctor(*args, **kwargs)
            return km

        return create_kernel_manager

    def _handle_kernel_died(self, kernel_id):
        """notice that a kernel died"""
        logger.warning("Kernel %s died, removing from map.", kernel_id)
        self.remove_kernel(kernel_id)

    def cwd_for_path(self, path, **kwargs):
        """Turn API path into absolute OS path."""
        os_path = to_os_path(path, self.root_dir)
        # in the case of documents and kernels not being on the same filesystem,
        # walk up to root_dir if the paths don't exist
        while not os.path.isdir(os_path) and os_path != self.root_dir:
            os_path = os.path.dirname(os_path)
        return os_path

    def _check_kernel_id(self, kernel_id: str) -> None:
        """check that a kernel id is valid"""
        if kernel_id not in self:
            raise KeyError("Kernel with id not found: %s" % kernel_id)

    def get_kernel(self, kernel_id: str) -> KernelManager:
        """Get the single KernelManager object for a kernel by its uuid.

        Parameters
        ==========
        kernel_id : uuid
            The id of the kernel.
        """
        self._check_kernel_id(kernel_id)
        return self._kernels[kernel_id]

    async def _finish_kernel_start(self, kernel_id):
        """Handle a kernel that finishes starting."""
        km = self.get_kernel(kernel_id)
        if hasattr(km, "ready"):
            ready = km.ready
            if not isinstance(ready, asyncio.Future):
                ready = asyncio.wrap_future(ready)
            try:
                await ready
            except Exception:
                self.log.exception("Error waiting for kernel manager ready")
                return

        self._kernel_ports[kernel_id] = km.ports
        self.start_watching_activity(kernel_id)
        # register callback for failed auto-restart
        self.add_restart_callback(
            kernel_id,
            lambda: self._handle_kernel_died(kernel_id),
            "dead",
        )

    @kernel_method
    def add_restart_callback(
            self, kernel_id: str, callback: t.Callable, event: str = "restart"
    ) -> None:
        """add a callback for the KernelRestarter"""

    @kernel_method
    def remove_restart_callback(
            self, kernel_id: str, callback: t.Callable, event: str = "restart"
    ) -> None:
        """remove a callback for the KernelRestarter"""

    @kernel_method
    def connect_shell(  # type:ignore[empty-body]
            self, kernel_id: str, identity: bytes | None = None
    ) -> socket.socket:
        """Return a zmq Socket connected to the shell channel.

        Parameters
        ==========
        kernel_id : uuid
            The id of the kernel
        identity : bytes (optional)
            The zmq identity of the socket

        Returns
        =======
        stream : zmq Socket or ZMQStream
        """

    async def prepare(self):
        """Prepare a kernel connection."""
        # check session collision:
        await self._register_session()
        # then request kernel info, waiting up to a certain time before giving up.
        # We don't want to wait forever, because browsers don't take it well when
        # servers never respond to websocket connection requests.

        if hasattr(self.kernel_manager, "ready"):
            ready = self.kernel_manager.ready
            if not isinstance(ready, asyncio.Future):
                ready = asyncio.wrap_future(ready)
            try:
                await ready
            except Exception as e:
                self.kernel_manager.execution_state = "dead"
                self.kernel_manager.reason = str(e)
                raise web.HTTPError(500, str(e)) from e

        t0 = time.time()
        while not await self.kernel_manager.is_alive():
            await asyncio.sleep(0.1)
            if (time.time() - t0) > self.kernel_info_timeout:
                msg = "Kernel never reached an 'alive' state."
                raise TimeoutError(msg)

        self.session.key = self.kernel_manager.session.key
        future = self.request_kernel_info()

    def start_watching_activity(self, kernel_id):
        """Start watching IOPub messages on a kernel for activity.

        - update last_activity on every message
        - record execution_state from status messages
        """
        kernel = self._kernels[kernel_id]
        # add busy/activity markers:
        kernel.execution_state = "starting"
        kernel.reason = ""
        kernel.last_activity = utcnow()
        kernel._activity_stream = kernel.connect_iopub()
        print("kernel is =================>")
        print("kernel is =================>")
        print(kernel)
        session = Session(
            config=kernel.session.config,
            key=kernel.session.key,
        )

        def record_activity(msg_list):
            """Record an IOPub message arriving from a kernel"""
            self.last_kernel_activity = kernel.last_activity = utcnow()

            idents, fed_msg_list = session.feed_identities(msg_list)
            msg = session.deserialize(fed_msg_list, content=False)

            msg_type = msg["header"]["msg_type"]
            if msg_type == "status":
                msg = session.deserialize(fed_msg_list)
                kernel.execution_state = msg["content"]["execution_state"]
                logger.debug(
                    "activity on %s: %s (%s)",
                    kernel_id,
                    msg_type,
                    kernel.execution_state,
                )
            else:
                logger.debug("activity on %s: %s", kernel_id, msg_type)

        kernel._activity_stream.on_recv(record_activity)

    def kernel_model(self, kernel_id):
        """Return a JSON-safe dict representing a kernel

        For use in representing kernels in the JSON APIs.
        """
        self._check_kernel_id(kernel_id)
        kernel = self._kernels[kernel_id]

        model = {
            "id": kernel_id,
            "name": kernel.kernel_name,
            "last_activity": isoformat(kernel.last_activity),
            "execution_state": kernel.execution_state,
            "connections": self._kernel_connections.get(kernel_id, 0),
        }
        if getattr(kernel, "reason", None):
            model["reason"] = kernel.reason
        return model

    def update_env(self, *, kernel_id: str, env: t.Dict[str, str]) -> None:
        """
        Allow to update the environment of the given kernel.

        Forward the update env request to the corresponding kernel.

        .. version-added: 8.5
        """
        if kernel_id in self:
            self._kernels[kernel_id].update_env(env=env)

    async def _add_kernel_when_ready(
            self, kernel_id: str, km: KernelManager, kernel_awaitable: t.Awaitable
    ) -> None:
        print("Adding kernel when ready!!!!")
        try:
            await kernel_awaitable
            self._kernels[kernel_id] = km
            print("self.kernels ===>", self._kernels)
            self._pending_kernels.pop(kernel_id, None)
        except Exception as e:
            logger.info(e)

    async def _remove_kernel_when_ready(
            self, kernel_id: str, kernel_awaitable: t.Awaitable
    ) -> None:
        try:
            await kernel_awaitable
            self.remove_kernel(kernel_id)
            self._pending_kernels.pop(kernel_id, None)
        except Exception as e:
            # self.log.exception(e)
            logger.info(e)

    def list_kernels(self):
        """Returns a list of kernel_id's of kernels running."""
        kernels = []
        kernel_ids = self.list_kernel_ids()
        for kernel_id in kernel_ids:
            try:
                model = self.kernel_model(kernel_id)
                kernels.append(model)
            except (web.HTTPError, KeyError):
                # Probably due to a (now) non-existent kernel, continue building the list
                pass
        return kernels

    def __len__(self) -> int:
        """Return the number of running kernels."""
        return len(self.list_kernel_ids())

    def __contains__(self, kernel_id: str) -> bool:
        return kernel_id in self._kernels

    def list_kernel_ids(self) -> list[str]:
        """Return a list of the kernel ids of the active kernels."""
        if self.external_connection_dir is not None:
            external_connection_dir = Path(self.external_connection_dir)
            if external_connection_dir.is_dir():
                connection_files = [
                    p for p in external_connection_dir.iterdir() if p.is_file()
                ]

                # remove kernels (whose connection file has disappeared) from our list
                k = list(self.kernel_id_to_connection_file.keys())
                v = list(self.kernel_id_to_connection_file.values())
                for connection_file in list(self.kernel_id_to_connection_file.values()):
                    if connection_file not in connection_files:
                        kernel_id = k[v.index(connection_file)]
                        del self.kernel_id_to_connection_file[kernel_id]
                        del self._kernels[kernel_id]

                # add kernels (whose connection file appeared) to our list
                for connection_file in connection_files:
                    if connection_file in self.kernel_id_to_connection_file.values():
                        continue
                    try:
                        connection_info: KernelConnectionInfo = json.loads(
                            connection_file.read_text()
                        )
                    except Exception:  # noqa: S112
                        continue
                    self.log.debug("Loading connection file %s", connection_file)
                    if not (
                            "kernel_name" in connection_info and "key" in connection_info
                    ):
                        continue
                    # it looks like a connection file
                    kernel_id = self.new_kernel_id()
                    self.kernel_id_to_connection_file[kernel_id] = connection_file
                    km = self.kernel_manager_factory(
                        parent=self,
                        log=self.log,
                        owns_kernel=False,
                    )
                    km.load_connection_info(connection_info)
                    km.last_activity = utcnow()
                    km.execution_state = "idle"
                    km.connections = 1
                    km.kernel_id = kernel_id
                    km.kernel_name = connection_info["kernel_name"]
                    km.ready.set_result(None)

                    self._kernels[kernel_id] = km

        # Create a copy so we can iterate over kernels in operations
        # that delete keys.
        return list(self._kernels.keys())

    def remove_kernel(self, kernel_id: str) -> KernelManager:
        """remove a kernel from our mapping.

        Mainly so that a kernel can be removed if it is already dead,
        without having to call shutdown_kernel.

        The kernel object is returned, or `None` if not found.
        """
        return self._kernels.pop(kernel_id, None)

    """
    culler
    """

    async def cull_kernels(self):
        """Handle culling kernels."""
        logger.debug(
            "Polling every %s seconds for kernels idle > %s seconds...",
            self.cull_interval,
            self.cull_idle_timeout,
        )
        """Create a separate list of kernels to avoid conflicting updates while iterating"""
        for kernel_id in list(self._kernels):
            try:
                await self.cull_kernel_if_idle(kernel_id)
            except Exception as e:
                logger.exception(
                    "The following exception was encountered while checking the idle duration of kernel %s: %s",
                    kernel_id,
                    e,
                )

    async def cull_kernel_if_idle(self, kernel_id):
        """Cull a kernel if it is idle."""
        kernel = self._kernels[kernel_id]

        if getattr(kernel, "execution_state", None) == "dead":
            self.log.warning(
                "Culling '%s' dead kernel '%s' (%s).",
                kernel.execution_state,
                kernel.kernel_name,
                kernel_id,
            )
            await ensure_async(self.shutdown_kernel(kernel_id))
            return

        kernel_spec_metadata = kernel.kernel_spec.metadata
        cull_idle_timeout = kernel_spec_metadata.get("cull_idle_timeout", self.cull_idle_timeout)

        if hasattr(
                kernel, "last_activity"
        ):  # last_activity is monkey-patched, so ensure that has occurred
            self.log.debug(
                "kernel_id=%s, kernel_name=%s, last_activity=%s",
                kernel_id,
                kernel.kernel_name,
                kernel.last_activity,
            )
            dt_now = utcnow()
            dt_idle = dt_now - kernel.last_activity
            # Compute idle properties
            is_idle_time = dt_idle > timedelta(seconds=cull_idle_timeout)
            is_idle_execute = self.cull_busy or (kernel.execution_state != "busy")
            connections = self._kernel_connections.get(kernel_id, 0)
            is_idle_connected = self.cull_connected or not connections
            # Cull the kernel if all three criteria are met
            if is_idle_time and is_idle_execute and is_idle_connected:
                idle_duration = int(dt_idle.total_seconds())
                self.log.warning(
                    "Culling '%s' kernel '%s' (%s) with %d connections due to %s seconds of inactivity.",
                    kernel.execution_state,
                    kernel.kernel_name,
                    kernel_id,
                    connections,
                    idle_duration,
                )
                await ensure_async(self.shutdown_kernel(kernel_id))

    def initialize_culler(self):
        """Start idle culler if 'cull_idle_timeout' is greater than zero.

        Regardless of that value, set flag that we've been here.
        """
        if (
                not self._initialized_culler
                and self.cull_idle_timeout > 0
                and self._culler_callback is None
        ):
            _ = IOLoop.current()
            if self.cull_interval <= 0:  # handle case where user set invalid value
                self.log.warning(
                    "Invalid value for 'cull_interval' detected (%s) - using default value (%s).",
                    self.cull_interval,
                    self.cull_interval_default,
                )
                self.cull_interval = self.cull_interval_default
            self._culler_callback = PeriodicCallback(self.cull_kernels, 1000 * self.cull_interval)
            logger.info(
                "Culling kernels with idle durations > %s seconds at %s second intervals ...",
                self.cull_idle_timeout,
                self.cull_interval,
            )
            if self.cull_busy:
                logger.info("Culling kernels even if busy")
            if self.cull_connected:
                logger.info("Culling kernels even with connected clients")
            self._culler_callback.start()

        self._initialized_culler = True

    # receiveing messages from kernel on different channels


    # mapping kernel manager
    async def _async_shutdown_kernel(self, kernel_id, now=False, restart=False):
        """Shutdown a kernel by kernel_id"""
        self._check_kernel_id(kernel_id)

        # Decrease the metric of number of kernels
        # running for the relevant kernel type by 1
        KERNEL_CURRENTLY_RUNNING_TOTAL.labels(type=self._kernels[kernel_id].kernel_name).dec()

        if kernel_id in self._pending_kernel_tasks:
            task = self._pending_kernel_tasks.pop(kernel_id)
            task.cancel()

        self.stop_watching_activity(kernel_id)
        self.stop_buffering(kernel_id)

        return await self._multikm_async_shutdown_kernel(
            self, kernel_id, now=now, restart=restart
        )

    shutdown_kernel = _async_shutdown_kernel

    def start_buffering(self, kernel_id, session_key, channels):
        """Start buffering messages for a kernel

        Parameters
        ----------
        kernel_id : str
            The id of the kernel to stop buffering.
        session_key : str
            The session_key, if any, that should get the buffer.
            If the session_key matches the current buffered session_key,
            the buffer will be returned.
        channels : dict({'channel': ZMQStream})
            The zmq channels whose messages should be buffered.
        """

        if not self.buffer_offline_messages:
            for stream in channels.values():
                stream.close()
            return

        logger.info("Starting buffering for %s", session_key)
        self._check_kernel_id(kernel_id)
        # clear previous buffering state
        self.stop_buffering(kernel_id)
        buffer_info = self._kernel_buffers[kernel_id]
        # record the session key because only one session can buffer
        buffer_info["session_key"] = session_key
        # TODO: the buffer should likely be a memory bounded queue, we're starting with a list to keep it simple
        buffer_info["buffer"] = []
        buffer_info["channels"] = channels

        # forward any future messages to the internal buffer
        def buffer_msg(channel, msg_parts):
            logger.debug("Buffering msg on %s:%s", kernel_id, channel)
            buffer_info["buffer"].append((channel, msg_parts))

        for channel, stream in channels.items():
            stream.on_recv(partial(buffer_msg, channel))

    def get_buffer(self, kernel_id, session_key):
        """Get the buffer for a given kernel

        Parameters
        ----------
        kernel_id : str
            The id of the kernel to stop buffering.
        session_key : str, optional
            The session_key, if any, that should get the buffer.
            If the session_key matches the current buffered session_key,
            the buffer will be returned.
        """
        logger.debug("Getting buffer for %s", kernel_id)
        if kernel_id not in self._kernel_buffers:
            return None

        buffer_info = self._kernel_buffers[kernel_id]
        if buffer_info["session_key"] == session_key:
            # remove buffer
            self._kernel_buffers.pop(kernel_id)
            # only return buffer_info if it's a match
            return buffer_info
        else:
            self.stop_buffering(kernel_id)

    def stop_buffering(self, kernel_id):
        """Stop buffering kernel messages

        Parameters
        ----------
        kernel_id : str
            The id of the kernel to stop buffering.
        """
        logger.debug("Clearing buffer for %s", kernel_id)
        self._check_kernel_id(kernel_id)

        if kernel_id not in self._kernel_buffers:
            return
        buffer_info = self._kernel_buffers.pop(kernel_id)
        # close buffering streams
        for stream in buffer_info["channels"].values():
            if not stream.socket.closed:
                stream.on_recv(None)
                stream.close()

        msg_buffer = buffer_info["buffer"]
        if msg_buffer:
            logger.info(
                "Discarding %s buffered messages for %s",
                len(msg_buffer),
                buffer_info["session_key"],
            )
