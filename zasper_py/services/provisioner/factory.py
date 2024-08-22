import glob
import logging
import sys
from os import getenv, path
from typing import Any, Dict, List

from zasper_backend.services.provisioner import LocalProvisioner

# See compatibility note on `group` keyword in https://docs.python.org/3/library/importlib.metadata.html#entry-points
if sys.version_info < (3, 10):  # pragma: no cover
    from importlib_metadata import (  # type:ignore[import-not-found]
        EntryPoint, entry_points)
else:  # pragma: no cover
    from importlib.metadata import EntryPoint, entry_points

from zasper_backend.services.provisioner.base import KernelProvisionerBase

logger = logging.getLogger(__name__)


class KernelProvisionerFactory:
    """
      :class:`KernelProvisionerFactory` is responsible for creating provisioner instances.

      A singleton instance, `KernelProvisionerFactory` is also used by the :class:`KernelSpecManager`
      to validate `kernel_provisioner` references found in kernel specifications to confirm their
      availability (in cases where the kernel specification references a kernel provisioner that has
      not been installed into the current Python environment).

      It's ``default_provisioner_name`` attribute can be used to specify the default provisioner
      to use when a kernel_spec is found to not reference a provisioner.  It's value defaults to
      `"local-provisioner"` which identifies the local provisioner implemented by
      :class:`LocalProvisioner`.

      'zasper_backend.kernel_provisioners': [
      EntryPoint(name=
      'local-provisioner',
      value=
      'zasper_backend.provisioning:LocalProvisioner',
      group=
      'zasper_backend.kernel_provisioners'
      )
    ]
    """

    provisioners = {}

    GROUP_NAME = "zasper_server.kernel_provisioners"

    # default_provisioner_name_env = "ZASPER_DEFAULT_PROVISIONER_NAME"
    default_provisioner_name_env = "local-provisioner"
    default_provisioner_name = None

    def _default_provisioner_name_default(self) -> str:
        """The default provisioner name."""
        return getenv(self.default_provisioner_name_env, "local-provisioner")

    def __init__(self, **kwargs: Any) -> None:
        """Initialize a kernel provisioner factory."""
        super().__init__(**kwargs)
        self.default_provisioner_name = self._default_provisioner_name_default()
        for ep in KernelProvisionerFactory._get_all_provisioners():
            self.provisioners[ep.name] = ep

    @staticmethod
    def _get_all_provisioners() -> List[EntryPoint]:
        """Wrapper around entry_points (to fetch the set of provisioners) - primarily to facilitate testing."""
        ep = entry_points(group=KernelProvisionerFactory.GROUP_NAME)
        return ep

    def is_provisioner_available(self, kernel_spec: Any) -> bool:
        """
        Reads the associated ``kernel_spec`` to determine the provisioner and returns whether it
        exists as an entry_point (True) or not (False).  If the referenced provisioner is not
        in the current cache or cannot be loaded via entry_points, a warning message is issued
        indicating it is not available.
        """
        is_available: bool = True
        provisioner_cfg = self._get_provisioner_config(kernel_spec)
        provisioner_name = str(provisioner_cfg.get("provisioner_name"))
        if not self._check_availability(provisioner_name):
            is_available = False
            self.log.warning(
                f"Kernel '{kernel_spec.display_name}' is referencing a kernel "
                f"provisioner ('{provisioner_name}') that is not available.  "
                f"Ensure the appropriate package has been installed and retry."
            )
        return is_available

    def create_provisioner_instance(
        self, kernel_id: str, kernel_spec: Any, parent: Any
    ) -> KernelProvisionerBase:
        """
        Reads the associated ``kernel_spec`` to see if it has a `kernel_provisioner` stanza.
        If one exists, it instantiates an instance.  If a kernel provisioner is not
        specified in the kernel specification, a default provisioner stanza is fabricated
        and instantiated corresponding to the current value of ``default_provisioner_name`` trait.
        The instantiated instance is returned.

        If the provisioner is found to not exist (not registered via entry_points),
        `ModuleNotFoundError` is raised.
        """
        provisioner_cfg = self._get_provisioner_config(kernel_spec)
        provisioner_name = str(provisioner_cfg.get("provisioner_name"))
        if not self._check_availability(provisioner_name):
            msg = f"Kernel provisioner '{provisioner_name}' has not been registered."
            raise ModuleNotFoundError(msg)

        logger.info(
            f"Instantiating kernel '{kernel_spec.display_name}' with "
            f"kernel provisioner: {provisioner_name}"
        )
        provisioner_class = self.provisioners[provisioner_name].load()
        provisioner_config = provisioner_cfg.get("config")
        print(type(provisioner_class))
        # provisioner: KernelProvisionerBase = provisioner_class(
        provisioner: KernelProvisionerBase = LocalProvisioner(
            kernel_id=kernel_id,
            kernel_spec=kernel_spec,
            parent=parent,
            **provisioner_config,
        )
        return provisioner

    def _check_availability(self, provisioner_name: str) -> bool:
        """
        Checks that the given provisioner is available.

        If the given provisioner is not in the current set of loaded provisioners an attempt
        is made to fetch the named entry point and, if successful, loads it into the cache.

        :param provisioner_name:
        :return:
        """
        is_available = True
        if provisioner_name not in self.provisioners:
            try:
                ep = self._get_provisioner(provisioner_name)
                self.provisioners[provisioner_name] = ep  # Update cache
            except Exception:
                is_available = False
        return is_available

    def _get_provisioner_config(self, kernel_spec: Any) -> Dict[str, Any]:
        """
        Return the kernel_provisioner stanza from the kernel_spec.

        Checks the kernel_spec's metadata dictionary for a kernel_provisioner entry.
        If found, it is returned, else one is created relative to the DEFAULT_PROVISIONER
        and returned.

        Parameters
        ----------
        kernel_spec : Any - this is a KernelSpec type but listed as Any to avoid circular import
            The kernel specification object from which the provisioner dictionary is derived.

        Returns
        -------
        dict
            The provisioner portion of the kernel_spec.  If one does not exist, it will contain
            the default information.  If no `config` sub-dictionary exists, an empty `config`
            dictionary will be added.
        """
        env_provisioner = kernel_spec.metadata.get("kernel_provisioner", {})
        if (
            "provisioner_name" in env_provisioner
        ):  # If no provisioner_name, return default
            if (
                "config" not in env_provisioner
            ):  # if provisioner_name, but no config stanza, add one
                env_provisioner.update({"config": {}})
            return env_provisioner  # Return what we found (plus config stanza if necessary)
        return {"provisioner_name": self.default_provisioner_name, "config": {}}

    def get_provisioner_entries(self) -> Dict[str, str]:
        """
        Returns a dictionary of provisioner entries.

        The key is the provisioner name for its entry point.  The value is the colon-separated
        string of the entry point's module name and object name.
        """
        entries = {}
        for name, ep in self.provisioners.items():
            entries[name] = ep.value
        return entries

    def _get_provisioner(self, name: str) -> EntryPoint:
        """Wrapper around entry_points (to fetch a single provisioner) - primarily to facilitate testing."""
        eps = entry_points(group=KernelProvisionerFactory.GROUP_NAME, name=name)
        if eps:
            return eps[0]

        # Check if the entrypoint name is 'local-provisioner'.  Although this should never
        # happen, we have seen cases where the previous distribution of jupyter_client has
        # remained which doesn't include kernel-provisioner entrypoints (so 'local-provisioner'
        # is deemed not found even though its definition is in THIS package).  In such cases,
        # the entrypoints package uses what it first finds - which is the older distribution
        # resulting in a violation of a supposed invariant condition.  To address this scenario,
        # we will log a warning message indicating this situation, then build the entrypoint
        # instance ourselves - since we have that information.
        if name == "local-provisioner":
            distros = glob.glob(f"{path.dirname(path.dirname(__file__))}-*")
            logger.warning(
                f"Kernel Provisioning: The 'local-provisioner' is not found.  This is likely "
                f"due to the presence of multiple jupyter_client distributions and a previous "
                f"distribution is being used as the source for entrypoints - which does not "
                f"include 'local-provisioner'.  That distribution should be removed such that "
                f"only the version-appropriate distribution remains (version >= 7).  Until "
                f"then, a 'local-provisioner' entrypoint will be automatically constructed "
                f"and used.\nThe candidate distribution locations are: {distros}"
            )
            return EntryPoint(
                "local-provisioner",
                "zasper_backend.services.provisioner",
                "LocalProvisioner",
            )

        raise
