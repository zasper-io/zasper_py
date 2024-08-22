import contextvars
import json
import os
import sys
import traceback
import uuid

from pydantic.json import pydantic_encoder
from tornado import escape
from tornado.web import RequestHandler

from zasper_backend.models.projectModel import ProjectModel
from zasper_backend.services.project.projectManager import ProjectsManager

request_id_var = contextvars.ContextVar("request_id")


class ProjectApiHandler(RequestHandler):
    def set_default_headers(self):
        print("set headers!!")
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "*")
        self.set_header("Access-Control-Max-Age", 1000)
        self.set_header("Content-type", "application/json")
        self.set_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.set_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Access-Control-Allow-Origin, Access-Control-Allow-Headers, X-Requested-By, Access-Control-Allow-Methods",
        )

    def _return_response(self, request, message_to_be_returned: dict, status_code):
        """
        Returns formatted response back to client
        """
        try:
            request.set_header("Content-Type", "application/json; charset=UTF-8")
            request.set_status(status_code)

            # If dictionary is not empty then write the dictionary directly into
            if bool(message_to_be_returned):
                request.write(message_to_be_returned)

            request.finish()
        except Exception:
            raise

    def prepare(self):
        # If the request headers do not include a request ID, let's generate one.
        request_id = self.request.headers.get("request-id") or str(uuid.uuid4())
        request_id_var.set(request_id)

    def options(self):
        pass

    async def get(self):
        self.cm = ProjectsManager()
        content = await self.cm.get(os.getcwd())
        self.write(json.dumps(content, default=pydantic_encoder))

    async def post(self):
        self.cm = ProjectsManager()

        self.cm.create_file("Untitled.ipynb")

        try:
            # Do something with request body
            request_payload = escape.json_decode(self.request.body)

            return self._return_response(self, request_payload, 200)

        except json.decoder.JSONDecodeError:
            return self._return_response(
                self, {"message": "Cannot decode request body!"}, 400
            )

        except Exception as ex:
            return self._return_response(
                self,
                {
                    "message": "Could not complete the request because of some error at the server!",
                    "cause": ex.args[0],
                    "stack_trace": traceback.format_exc(sys.exc_info()),
                },
                500,
            )
