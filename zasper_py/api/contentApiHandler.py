from __future__ import annotations

import contextvars
import json
import logging
import uuid
from typing import Any, Dict, List, cast

from pydantic.json import pydantic_encoder
from tornado import escape, web
from tornado.httpclient import HTTPError
from tornado.web import RequestHandler

from zasper_backend.api.base.BaseApiHandler import ZasperAPIHandler
from zasper_backend.models.contentModel import ContentModel
from zasper_backend.services.content.contentsManager import ContentsManager
from zasper_backend.utils import ensure_async, url_escape, url_path_join
from zasper_backend.utils.jsonutil import json_default

request_id_var = contextvars.ContextVar("request_id")

logger = logging.getLogger(__name__)


class CheckpointsApiHandler(RequestHandler):
    pass


class ModifyCheckpointsApiHandler(RequestHandler):
    pass


def _validate_keys(expect_defined: bool, model: Dict[str, Any], keys: List[str]):
    """
    Validate that the keys are defined (i.e. not None) or not (i.e. None)
    """

    if expect_defined:
        errors = [key for key in keys if model[key] is None]
        if errors:
            raise web.HTTPError(
                500,
                f"Keys unexpectedly None: {errors}",
            )
    else:
        errors = {key: model[key] for key in keys if model[key] is not None}  # type: ignore[assignment]
        if errors:
            raise web.HTTPError(
                500,
                f"Keys unexpectedly not None: {errors}",
            )


def validate_model(model, expect_content=False, expect_hash=False):
    """
    Validate a model returned by a ContentsManager method.

    If expect_content is True, then we expect non-null entries for 'content'
    and 'format'.

    If expect_hash is True, then we expect non-null entries for 'hash' and 'hash_algorithm'.
    """
    required_keys = {
        "name",
        "path",
        "type",
        "writable",
        "created",
        "last_modified",
        "mimetype",
        "content",
        "format",
    }
    if expect_hash:
        required_keys.update(["hash", "hash_algorithm"])
    missing = required_keys - set(model.keys())
    if missing:
        raise web.HTTPError(
            500,
            f"Missing Model Keys: {missing}",
        )

    content_keys = ["content", "format"]
    _validate_keys(expect_content, model, content_keys)
    if expect_hash:
        _validate_keys(expect_hash, model, ["hash", "hash_algorithm"])


class ContentApiHandler(ZasperAPIHandler):

    @property
    def base_url(self) -> str:
        return cast(str, self.settings.get("base_url", "/"))

    def initialize(self):
        self.cm = ContentsManager()

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

    def options(self, a):
        pass

    def location_url(self, path):
        """Return the full URL location of a file.

        Parameters
        ----------
        path : unicode
            The API path of the file, such as "foo/bar.txt".
        """
        return url_path_join(self.base_url, "api", "contents", url_escape(path))


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

    async def get(self, path):
        path = path or ""

        type = self.get_query_argument("type", default=None)
        if type not in {None, "directory", "file", "notebook"}:
            # fall back to file if unknown type
            type = "file"

        format = self.get_query_argument("format", default=None)
        if format not in {None, "text", "base64"}:
            raise web.HTTPError(400, "Format %r is invalid" % format)
        content_str = self.get_query_argument("content", default="1")
        if content_str not in {"0", "1"}:
            raise web.HTTPError(400, "Content %r is invalid" % content_str)
        content = int(content_str or "")

        hash_str = self.get_query_argument("hash", default="0")
        if hash_str not in {"0", "1"}:
            raise web.HTTPError(400, f"Content {hash_str!r} is invalid")
        require_hash = int(hash_str)

        # if not cm.allow_hidden and await ensure_async(cm.is_hidden(path)):
        #     await self._finish_error(
        #         HTTPStatus.NOT_FOUND, f"file or directory {path!r} does not exist"
        #     )

        # content = await self.cm.get(os.getcwd())
        content = self.cm.get(
            path=path,
            type=type,
            format=format,
            content=content,
            require_hash=require_hash,
        )
        self.write(json.dumps(content, default=pydantic_encoder))

    async def _save(self, model, path):
        """Save an existing file."""
        chunk = model.get("chunk", None)
        if not chunk or chunk == -1:  # Avoid tedious log information
            logger.info("Saving file at %s", path)
        model = await ensure_async(self.contents_manager.save(model, path))
        validate_model(model)
        self._finish_model(model)

    async def _new_untitled(self, path, type="", ext=""):
        """Create a new, empty untitled entity"""
        logger.info("Creating new %s in %s", type or "file", path)
        model = await ensure_async(self.cm.new_untitled(path=path, type=type, ext=ext))
        self.set_status(201)
        print("model is => ", model)
        validate_model(model)
        self._finish_model(model)

    async def post(self, path=""):
        """Create a new file in the specified path.

        POST creates new files. The server always decides on the name.

        POST /api/contents/path
          New untitled, empty file or directory.
        POST /api/contents/path
          with body {"copy_from" : "/path/to/OtherNotebook.ipynb"}
          New copy of OtherNotebook in path
        """

        file_exists = await ensure_async(self.cm.file_exists(path))
        if file_exists:
            raise web.HTTPError(400, "Cannot POST to files, use PUT instead.")

        model = self.get_json_body()
        if model:
            copy_from = model.get("copy_from")
            if copy_from:
                # if not cm.allow_hidden and (
                #         await ensure_async(cm.is_hidden(path))
                #         or await ensure_async(cm.is_hidden(copy_from))
                # ):
                #     raise web.HTTPError(400, f"Cannot copy file or directory {path!r}")
                # else:
                #     await self._copy(copy_from, path)
                await self._copy(copy_from, path)
            else:
                ext = model.get("ext", "")
                type = model.get("type", "")
                if type not in {None, "", "directory", "file", "notebook"}:
                    # fall back to file if unknown type
                    type = "file"
                await self._new_untitled(path, type=type, ext=ext)
        else:
            await self._new_untitled(path)

    def _finish_model(self, model, location=True):
        """Finish a JSON request with a model, setting relevant headers, etc."""
        if location:
            location = self.location_url(model["path"])
            self.set_header("Location", location)
        self.set_header("Last-Modified", model["last_modified"])
        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps(model, default=json_default))

    async def delete(self, path=""):
        """delete a file in the given path"""

        # if not self.cm.allow_hidden and await ensure_async(cm.is_hidden(path)):
        #     raise web.HTTPError(400, f"Cannot delete file or directory {path!r}")

        logger.warning("delete %s", path)
        await ensure_async(self.cm.delete(path))
        self.set_status(204)
        await self.finish()

    async def patch(self, path=""):
        """PATCH renames a file or directory without re-uploading content."""
        model = self.get_json_body()
        if model is None:
            raise web.HTTPError(400, "JSON body missing")

        old_path = model.get("path")
        # if (
        #         old_path
        #         and not cm.allow_hidden
        #         and (
        #         await ensure_async(cm.is_hidden(path)) or await ensure_async(cm.is_hidden(old_path))
        # )
        # ):
        #     raise web.HTTPError(400, f"Cannot rename file or directory {path!r}")

        model = await ensure_async(self.cm.update(model, path))
        validate_model(model)
        self._finish_model(model)


