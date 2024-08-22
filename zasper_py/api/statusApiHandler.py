import contextvars
import uuid

from tornado.web import RequestHandler

from zasper_backend.models.apiStatusModel import ApiStatusModel

request_id_var = contextvars.ContextVar("request_id")


class StatusApiHandler(RequestHandler):
    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "*")
        self.set_header("Access-Control-Max-Age", 1000)
        self.set_header("Content-type", "application/json")
        self.set_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.set_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Access-Control-Allow-Origin, Access-Control-Allow-Headers, X-Requested-By, Access-Control-Allow-Methods",
        )

    def options(self):
        pass

    def prepare(self):
        # If the request headers do not include a request ID, let's generate one.
        request_id = self.request.headers.get("request-id") or str(uuid.uuid4())
        request_id_var.set(request_id)

    def get(self):
        asm = ApiStatusModel(
            started="string",
            last_activity="string",
            connections="string",
            kernels="string",
        )
        self.write(asm.json())
