from __future__ import annotations
import os
import shlex
import sys
from shutil import which

import json
import logging
from pathlib import Path

from zasper_backend.api.base.BaseApiHandler import ZasperAPIHandler
from zasper_backend.services.terminal.base import TerminalsMixin

logger = logging.getLogger(__name__)


class TerminalRootApiHandler(ZasperAPIHandler):
    """The root terminal API handler."""

    def _default_root_dir(self):
        return os.getcwd()
    def get(self) -> None:
        """Get the list of terminals."""
        models = self.terminal_manager.list()
        self.finish(json.dumps(models))

    def post(self) -> None:
        """POST /terminals creates a new terminal and redirects to it"""
        data = self.get_json_body() or {}

        # if cwd is a relative path, it should be relative to the root_dir,
        # but if we pass it as relative, it will we be considered as relative to
        # the path jupyter_server was started in
        if "cwd" in data:
            cwd: Path | None = Path(data["cwd"])
            assert cwd is not None
            if not cwd.resolve().exists():
                cwd = Path(self.settings["server_root_dir"]).expanduser() / cwd
                if not cwd.resolve().exists():
                    cwd = None

            if cwd is None:
                server_root_dir = self.settings["server_root_dir"]
                logger.debug(
                    "Failed to find requested terminal cwd: %s\n"
                    "  It was not found within the server root neither: %s.",
                    data.get("cwd"),
                    server_root_dir,
                )
                del data["cwd"]
            else:
                logger.debug("Opening terminal in: %s", cwd.resolve())
                data["cwd"] = str(cwd.resolve())

        model = self.terminal_manager.create(**data)
        self.finish(json.dumps(model))


class TerminalApiHandler(ZasperAPIHandler):
    """A handler for a specific terminal."""

    SUPPORTED_METHODS = ("GET", "DELETE", "OPTIONS")  # type:ignore[assignment]

    def get(self, name: str) -> None:
        print(name)
        """Get a terminal by name."""
        model = self.terminal_manager.get(name)
        self.finish(json.dumps(model))

    async def delete(self, name: str) -> None:
        """Remove a terminal by name."""
        await self.terminal_manager.terminate(name, force=True)
        self.set_status(204)
        await self.finish()
