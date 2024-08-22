import time
import typing as t


class KernelRestarter:
    """Monitor and autorestart a kernel."""

    # Instance("jupyter_client.KernelManager")
    kernel_manager = None
    # Whether to include every poll event in debugging output.
    # Has to be set explicitly, because there will be *a lot* of output.


    def __init__(self):
        self._last_dead = self._default_last_dead()
        self.debug = False
        # Kernel heartbeat interval in seconds.
        self.time_to_dead = 3.0
        # The time in seconds to consider the kernel to have completed a stable start up.
        self.stable_start_time = 10.0

        # The number of consecutive autorestarts before the kernel is presumed dead.""",
        self.restart_limit = 5
        # Whether to choose new random ports when restarting before the kernel is alive
        random_ports_until_alive = True
        self._restarting = False
        self._restart_count = 0
        self._initial_startup = True
        self.callbacks = self._callbacks_default()

    def _default_last_dead(self) -> float:
        return time.time()

    def _callbacks_default(self) -> dict[str, list]:
        return {"restart": [], "dead": []}

    def start(self) -> None:
        """Start the polling of the kernel."""
        msg = "Must be implemented in a subclass"
        raise NotImplementedError(msg)

    def stop(self) -> None:
        """Stop the kernel polling."""
        msg = "Must be implemented in a subclass"
        raise NotImplementedError(msg)

    def add_callback(self, f: t.Callable[..., t.Any], event: str = "restart") -> None:
        """register a callback to fire on a particular event

        Possible values for event:

          'restart' (default): kernel has died, and will be restarted.
          'dead': restart has failed, kernel will be left dead.

        """
        self.callbacks[event].append(f)

    def remove_callback(
        self, f: t.Callable[..., t.Any], event: str = "restart"
    ) -> None:
        """unregister a callback to fire on a particular event

        Possible values for event:

          'restart' (default): kernel has died, and will be restarted.
          'dead': restart has failed, kernel will be left dead.

        """
        try:
            self.callbacks[event].remove(f)
        except ValueError:
            pass

    def _fire_callbacks(self, event: t.Any) -> None:
        """fire our callbacks for a particular event"""
        for callback in self.callbacks[event]:
            try:
                callback()
            except Exception:
                self.log.error(
                    "KernelRestarter: %s callback %r failed",
                    event,
                    callback,
                    exc_info=True,
                )

    def poll(self) -> None:
        if self.debug:
            self.log.debug("Polling kernel...")
        if self.kernel_manager.shutting_down:
            self.log.debug("Kernel shutdown in progress...")
            return
        now = time.time()
        if not self.kernel_manager.is_alive():
            self._last_dead = now
            if self._restarting:
                self._restart_count += 1
            else:
                self._restart_count = 1

            if self._restart_count > self.restart_limit:
                self.log.warning("KernelRestarter: restart failed")
                self._fire_callbacks("dead")
                self._restarting = False
                self._restart_count = 0
                self.stop()
            else:
                newports = self.random_ports_until_alive and self._initial_startup
                self.log.info(
                    "KernelRestarter: restarting kernel (%i/%i), %s random ports",
                    self._restart_count,
                    self.restart_limit,
                    "new" if newports else "keep",
                )
                self._fire_callbacks("restart")
                self.kernel_manager.restart_kernel(now=True, newports=newports)
                self._restarting = True
        else:
            # Since `is_alive` only tests that the kernel process is alive, it does not
            # indicate that the kernel has successfully completed startup. To solve this
            # correctly, we would need to wait for a kernel info reply, but it is not
            # necessarily appropriate to start a kernel client + channels in the
            # restarter. Therefore, we use "has been alive continuously for X time" as a
            # heuristic for a stable start up.
            # See https://github.com/jupyter/jupyter_client/pull/717 for details.
            stable_start_time = self.stable_start_time
            if self.kernel_manager.provisioner:
                stable_start_time = (
                    self.kernel_manager.provisioner.get_stable_start_time(
                        recommended=stable_start_time
                    )
                )
            if self._initial_startup and now - self._last_dead >= stable_start_time:
                self._initial_startup = False
            if self._restarting and now - self._last_dead >= stable_start_time:
                self.log.debug("KernelRestarter: restart apparently succeeded")
                self._restarting = False


class IOLoopKernelRestarter(KernelRestarter):
    """Monitor and autorestart a kernel."""

    def __init__(self, **kwargs):
        super().__init__()
        self.loop = kwargs["loop"]
        self.kernel_manager = kwargs["parent"]

    def _loop_default(self) -> t.Any:
        warnings.warn(
            "IOLoopKernelRestarter.loop is deprecated in jupyter-client 5.2",
            DeprecationWarning,
            stacklevel=4,
        )
        from tornado import ioloop

        return ioloop.IOLoop.current()

    _pcallback = None

    def start(self) -> None:
        """Start the polling of the kernel."""
        if self._pcallback is None:
            from tornado.ioloop import PeriodicCallback

            self._pcallback = PeriodicCallback(
                self.poll,
                1000 * self.time_to_dead,
            )
            self._pcallback.start()

    def stop(self) -> None:
        """Stop the kernel polling."""
        if self._pcallback is not None:
            self._pcallback.stop()
            self._pcallback = None


class AsyncIOLoopKernelRestarter(IOLoopKernelRestarter):
    """An async io loop kernel restarter."""

    async def poll(self) -> None:  # type:ignore[override]
        """Poll the kernel."""
        if self.debug:
            self.log.debug("Polling kernel...")
        is_alive = await self.kernel_manager.is_alive()
        now = time.time()
        if not is_alive:
            self._last_dead = now
            if self._restarting:
                self._restart_count += 1
            else:
                self._restart_count = 1

            if self._restart_count > self.restart_limit:
                self.log.warning("AsyncIOLoopKernelRestarter: restart failed")
                self._fire_callbacks("dead")
                self._restarting = False
                self._restart_count = 0
                self.stop()
            else:
                newports = self.random_ports_until_alive and self._initial_startup
                self.log.info(
                    "AsyncIOLoopKernelRestarter: restarting kernel (%i/%i), %s random ports",
                    self._restart_count,
                    self.restart_limit,
                    "new" if newports else "keep",
                )
                self._fire_callbacks("restart")
                await self.kernel_manager.restart_kernel(now=True, newports=newports)
                self._restarting = True
        else:
            # Since `is_alive` only tests that the kernel process is alive, it does not
            # indicate that the kernel has successfully completed startup. To solve this
            # correctly, we would need to wait for a kernel info reply, but it is not
            # necessarily appropriate to start a kernel client + channels in the
            # restarter. Therefore, we use "has been alive continuously for X time" as a
            # heuristic for a stable start up.
            # See https://github.com/jupyter/jupyter_client/pull/717 for details.
            stable_start_time = self.stable_start_time
            if self.kernel_manager.provisioner:
                stable_start_time = (
                    self.kernel_manager.provisioner.get_stable_start_time(
                        recommended=stable_start_time
                    )
                )
            if self._initial_startup and now - self._last_dead >= stable_start_time:
                self._initial_startup = False
            if self._restarting and now - self._last_dead >= stable_start_time:
                self.log.debug(
                    "AsyncIOLoopKernelRestarter: restart apparently succeeded"
                )
                self._restarting = False
