import contextvars
import json
import logging

from typing import cast, Any

from tornado.web import RequestHandler, HTTPError

from zasper_backend.services.kernels.multiKernelManager import MultiKernelManager
from zasper_backend.services.session.sessionManager import SessionManager
from zasper_backend.services.terminal.terminalManager import TerminalManager

logger = logging.getLogger(__name__)
request_id_var = contextvars.ContextVar("request_id")


class ZasperAPIHandler(RequestHandler):
    # _session_manager = None
    # _kernel_manager = None
    # _terminal_manager = None




    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "*")
        self.set_header("Access-Control-Max-Age", 1000)
        self.set_header("Content-type", "application/json")
        self.set_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.set_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Access-Control-Allow-Origin, Access-Control-Allow-Headers, X-Requested-By, "
            "Access-Control-Allow-Methods",
        )

    @property
    def allow_origin(self) -> str:
        """Normal Access-Control-Allow-Origin"""
        return "*"

    @property
    def allow_origin_pat(self) -> str | None:
        """Regular expression version of allow_origin"""
        return "*"

    @property
    def base_url(self) -> str:
        return cast(str, self.settings.get("base_url", "/"))

    def get_json_body(self) -> dict[str, Any] | None:
        """Return the body of the request as JSON data."""
        if not self.request.body:
            return None
        # Do we need to call body.decode('utf-8') here?
        body = self.request.body.strip().decode("utf-8")
        try:
            model = json.loads(body)
        except Exception as e:
            logger.info("Bad JSON: %r", body)
            logger.info("Couldn't parse JSON")
            raise HTTPError(400, "Invalid JSON in body of request") from e
        return cast("dict[str, Any]", model)


    @property
    def kernel_manager(self) -> MultiKernelManager:
        return self.application._kernel_manager

    @property
    def km(self) -> MultiKernelManager:
        return self.application._kernel_manager

    @property
    def sm(self):
        return self.application._session_manager

    @property
    def session_manager(self):
        return self.application._session_manager

    @property
    def terminal_manager(self) -> TerminalManager:
        return self.application._terminal_manager

