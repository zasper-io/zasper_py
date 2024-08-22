import contextvars
import json
import logging
import uuid
import os
import shlex
import sys
from shutil import which

from tornado import ioloop, web, websocket
from tornado.web import RequestHandler

from zasper_py.api.contentApiHandler import (CheckpointsApiHandler,
                                                  ContentApiHandler,
                                                  ModifyCheckpointsApiHandler)
from zasper_py.api.identityApiHandler import IdentityApiHandler
from zasper_py.api.infoApiHandler import InfoApiHandler
from zasper_py.api.kernelActionApiHandler import KernelActionApiHandler
from zasper_py.api.kernelApiHandler import KernelApiHandler, RootKernelApiHandler
from zasper_py.api.kernelSpecApiHandler import KernelSpecApiHandler
from zasper_py.api.projectApiHandler import ProjectApiHandler
from zasper_py.api.secretApiHandler import SecretApiHandler
from zasper_py.api.sessionApiHandler import (SessionApiHandler,
                                                  SessionRootApiHandler)
from zasper_py.api.singleKernelSpecApiHandler import \
    SingleKernelSpecApiHandler
from zasper_py.api.singleProjectApiHandler import SingleProjectApiHandler
from zasper_py.api.statusApiHandler import StatusApiHandler
from zasper_py.api.terminalApiHandler import TerminalApiHandler, TerminalRootApiHandler
from zasper_py.api.userApiHandler import UserApiHandler
from zasper_py.services.kernels.multiKernelManager import MultiKernelManager
from zasper_py.services.session.sessionManager import SessionManager
from zasper_py.services.terminal.terminalManager import TerminalManager
from zasper_py.services.terminal.terminalWebsocketHandler import TermSocket
from zasper_py.services.websocketHandler.kernelWebsocketHandler import KernelWebsocketHandler

cl = []

logger = logging.getLogger(__name__)
request_id_var = contextvars.ContextVar("request_id")


class IndexHandler(RequestHandler):
    def get(self):
        self.render("ui/index.html")


class MyFilter(logging.Filter):
    def filter(self, record):
        record.request_id = request_id_var.get("-")
        return True


path_regex = r"(?P<path>(?:(?:/[^/]+)+|/?))"
_checkpoint_id_regex = r"(?P<checkpoint_id>[\w-]+)"

kernel_name_regex = r"(?P<kernel_name>[\w\.\-%]+)"

_session_id_regex = r"(?P<session_id>\w+-\w+-\w+-\w+-\w+)"

_kernel_id_regex = r"(?P<kernel_id>\w+-\w+-\w+-\w+-\w+)"
_kernel_action_regex = r"(?P<action>restart|interrupt)"

app = web.Application(
    [
        (r"/", IndexHandler),
        (r"/api/me", IdentityApiHandler),
        (r"/user", UserApiHandler),
        (r"/info", InfoApiHandler),
        (r"/api/contents%s/checkpoints" % path_regex, CheckpointsApiHandler),
        (
            rf"/api/contents{path_regex}/checkpoints/{_checkpoint_id_regex}",
            ModifyCheckpointsApiHandler,
        ),
        # (r"/api/contents%s/trust" % path_regex, TrustNotebooksHandler),
        (r"/api/contents%s" % path_regex, ContentApiHandler),
        # (r"/api/notebooks/?(.*)", NotebooksRedirectHandler),
        (r"/api/kernelspecs", KernelSpecApiHandler),
        (r"/api/kernelspecs/%s" % kernel_name_regex, SingleKernelSpecApiHandler),
        (r"/api/projects", ProjectApiHandler),
        (r"/api/projects/([a-z]+)", SingleProjectApiHandler),
        (r"/api/sessions/%s" % _session_id_regex, SessionApiHandler),
        (r"/api/sessions", SessionRootApiHandler),

        (r"/api/kernels", RootKernelApiHandler),
        (r"/api/kernels/%s" % _kernel_id_regex, KernelApiHandler),
        (
            rf"/api/kernels/{_kernel_id_regex}/{_kernel_action_regex}",
            KernelActionApiHandler,
        ),
        (r"/api/kernels/%s/channels" % _kernel_id_regex, KernelWebsocketHandler),

        (r"/api/terminals", TerminalRootApiHandler),
        (r"/api/terminals/(\w+)", TerminalApiHandler),

        (r"/api/terminals/websocket/(\w+)", TermSocket),

        (r"/api/secrets", SecretApiHandler),
        (r"/api/status", StatusApiHandler),
        (r"/(script.js)", web.StaticFileHandler, {"path": "./"}),
        (r"/(rest_api_example.png)", web.StaticFileHandler, {"path": "./"}),
    ]
)


def _default_root_dir():
    return os.getcwd()


def initialize_tm() -> TerminalManager:
    """Initialize configurables."""
    default_shell = "powershell.exe" if os.name == "nt" else which("sh")
    # assert self.serverapp is not None
    # shell_override = self.serverapp.terminado_settings.get("shell_command")
    shell_override = None
    if isinstance(shell_override, str):
        shell_override = shlex.split(shell_override)
    shell = (
        [os.environ.get("SHELL") or default_shell] if shell_override is None else shell_override
    )
    # When the notebook server is not running in a terminal (e.g. when
    # it's launched by a JupyterHub spawner), it's likely that the user
    # environment hasn't been fully set up. In that case, run a login
    # shell to automatically source /etc/profile and the like, unless
    # the user has specifically set a preferred shell command.
    if os.name != "nt" and shell_override is None and not sys.stdout.isatty():
        shell.append("-l")

    return TerminalManager(
        shell_command=shell,
        extra_env={
            "JUPYTER_SERVER_ROOT": _default_root_dir()
            # "JUPYTER_SERVER_URL": self.serverapp.connection_url,
        }
    )
    # self.terminal_manager.log = self.serverapp.log


app._session_manager = SessionManager()
app._kernel_manager = MultiKernelManager()
app._terminal_manager = initialize_tm()


def main():
    logging.basicConfig(
        format="%(levelname)s %(request_id)s %(message)s", level=logging.INFO
    )

    # kl = KernelLauncher()
    # # print(kl.run())
    # #  how to run in loop ?
    # kl.run()

    my_filter = MyFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(my_filter)

    app.listen(8888)

    logger.info("Listening at http://localhost:%d", 8888)

    ioloop.IOLoop.instance().start()
