import logging
# https://github.com/jupyter-server/jupyter_server/blob/main/jupyter_server/services/kernels/websocket.py
from tornado import web
from tornado.websocket import WebSocketHandler

from zasper_backend.api.base.BaseApiHandler import ZasperAPIHandler
from zasper_backend.services.websocketHandler.connection.channels import ZMQChannelsWebsocketConnection
from zasper_backend.services.websocketHandler.websocketmixin import WebSocketMixin
from zasper_backend.utils import ensure_async

logger = logging.getLogger(__name__)


class KernelWebsocketHandler(ZasperAPIHandler, WebSocketMixin, WebSocketHandler):
    # auth_resource = AUTH_RESOURCE

    @property
    def kernel_websocket_connection_class(self):
        """The kernel websocket connection class."""
        return ZMQChannelsWebsocketConnection

    def set_default_headers(self):
        """Undo the set_default_headers in JupyterHandler

        which doesn't make sense for websockets
        """

    def get_compression_options(self):
        """Get the socket connection options."""
        return self.settings.get("websocket_compression_options", None)

    async def pre_get(self):
        """Handle a pre_get."""
        user = self.current_user

        # authorize the user.
        # authorized = await ensure_async(
        #     self.authorizer.is_authorized(self, user, "execute", "kernels")
        # )
        # if not authorized:
        #     raise web.HTTPError(403)

        kernel = self.kernel_manager.get_kernel(self.kernel_id)
        self.config = {}
        print("session goes here")
        self.connection = self.kernel_websocket_connection_class(
            parent=kernel, websocket_handler=self, config=self.config
        )

        if self.get_argument("session_id", None):
            self.connection.session.session = self.get_argument("session_id")
        else:
            logger.warning("No session ID specified")
        # For backwards compatibility with older versions
        # of the websocket connection, call a prepare method if found.
        if hasattr(self.connection, "prepare"):
            await self.connection.prepare()

    # @ws_authenticated
    async def get(self, kernel_id):
        """Handle a get request for a kernel."""
        self.kernel_id = kernel_id
        await self.pre_get()
        await super().get(kernel_id=kernel_id)

    async def open(self, kernel_id):
        """Open a kernel websocket."""
        # Need to call super here to make sure we
        # begin a ping-pong loop with the client.
        # super().open()
        # Wait for the kernel to emit an idle status.
        logger.info(f"Connecting to kernel {self.kernel_id}.")
        logger.info(f"Connecting to kernel {self.kernel_id}.")
        logger.info(f"Connecting to kernel {self.kernel_id}.")
        print(self.connection)
        await self.connection.connect()


    def on_message(self, ws_message):
        """Get a kernel message from the websocket and turn it into a ZMQ message."""
        self.connection.handle_incoming_message(ws_message)

    def on_close(self):
        """Handle a socket closure."""
        self.connection.disconnect()
        self.connection = None

    def select_subprotocol(self, subprotocols):
        """Select the sub protocol for the socket."""
        preferred_protocol = self.connection.kernel_ws_protocol
        if preferred_protocol is None:
            preferred_protocol = "v1.kernel.websocket.jupyter.org"
        elif preferred_protocol == "":
            preferred_protocol = None
        selected_subprotocol = preferred_protocol if preferred_protocol in subprotocols else None
        # None is the default, "legacy" protocol
        return selected_subprotocol
