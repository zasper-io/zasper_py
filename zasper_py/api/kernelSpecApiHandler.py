import contextvars
import json
import uuid
import glob
import os

from tornado.web import RequestHandler
from typing import Any

from zasper_backend.api.base.BaseApiHandler import ZasperAPIHandler
from zasper_backend.services.kernelspec.kernelSpecManager import \
    KernelSpecManager
from zasper_backend.utils import url_path_join

request_id_var = contextvars.ContextVar("request_id")

pjoin = os.path.join

def kernelspec_model(handler, name, spec_dict, resource_dir):
    """Load a KernelSpec by name and return the REST API model"""
    d = {"name": name, "spec": spec_dict, "resources": {}}

    # Add resource files if they exist
    for resource in ["kernel.js", "kernel.css"]:
        if os.path.exists(pjoin(resource_dir, resource)):
            d["resources"][resource] = url_path_join(
                handler.base_url, "kernelspecs", name, resource
            )
    for logo_file in glob.glob(pjoin(resource_dir, "logo-*")):
        fname = os.path.basename(logo_file)
        no_ext, _ = os.path.splitext(fname)
        d["resources"][no_ext] = url_path_join(handler.base_url, "kernelspecs", name, fname)
    return d


def is_kernelspec_model(spec_dict):
    """Returns True if spec_dict is already in proper form.  This will occur when using a gateway."""
    return (
        isinstance(spec_dict, dict)
        and "name" in spec_dict
        and "spec" in spec_dict
        and "resources" in spec_dict
    )

class KernelSpecApiHandler(ZasperAPIHandler):
    def initialize(self):
        self.ksm = KernelSpecManager()

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

    def get(self, *args):
        # ksm = KernelSpecModel(name="yolo", KernelSpecFile="string", resources="string")
        model: dict[str, Any] = {}
        model["default"] = "python3" #self.km.default_kernel_name
        model["kernelspecs"] = specs = {}
        kspecs = self.ksm.get_all_specs()
        for kernel_name, kernel_info in kspecs.items():
            try:
                if is_kernelspec_model(kernel_info):
                    d = kernel_info
                else:
                    d = kernelspec_model(
                        self,
                        kernel_name,
                        kernel_info["spec"],
                        kernel_info["resource_dir"],
                    )
            except Exception:
                self.log.error("Failed to load kernel spec: '%s'", kernel_name, exc_info=True)
                continue
            specs[kernel_name] = d
        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps(model))

    def post(self):
        pass

    def delete(self):
        pass
