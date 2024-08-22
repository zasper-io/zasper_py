# Responsible for installing and listing kernelSpecs
# Responsible for launching kernels
import argparse
import errno
import sys

from zasper_backend._version import __version__
from zasper_backend.services.kernelspec.kernelSpecManager import \
    KernelSpecManager


class InstallKernelSpec:
    """An app to install a kernel spec."""

    # version = __version__
    description = """Install a kernel specification directory.

    Given a SOURCE DIRECTORY containing a kernel spec,
    jupyter will copy that directory into one of the Jupyter kernel directories.
    The default is to install kernelspecs for all users.
    `--user` can be specified to install a kernel only for the current user.
    """
    examples = """
    jupyter kernelspec install /path/to/my_kernel --user
    """
    usage = "jupyter kernelspec install SOURCE_DIR [--options]"
    kernel_spec_manager = KernelSpecManager()

    def _kernel_spec_manager_default(self) -> KernelSpecManager:
        print("data_dir is:", self.data_dir)
        return KernelSpecManager(data_dir=self.data_dir)

    sourcedir = "/home/prasun"
    kernel_name = "superkernel"

    def _kernel_name_default(self) -> str:
        return os.path.basename(self.sourcedir)

    def _user_kernel_dir_default(self) -> str:
        return pjoin(self.data_dir, "kernels")

    user = True
    prefix = ""
    replace = False
    aliases = {
        "name": "InstallKernelSpec.kernel_name",
        "prefix": "InstallKernelSpec.prefix",
    }
    # aliases.update(base_aliases)

    flags = {
        "user": (
            {"InstallKernelSpec": {"user": True}},
            "Install to the per-user kernel registry",
        ),
        "replace": (
            {"InstallKernelSpec": {"replace": True}},
            "Replace any existing kernel spec with this name.",
        ),
        "sys-prefix": (
            {"InstallKernelSpec": {"prefix": sys.prefix}},
            "Install to Python's sys.prefix. Useful in conda/virtual environments.",
        ),
        # "debug": base_flags["debug"],
    }

    def parse_command_line(
        self, argv: None | list[str]
    ) -> None:  # type:ignore[override]
        """Parse the command line args."""
        super().parse_command_line(argv)
        # accept positional arg as profile name
        if self.extra_args:
            self.sourcedir = self.extra_args[0]
        else:
            print("No source directory specified.", file=sys.stderr)
            self.exit(1)

    def start(self) -> None:
        """Start the application."""
        if self.user and self.prefix:
            self.exit(
                "Can't specify both user and prefix. Please choose one or the other."
            )
        try:
            self.kernel_spec_manager.install_kernel_spec(
                self.sourcedir,
                kernel_name=self.kernel_name,
                user=self.user,
                prefix=self.prefix,
                replace=self.replace,
            )
        except OSError as e:
            if e.errno == errno.EACCES:
                print(e, file=sys.stderr)
                if not self.user:
                    print(
                        "Perhaps you want to install with `sudo` or `--user`?",
                        file=sys.stderr,
                    )
                exit(1)
            elif e.errno == errno.EEXIST:
                print(
                    f"A kernel spec is already present at {e.filename}", file=sys.stderr
                )
                self.exit(1)
            raise


def main():
    parser = argparse.ArgumentParser(description="Script so useful.")
    parser.add_argument("--opt1", type=int, default=1)
    parser.add_argument("--opt2")

    args = parser.parse_args()

    print("opt1 is", args.opt1)
    if args.opt2 == "install":
        installer = InstallKernelSpec()
        installer.start()

        print("opt2 is", args.opt2)
