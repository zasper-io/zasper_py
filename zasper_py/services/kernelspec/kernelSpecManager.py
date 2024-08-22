import json
import logging
import os
import re
import shutil
import typing as t
import warnings

from zasper_py.core.paths import (SYSTEM_JUPYTER_PATH, jupyter_data_dir,
                                       jupyter_path)
from zasper_py.models.kernelSpecModel import KernelSpecModel

pjoin = os.path.join

NATIVE_KERNEL_NAME = "python3"

# https://github.com/jupyter/jupyter_client/blob/main/jupyter_client/kernelspec.py

logger = logging.getLogger(__name__)


class KernelSpecManager:
    ensure_native_kernel = False

    def _user_kernel_dir_default(self) -> str:
        return pjoin(self.data_dir, "kernels")

    def _data_dir_default(self) -> str:
        return jupyter_data_dir()

    def _kernel_dirs_default(self) -> list[str]:
        dirs = jupyter_path("kernels")
        # At some point, we should stop adding .ipython/kernels to the path,
        # but the cost to keeping it is very small.
        try:
            # this should always be valid on IPython 3+
            from IPython.paths import get_ipython_dir

            dirs.append(os.path.join(get_ipython_dir(), "kernels"))
        except ModuleNotFoundError:
            pass
        return dirs

    def __init__(self):
        self.data_dir = self._data_dir_default()
        self.user_kernel_dir = self._user_kernel_dir_default()
        self.kernel_dirs = self._kernel_dirs_default()

    def find_kernel_specs(self) -> dict[str, str]:
        """Returns a dict mapping kernel names to resource directories."""
        d = {}
        print("finding kernel specs")
        for kernel_dir in self.kernel_dirs:
            kernels = _list_kernels_in(kernel_dir)
            for kname, spec in kernels.items():
                if kname not in d:
                    print("Found kernel %s in %s", kname, kernel_dir)
                    d[kname] = spec

        if self.ensure_native_kernel and NATIVE_KERNEL_NAME not in d:
            try:
                from ipykernel.kernelspec import RESOURCES

                self.log.debug(
                    "Native kernel (%s) available from %s",
                    NATIVE_KERNEL_NAME,
                    RESOURCES,
                )
                d[NATIVE_KERNEL_NAME] = RESOURCES
            except ImportError:
                self.log.warning(
                    "Native kernel (%s) is not available", NATIVE_KERNEL_NAME
                )

        # if self.allowed_kernelspecs:
        #     # filter if there's an allow list
        #     d = {
        #         name: spec
        #         for name, spec in d.items()
        #         if name in self.allowed_kernelspecs
        #     }
        print(d)
        return d
        # TODO: Caching?

    def _get_kernel_spec_by_name(self, kernel_name: str, resource_dir: str):
        """Returns a :class:`KernelSpec` instance for a given kernel_name
        and resource_dir.
        """
        print("getting kernelspec by name ")
        kspec = None
        kspec = from_resource_dir(resource_dir)
        # if kernel_name == NATIVE_KERNEL_NAME:
        #     try:
        #         from ipykernel.kernelspec import RESOURCES, get_kernel_dict
        #     except ImportError:
        #         # It should be impossible to reach this, but let's play it safe
        #         pass
        #     else:
        #         if resource_dir == RESOURCES:
        #             kdict = get_kernel_dict()
        #             kspec = self.kernel_spec_class(resource_dir=resource_dir, **kdict)
        # if not kspec:
        #     kspec = self.kernel_spec_class.from_resource_dir(resource_dir)

        # if not KPF.instance(parent=self.parent).is_provisioner_available(kspec):
        #     raise NoSuchKernel(kernel_name)

        return kspec

    def _find_spec_directory(self, kernel_name: str) -> str | None:
        """Find the resource directory of a named kernel spec"""
        for kernel_dir in [kd for kd in self.kernel_dirs if os.path.isdir(kd)]:
            files = os.listdir(kernel_dir)
            for f in files:
                path = pjoin(kernel_dir, f)
                if f.lower() == kernel_name and _is_kernel_dir(path):
                    return path

        if kernel_name == NATIVE_KERNEL_NAME:
            try:
                from ipykernel.kernelspec import RESOURCES
            except ImportError:
                pass
            else:
                return RESOURCES
        return None

    def get_kernel_spec(self, kernel_name: str):
        """Returns a :class:`KernelSpec` instance for the given kernel_name.

        Raises :exc:`NoSuchKernel` if the given kernel name is not found.
        """
        if not _is_valid_kernel_name(kernel_name):
            logger.warning(
                f"Kernelspec name {kernel_name} is invalid: {_kernel_name_description}"
            )

        resource_dir = self._find_spec_directory(kernel_name.lower())
        if resource_dir is None:
            logger.warning("Kernelspec name %s cannot be found!", kernel_name)
            raise NoSuchKernel(kernel_name)

        return self._get_kernel_spec_by_name(kernel_name, resource_dir)

    def get_all_specs(self) -> dict[str, t.Any]:
        """Returns a dict mapping kernel names to kernelspecs.

        Returns a dict of the form::

            {
              'kernel_name': {
                'resource_dir': '/path/to/kernel_name',
                'spec': {"the spec itself": ...}
              },
              ...
            }
        """
        d = self.find_kernel_specs()
        res = {}
        print("d = >", d)
        for kname, resource_dir in d.items():
            try:
                if self.__class__ is KernelSpecManager:
                    spec = self._get_kernel_spec_by_name(kname, resource_dir)
                else:
                    # avoid calling private methods in subclasses,
                    # which may have overridden find_kernel_specs
                    # and get_kernel_spec, but not the newer get_all_specs
                    spec = self.get_kernel_spec(kname)

                res[kname] = {"resource_dir": resource_dir, "spec": spec.dict()}
            except NoSuchKernel:
                pass  # The appropriate warning has already been logged
            except Exception:
                # self.log.warning("Error loading kernelspec %r", kname, exc_info=True)
                print("Error loading kernelspec %r", kname)
        return res

    def remove_kernel_spec(self, name: str) -> str:
        """Remove a kernel spec directory by name.

        Returns the path that was deleted.
        """
        save_native = self.ensure_native_kernel
        try:
            self.ensure_native_kernel = False
            specs = self.find_kernel_specs()
        finally:
            self.ensure_native_kernel = save_native
        spec_dir = specs[name]
        self.log.debug("Removing %s", spec_dir)
        if os.path.islink(spec_dir):
            os.remove(spec_dir)
        else:
            shutil.rmtree(spec_dir)
        return spec_dir

    def _get_destination_dir(
        self, kernel_name: str, user: bool = False, prefix: str | None = None
    ) -> str:
        if user:
            return os.path.join(self.user_kernel_dir, kernel_name)
        elif prefix:
            return os.path.join(
                os.path.abspath(prefix), "share", "jupyter", "kernels", kernel_name
            )
        else:
            return os.path.join(SYSTEM_JUPYTER_PATH[0], "kernels", kernel_name)

    def install_kernel_spec(
        self,
        source_dir: str,
        kernel_name: str | None = None,
        user: bool = False,
        replace: bool | None = None,
        prefix: str | None = None,
    ) -> str:
        """Install a kernel spec by copying its directory.

        If ``kernel_name`` is not given, the basename of ``source_dir`` will
        be used.

        If ``user`` is False, it will attempt to install into the systemwide
        kernel registry. If the process does not have appropriate permissions,
        an :exc:`OSError` will be raised.

        If ``prefix`` is given, the kernelspec will be installed to
        PREFIX/share/jupyter/kernels/KERNEL_NAME. This can be sys.prefix
        for installation inside virtual or conda envs.
        """
        source_dir = source_dir.rstrip("/\\")
        if not kernel_name:
            kernel_name = os.path.basename(source_dir)
        kernel_name = kernel_name.lower()
        print("kernel_name is", kernel_name)
        if not _is_valid_kernel_name(kernel_name):
            msg = f"Invalid kernel name {kernel_name!r}.  {_kernel_name_description}"
            raise ValueError(msg)

        if user and prefix:
            msg = "Can't specify both user and prefix. Please choose one or the other."
            raise ValueError(msg)

        if replace is not None:
            warnings.warn(
                "replace is ignored. Installing a kernelspec always replaces an existing "
                "installation",
                DeprecationWarning,
                stacklevel=2,
            )

        destination = self._get_destination_dir(kernel_name, user=user, prefix=prefix)
        print("Installing kernelspec in %s", destination)

        kernel_dir = os.path.dirname(destination)
        print("kernel dir is =>", kernel_dir)
        print("self.kernel_dirs is =>", self.kernel_dirs)
        if kernel_dir not in self.kernel_dirs:
            print(
                "Installing to %s, which is not in %s. The kernelspec may not be found.",
                kernel_dir,
                self.kernel_dirs,
            )

        if os.path.isdir(destination):
            print("Removing existing kernelspec in %s", destination)
            shutil.rmtree(destination)

        shutil.copytree(source_dir, destination)
        self.log.info("Installed kernelspec %s in %s", kernel_name, destination)
        return destination

    def install_native_kernel_spec(self, user: bool = False) -> None:
        """DEPRECATED: Use ipykernel.kernelspec.install"""
        warnings.warn(
            "install_native_kernel_spec is deprecated. Use ipykernel.kernelspec import install.",
            stacklevel=2,
        )
        from ipykernel.kernelspec import install

        install(self, user=user)


def install_kernel_spec(
    source_dir: str,
    kernel_name: str | None = None,
    user: bool = False,
    replace: bool | None = False,
    prefix: str | None = None,
) -> str:
    """Install a kernel spec in a given directory."""
    return KernelSpecManager().install_kernel_spec(
        source_dir, kernel_name, user, replace, prefix
    )


_kernel_name_pat = re.compile(r"^[a-z0-9._\-]+$", re.IGNORECASE)


def _is_valid_kernel_name(name: str) -> t.Any:
    """Check that a kernel name is valid."""
    # quote is not unicode-safe on Python 2
    return _kernel_name_pat.match(name)


_kernel_name_description = (
    "Kernel names can only contain ASCII letters and numbers and these separators:"
    " - . _ (hyphen, period, and underscore)."
)


def _is_kernel_dir(path: str) -> bool:
    """Is ``path`` a kernel directory?"""
    return os.path.isdir(path) and os.path.isfile(pjoin(path, "kernel.json"))


def _list_kernels_in(dir: str | None) -> dict[str, str]:
    """Return a mapping of kernel names to resource directories from dir.

    If dir is None or does not exist, returns an empty dict.
    """
    if dir is None or not os.path.isdir(dir):
        return {}
    kernels = {}
    for f in os.listdir(dir):
        path = pjoin(dir, f)
        if not _is_kernel_dir(path):
            continue
        key = f.lower()
        if not _is_valid_kernel_name(key):
            warnings.warn(
                f"Invalid kernelspec directory name ({_kernel_name_description}): {path}",
                stacklevel=3,
            )
        kernels[key] = path
    return kernels


class NoSuchKernel(KeyError):  # noqa
    """An error raised when there is no kernel of a give name."""

    def __init__(self, name: str) -> None:
        """Initialize the error."""
        self.name = name

    def __str__(self) -> str:
        return f"No such kernel named {self.name}"


def from_resource_dir(resource_dir: str) -> KernelSpecModel:
    """Create a KernelSpec object by reading kernel.json

    Pass the path to the *directory* containing kernel.json.
    """
    print("loading file")
    kernel_file = pjoin(resource_dir, "kernel.json")
    with open(kernel_file, encoding="utf-8") as f:
        kernel_dict = json.load(f)
    km = KernelSpecModel(resource_dir=resource_dir, **kernel_dict)
    return km
