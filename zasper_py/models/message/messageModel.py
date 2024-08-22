class Header:
    msg_id: str # typically UUID, must be unique per message 
    session: str # typically UUID, should be unique per session
    username: str
    date: str # ISO 8601 timestamp for when the message is created
    msg_type: str # All recognized message type strings are listed below.
    version: str #the message protocol version



class Metadata:
    deletedCells: list
    recordTiming: bool
    cellId: str
    

class Content:
    silent: bool
    store_history: bool
    user_expressions: dict,
    allow_stdin: bool,
    stop_on_error: bool,
    code: str

    

class Message
    buffers: list
    channel: str
    header: Header
    parent_header: Header,
    metadata: Metadata
    content: Content
    


# {
#     "buffers": [],
#     "channel": "shell",
#     "content": {
#         "silent": false,
#         "store_history": true,
#         "user_expressions": {},
#         "allow_stdin": true,
#         "stop_on_error": true,
#         "code": "1200*3600"
#     },
#     "header": {
#         "date": getTimeStamp(),
#         "msg_id": uuidv4(),
#         "msg_type": "execute_request",
#         "session": session.id,
#         "username": "",
#         "version": "5.2"
#     },
#     "metadata": {
#         "deletedCells": [],
#         "recordTiming": false,
#         "cellId": "1cb16896-03e7-480c-aa2b-f1ba6bb1b56d"
#     },
#     "parent_header": {}
# }
