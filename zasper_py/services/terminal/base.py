import os
import shlex
import sys
from shutil import which

from zasper_backend.services.terminal.terminalManager import TerminalManager


class TerminalsMixin:
    def _default_root_dir(self):
        return os.getcwd()

    def initial(self) -> None:
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

        self._terminal_manager = TerminalManager(
            shell_command=shell,
            extra_env={
                "JUPYTER_SERVER_ROOT": self._default_root_dir()
                # "JUPYTER_SERVER_URL": self.serverapp.connection_url,
            },
            parent=self
        )
        self.initialized = True
        self.count +=1
        # self.terminal_manager.log = self.serverapp.log



