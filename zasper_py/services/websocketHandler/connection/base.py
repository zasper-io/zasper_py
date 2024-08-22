import json
import struct
from typing import List, Any

from zasper_backend.services.kernels.session import Session
from zasper_backend.utils.jsonutil import json_default, extract_dates


def serialize_binary_message(msg):
    """serialize a message as a binary blob

    Header:

    4 bytes: number of msg parts (nbufs) as 32b int
    4 * nbufs bytes: offset for each buffer as integer as 32b int

    Offsets are from the start of the buffer, including the header.

    Returns
    -------
    The message serialized to bytes.

    """
    # don't modify msg or buffer list in-place
    msg = msg.copy()
    buffers = list(msg.pop("buffers"))
    bmsg = json.dumps(msg, default=json_default).encode("utf8")
    buffers.insert(0, bmsg)
    nbufs = len(buffers)
    offsets = [4 * (nbufs + 1)]
    for buf in buffers[:-1]:
        offsets.append(offsets[-1] + len(buf))
    offsets_buf = struct.pack("!" + "I" * (nbufs + 1), nbufs, *offsets)
    buffers.insert(0, offsets_buf)
    return b"".join(buffers)


def deserialize_binary_message(bmsg):
    """deserialize a message from a binary blog

    Header:

    4 bytes: number of msg parts (nbufs) as 32b int
    4 * nbufs bytes: offset for each buffer as integer as 32b int

    Offsets are from the start of the buffer, including the header.

    Returns
    -------
    message dictionary
    """
    nbufs = struct.unpack("!i", bmsg[:4])[0]
    offsets = list(struct.unpack("!" + "I" * nbufs, bmsg[4 : 4 * (nbufs + 1)]))
    offsets.append(None)
    bufs = []
    for start, stop in zip(offsets[:-1], offsets[1:]):
        bufs.append(bmsg[start:stop])
    msg = json.loads(bufs[0].decode("utf8"))
    msg["header"] = extract_dates(msg["header"])
    msg["parent_header"] = extract_dates(msg["parent_header"])
    msg["buffers"] = bufs[1:]
    return msg


def serialize_msg_to_ws_v1(msg_or_list, channel, pack=None):
    """Serialize a message using the v1 protocol."""
    if pack:
        msg_list = [
            pack(msg_or_list["header"]),
            pack(msg_or_list["parent_header"]),
            pack(msg_or_list["metadata"]),
            pack(msg_or_list["content"]),
        ]
    else:
        msg_list = msg_or_list
    channel = channel.encode("utf-8")
    offsets: List[Any] = []
    offsets.append(8 * (1 + 1 + len(msg_list) + 1))
    offsets.append(len(channel) + offsets[-1])
    for msg in msg_list:
        offsets.append(len(msg) + offsets[-1])
    offset_number = len(offsets).to_bytes(8, byteorder="little")
    offsets = [offset.to_bytes(8, byteorder="little") for offset in offsets]
    bin_msg = b"".join([offset_number, *offsets, channel, *msg_list])
    return bin_msg


def deserialize_msg_from_ws_v1(ws_msg):
    """Deserialize a message using the v1 protocol."""
    offset_number = int.from_bytes(ws_msg[:8], "little")
    offsets = [
        int.from_bytes(ws_msg[8 * (i + 1) : 8 * (i + 2)], "little") for i in range(offset_number)
    ]
    channel = ws_msg[offsets[0] : offsets[1]].decode("utf-8")
    msg_list = [ws_msg[offsets[i] : offsets[i + 1]] for i in range(1, offset_number - 1)]
    return channel, msg_list


class BaseKernelWebsocketConnection():
    """A configurable base class for connecting Kernel WebSockets to ZMQ sockets."""
    # "Preferred kernel message protocol over websocket to use (default: None). "
    # "If an empty string is passed, select the legacy protocol. If None, "
    # "the selected protocol will depend on what the front-end supports "
    # "(usually the most recent protocol supported by the back-end and the "
    # "front-end)."
    kernel_ws_protocol = None

    @property
    def kernel_manager(self):
        """The kernel manager."""
        return self.parent

    @property
    def multi_kernel_manager(self):
        """The multi kernel manager."""
        return self.kernel_manager.parent

    @property
    def kernel_id(self):
        """The kernel id."""
        return self.kernel_manager.kernel_id

    @property
    def session_id(self):
        """The session id."""
        return self.session.session

    kernel_info_timeout = None
    session = None

    def __init__(self, **kwargs):
        print("==session initialized here============")
        self.parent = kwargs['parent']
        self.kernel_info_timeout = self._default_kernel_info_timeout()
        self.session = self._default_session()


    def _default_kernel_info_timeout(self):
        return self.multi_kernel_manager.kernel_info_timeout

    def _default_session(self):
        print("==session initialized here============")
        return Session()  # config=self.config)

    websocket_handler = None

    async def connect(self):
        """Handle a connect."""
        raise NotImplementedError

    async def disconnect(self):
        """Handle a disconnect."""
        raise NotImplementedError

    def handle_incoming_message(self, incoming_msg: str) -> None:
        """Handle an incoming message."""
        raise NotImplementedError

    def handle_outgoing_message(self, stream: str, outgoing_msg: List[Any]) -> None:
        """Handle an outgoing message."""
        raise NotImplementedError
