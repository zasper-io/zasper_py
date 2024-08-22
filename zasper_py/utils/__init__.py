import asyncio
import atexit
import inspect
import os
import sys
import threading
from contextvars import ContextVar
from typing import Any, Awaitable, Callable, NewType, TypeVar, cast
from urllib.parse import quote

ApiPath = NewType("ApiPath", str)

T = TypeVar("T")


def to_os_path(path: ApiPath, root: str = "") -> str:
    """Convert an API path to a filesystem path

    If given, root will be prepended to the path.
    root must be a filesystem path already.
    """
    parts = str(path).strip("/").split("/")
    parts = [p for p in parts if p != ""]  #  remove duplicate splits
    path_ = os.path.join(root, *parts)
    return os.path.normpath(path_)


def url_path_join(*pieces: str) -> str:
    """Join components of url into a relative url

    Use to prevent double slash when joining subpath. This will leave the
    initial and final / in place
    """
    initial = pieces[0].startswith("/")
    final = pieces[-1].endswith("/")
    stripped = [s.strip("/") for s in pieces]
    result = "/".join(s for s in stripped if s)
    if initial:
        result = "/" + result
    if final:
        result = result + "/"
    if result == "//":
        result = "/"
    return result


def url_escape(path: str) -> str:
    """Escape special characters in a URL path

    Turns '/foo bar/' into '/foo%20bar/'
    """
    parts = path.split("/")
    return "/".join([quote(p) for p in parts])


class _TaskRunner:
    """A task runner that runs an asyncio event loop on a background thread."""

    def __init__(self) -> None:
        self.__io_loop: asyncio.AbstractEventLoop | None = None
        self.__runner_thread: threading.Thread | None = None
        self.__lock = threading.Lock()
        atexit.register(self._close)

    def _close(self) -> None:
        if self.__io_loop:
            self.__io_loop.stop()

    def _runner(self) -> None:
        loop = self.__io_loop
        assert loop is not None
        try:
            loop.run_forever()
        finally:
            loop.close()

    def run(self, coro: Any) -> Any:
        """Synchronously run a coroutine on a background thread."""
        with self.__lock:
            name = f"{threading.current_thread().name} - runner"
            if self.__io_loop is None:
                self.__io_loop = asyncio.new_event_loop()
                self.__runner_thread = threading.Thread(
                    target=self._runner, daemon=True, name=name
                )
                self.__runner_thread.start()
        fut = asyncio.run_coroutine_threadsafe(coro, self.__io_loop)
        return fut.result(None)


_runner_map: dict[str, _TaskRunner] = {}
_loop: ContextVar[asyncio.AbstractEventLoop | None] = ContextVar("_loop", default=None)


def run_sync(coro: Callable[..., Awaitable[T]]) -> Callable[..., T]:
    """Wraps coroutine in a function that blocks until it has executed.

    Parameters
    ----------
    coro : coroutine-function
        The coroutine-function to be executed.

    Returns
    -------
    result :
        Whatever the coroutine-function returns.
    """

    if not inspect.iscoroutinefunction(coro):
        raise AssertionError

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        name = threading.current_thread().name
        inner = coro(*args, **kwargs)
        try:
            # If a loop is currently running in this thread,
            # use a task runner.
            asyncio.get_running_loop()
            if name not in _runner_map:
                _runner_map[name] = _TaskRunner()
            return _runner_map[name].run(inner)
        except RuntimeError:
            pass

        # Run the loop for this thread.
        loop = ensure_event_loop()
        return loop.run_until_complete(inner)

    wrapped.__doc__ = coro.__doc__
    return wrapped


def ensure_event_loop(prefer_selector_loop: bool = False) -> asyncio.AbstractEventLoop:
    # Get the loop for this thread, or create a new one.
    loop = _loop.get()
    if loop is not None and not loop.is_closed():
        return loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        if sys.platform == "win32" and prefer_selector_loop:
            loop = asyncio.WindowsSelectorEventLoopPolicy().new_event_loop()
        else:
            loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    _loop.set(loop)
    return loop


async def ensure_async(obj: Awaitable[T] | T) -> T:
    """Convert a non-awaitable object to a coroutine if needed,
    and await it if it was not already awaited.

    This function is meant to be called on the result of calling a function,
    when that function could either be asynchronous or not.
    """
    if inspect.isawaitable(obj):
        obj = cast(Awaitable[T], obj)
        try:
            result = await obj
        except RuntimeError as e:
            if str(e) == "cannot reuse already awaited coroutine":
                # obj is already the coroutine's result
                return cast(T, obj)
            raise
        return result
    # obj doesn't need to be awaited
    return cast(T, obj)
