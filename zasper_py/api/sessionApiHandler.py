import contextvars
import uuid
from typing import Any, cast

from tornado import web
from tornado.web import HTTPError, RequestHandler

from zasper_backend.api.base.BaseApiHandler import ZasperAPIHandler
from zasper_backend.models.sessionModel import SessionModel
from zasper_backend.services.kernelspec.kernelSpecManager import NoSuchKernel
from zasper_backend.services.session.sessionManager import SessionManager
from zasper_backend.utils.jsonutil import json_default

request_id_var = contextvars.ContextVar("request_id")
import json
import logging

from zasper_backend.utils import ensure_async, url_path_join

logger = logging.getLogger(__name__)


class SessionApiHandler(ZasperAPIHandler):
    pass
    #
    # def initialize(self):
    #     pass
    #     # self.sm = SessionManager()
    #
    # def set_default_headers(self):
    #     self.set_header("Access-Control-Allow-Origin", "*")
    #     self.set_header("Access-Control-Allow-Headers", "*")
    #     self.set_header("Access-Control-Max-Age", 1000)
    #     self.set_header("Content-type", "application/json")
    #     self.set_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
    #     self.set_header(
    #         "Access-Control-Allow-Headers",
    #         "Content-Type, Access-Control-Allow-Origin, Access-Control-Allow-Headers, X-Requested-By, "
    #         "Access-Control-Allow-Methods",
    #     )
    #
    # def get_json_body(self) -> dict[str, Any] | None:
    #     """Return the body of the request as JSON data."""
    #     if not self.request.body:
    #         return None
    #     # Do we need to call body.decode('utf-8') here?
    #     body = self.request.body.strip().decode("utf-8")
    #     try:
    #         model = json.loads(body)
    #     except Exception as e:
    #         logger.info("Bad JSON: %r", body)
    #         logger.info("Couldn't parse JSON")
    #         raise HTTPError(400, "Invalid JSON in body of request") from e
    #     return cast("dict[str, Any]", model)
    #
    # def options(self):
    #     pass
    #
    # def prepare(self):
    #     # If the request headers do not include a request ID, let's generate one.
    #     request_id = self.request.headers.get("request-id") or str(uuid.uuid4())
    #     request_id_var.set(request_id)
    #
    # async def geta(self):
    #     session = await self.sm.get_sessions()
    #     self.write(session.json())
    #
    # async def post(self):
    #     model = self.get_json_body()
    #     if model is None:
    #         raise web.HTTPError(400, "No JSON data provided")
    #     name = model.get("name", None)
    #
    #     try:
    #         # There is a high chance here that `path` is not a path but
    #         # a unique session id
    #         path = model["path"]
    #     except KeyError as e:
    #         raise web.HTTPError(400, "Missing field in JSON data: path") from e
    #
    #     try:
    #         mtype = model["type"]
    #
    #     except KeyError as e:
    #         raise web.HTTPError(400, "Missing field in JSON data: type") from e
    #
    #     kernel = model.get("kernel", {})
    #     kernel_name = kernel.get("name", None)
    #     kernel_id = kernel.get("id", None)
    #     await self.sm.create_session(
    #         path=path,
    #         kernel_name=kernel_name,
    #         kernel_id=kernel_id,
    #         name=name,
    #         type=mtype,
    #     )


class SessionRootApiHandler(ZasperAPIHandler):
    # sm = None



    # def initialize(self):
    #     self.sm = SessionManager()

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

    def options(self):
        pass

    def prepare(self):
        # If the request headers do not include a request ID, let's generate one.
        request_id = self.request.headers.get("request-id") or str(uuid.uuid4())
        request_id_var.set(request_id)

    async def get(self):
        sessions = await self.sm.list_sessions()
        print(type(sessions))
        print(sessions)
        self.write(json.dumps(sessions))

    async def post(self):
        model = self.get_json_body()
        if model is None:
            raise web.HTTPError(400, "No JSON data provided")
        name = model.get("name", None)

        try:
            # There is a high chance here that `path` is not a path but
            # a unique session id
            path = model["path"]
        except KeyError as e:
            raise web.HTTPError(400, "Missing field in JSON data: path") from e

        try:
            mtype = model["type"]

        except KeyError as e:
            raise web.HTTPError(400, "Missing field in JSON data: type") from e

        kernel = model.get("kernel", {})
        kernel_name = kernel.get("name", None)
        kernel_id = kernel.get("id", None)
        # exists = await ensure_async(self.sm.session_exists(path=path))
        exists = False
        if exists:
            s_model = await self.sm.get_session(path=path)
        else:
            try:
                s_model = await self.sm.create_session(
                    path=path,
                    kernel_name=kernel_name,
                    kernel_id=kernel_id,
                    name=name,
                    type=mtype,
                )
            except NoSuchKernel:
                msg = (
                        "The '%s' kernel is not available. Please pick another "
                        "suitable kernel instead, or install that kernel." % kernel_name
                )
                status_msg = "%s not found" % kernel_name
                logger.warning("Kernel not found: %s" % kernel_name)
                self.set_status(501)
                await self.finish(json.dumps({"message": msg, "short_message": status_msg}))
                return
            except Exception as e:
                raise web.HTTPError(500, str(e)) from e

        location = url_path_join(self.base_url, "api", "sessions", s_model["id"])
        self.set_header("Location", location)
        self.set_status(201)
        await self.finish(json.dumps(s_model, default=json_default))
