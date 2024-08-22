import contextvars
import json
import uuid

from zasper_backend.api.base.BaseApiHandler import ZasperAPIHandler
from zasper_backend.utils import ensure_async, url_path_join, url_escape
from zasper_backend.utils.jsonutil import json_default

request_id_var = contextvars.ContextVar("request_id")


class RootKernelApiHandler(ZasperAPIHandler):
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

    async def get(self):
        """Get the list of running kernels."""
        km = self.kernel_manager
        kernels = await ensure_async(km.list_kernels())
        await self.finish(json.dumps(kernels, default=json_default))

    async def post(self):
        """Start a kernel."""
        km = self.kernel_manager
        model = self.get_json_body()
        if model is None:
            model = {"name": km.default_kernel_name}
        else:
            model.setdefault("name", km.default_kernel_name)

        kernel_id = await ensure_async(
            km.start_kernel(  # type:ignore[has-type]
                kernel_name=model["name"], path=model.get("path")
            )
        )
        model = await ensure_async(km.kernel_model(kernel_id))
        location = url_path_join(self.base_url, "api", "kernels", url_escape(kernel_id))
        self.set_header("Location", location)
        self.set_status(201)
        await self.finish(json.dumps(model, default=json_default))


class KernelApiHandler(ZasperAPIHandler):
    async def get(self, kernel_id):
        """Get a kernel model."""
        km = self.kernel_manager
        model = await ensure_async(km.kernel_model(kernel_id))
        await self.finish(json.dumps(model, default=json_default))

    async def delete(self, kernel_id):
        """Remove a kernel."""
        km = self.kernel_manager
        await ensure_async(km.shutdown_kernel(kernel_id))
        self.set_status(204)
        await self.finish()
