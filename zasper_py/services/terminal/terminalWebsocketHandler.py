import contextvars
import json
import uuid

from tornado import web
from tornado.web import RequestHandler
import typing as t

from zasper_backend.api.base.BaseApiHandler import ZasperAPIHandler
from zasper_backend.services.terminal.base import TerminalsMixin
from zasper_backend.services.websocketHandler.websocketmixin import WebSocketMixin
from zasper_backend.utils.timeUtils import utcnow

from terminado.management import NamedTermManager
from zasper_backend.utils import ensure_async
from terminado.websocket import TermSocket as BaseTermSocket

request_id_var = contextvars.ContextVar("request_id")


class TermSocket(BaseTermSocket, ZasperAPIHandler, WebSocketMixin):
    def initialize(self, *args: t.Any) -> None:
        """Initialize the socket."""
        BaseTermSocket.initialize(self, self.terminal_manager)
        # print(name)

    # def get(self, name: str):
    #     """Get a terminal by name."""
    #     model = self.terminal_manager.get(name)
    #     self.finish(json.dumps(model))

    async def get(self, *args: t.Any, **kwargs: t.Any) -> None:
        """Get the terminal socket."""
        # user = self.current_user
        #
        # if not user:
        #     raise web.HTTPError(403)
        #
        # # authorize the user.
        # if self.authorizer is None:
        #     # Warn if an authorizer is unavailable.
        #     warn_disabled_authorization()  # type:ignore[unreachable]
        # elif not self.authorizer.is_authorized(self, user, "execute", self.auth_resource):
        #     raise web.HTTPError(403)
        self.authorizer = True
        print("hola")
        print(args)

        if args[0] not in self.term_manager.terminals:  # type:ignore[attr-defined]
            raise web.HTTPError(404)
        print("hola")
        resp = super().get(*args, **kwargs)
        print("hola", resp)
        if resp is not None:
            await ensure_async(resp)  # type:ignore[arg-type]

    async def on_message(self, message: t.Any) -> None:  # type:ignore[override]
        """Handle a socket message."""
        await ensure_async(super().on_message(message))  # type:ignore[arg-type]
        self._update_activity()

    def write_message(self, message: t.Any, binary: bool = False) -> None:  # type:ignore[override]
        """Write a message to the socket."""
        super().write_message(message, binary=binary)
        self._update_activity()

    def _update_activity(self) -> None:
        self.application.settings["terminal_last_activity"] = utcnow()
        # terminal may not be around on deletion/cull
        if self.term_name in self.terminal_manager.terminals:
            self.terminal_manager.terminals[self.term_name].last_activity = utcnow()  # type:ignore[attr-defined]
