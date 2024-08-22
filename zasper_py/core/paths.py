import logging
import os
import site
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

import platformdirs

pjoin = os.path.join


logger = logging.getLogger(__name__)

APPNAME = "zasper"


def envset(name: str, default: Optional[bool] = False) -> Optional[bool]:
    """Return the boolean value of a given environment variable.

    An environment variable is considered set if it is assigned to a value
    other than 'no', 'n', 'false', 'off', '0', or '0.0' (case insensitive)

    If the environment variable is not defined, the default value is returned.
    """
    if name not in os.environ:
        return default

    return os.environ[name].lower() not in ["no", "n", "false", "off", "0", "0.0"]


def prefer_environment_over_user() -> bool:
    """Determine if environment-level paths should take precedence over user-level paths."""
    # If JUPYTER_PREFER_ENV_PATH is defined, that signals user intent, so return its value
    if "JUPYTER_PREFER_ENV_PATH" in os.environ:
        return envset("JUPYTER_PREFER_ENV_PATH")  # type:ignore[return-value]

    # If we are in a Python virtualenv, default to True (see https://docs.python.org/3/library/venv.html#venv-def)
    if sys.prefix != sys.base_prefix and _do_i_own(sys.prefix):
        return True

    # If sys.prefix indicates Python comes from a conda/mamba environment that is not the root environment, default to True
    if (
        "CONDA_PREFIX" in os.environ
        and sys.prefix.startswith(os.environ["CONDA_PREFIX"])
        and os.environ.get("CONDA_DEFAULT_ENV", "base") != "base"
        and _do_i_own(sys.prefix)
    ):
        return True

    return False


def use_platform_dirs() -> bool:
    """Determine if platformdirs should be used for system-specific paths.

    We plan for this to default to False in jupyter_core version 5 and to True
    in jupyter_core version 6.
    """
    return envset("JUPYTER_PLATFORM_DIRS", False)


def get_home_dir() -> str:
    """Get the real path of the home directory"""
    homedir = Path("~").expanduser()
    # Next line will make things work even when /home/ is a symlink to
    # /usr/home as it is on FreeBSD, for example
    return str(Path(homedir).resolve())


_dtemps: dict[str, str] = {}


# /home/prasun/.jupyter
def jupyter_config_dir() -> str:
    """Get the Jupyter config directory for this platform and user.

    Returns JUPYTER_CONFIG_DIR if defined, otherwise the appropriate
    directory for the platform.
    """

    env = os.environ
    if env.get("JUPYTER_NO_CONFIG"):
        return _mkdtemp_once("jupyter-clean-cfg")

    if env.get("JUPYTER_CONFIG_DIR"):
        return env["JUPYTER_CONFIG_DIR"]

    if use_platform_dirs():
        return platformdirs.user_config_dir(APPNAME, appauthor=False)

    home_dir = get_home_dir()
    return pjoin(home_dir, ".jupyter")


# /home/prasun/.local/share
def jupyter_data_dir() -> str:
    """Get the config directory for Jupyter data files for this platform and user.

    These are non-transient, non-configuration files.

    Returns JUPYTER_DATA_DIR if defined, else a platform-appropriate path.
    """
    env = os.environ

    if env.get("JUPYTER_DATA_DIR"):
        return env["JUPYTER_DATA_DIR"]

    if use_platform_dirs():
        return platformdirs.user_data_dir(APPNAME, appauthor=False)

    home = get_home_dir()

    if sys.platform == "darwin":
        return str(Path(home, "Library", "Jupyter"))
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", None)
        if appdata:
            return str(Path(appdata, "jupyter").resolve())
        return pjoin(jupyter_config_dir(), "data")
    # Linux, non-OS X Unix, AIX, etc.
    xdg = env.get("XDG_DATA_HOME", None)
    if not xdg:
        xdg = pjoin(home, ".local", "share")
    return pjoin(xdg, "jupyter")


# /home/prasun/.local/share/runtime
def jupyter_runtime_dir() -> str:
    """Return the runtime dir for transient jupyter files.

    Returns JUPYTER_RUNTIME_DIR if defined.

    The default is now (data_dir)/runtime on all platforms;
    we no longer use XDG_RUNTIME_DIR after various problems.
    """
    env = os.environ

    if env.get("JUPYTER_RUNTIME_DIR"):
        return env["JUPYTER_RUNTIME_DIR"]

    return pjoin(jupyter_data_dir(), "runtime")


# "/usr/local/share/jupyter",
# "/usr/share/jupyter",
if use_platform_dirs():
    SYSTEM_JUPYTER_PATH = platformdirs.site_data_dir(
        APPNAME, appauthor=False, multipath=True
    ).split(os.pathsep)
else:
    print(
        "Jupyter is migrating its paths to use standard platformdirs\n"
        "given by the platformdirs library.  To remove this warning and\n"
        "see the appropriate new directories, set the environment variable\n"
        "`JUPYTER_PLATFORM_DIRS=1` and then run `jupyter --paths`.\n"
        "The use of platformdirs will be the default in `jupyter_core` v6"
    )
    if os.name == "nt":
        programdata = os.environ.get("PROGRAMDATA", None)
        if programdata:
            SYSTEM_JUPYTER_PATH = [pjoin(programdata, "jupyter")]
        else:  # PROGRAMDATA is not defined by default on XP.
            SYSTEM_JUPYTER_PATH = [str(Path(sys.prefix, "share", "jupyter"))]
    else:
        SYSTEM_JUPYTER_PATH = [
            "/usr/local/share/jupyter",
            "/usr/share/jupyter",
        ]

ENV_JUPYTER_PATH: list[str] = [str(Path(sys.prefix, "share", "jupyter"))]


def jupyter_path(*subdirs: str) -> list[str]:
    """Return a list of directories to search for data files

    JUPYTER_PATH environment variable has highest priority.

    If the JUPYTER_PREFER_ENV_PATH environment variable is set, the environment-level
    directories will have priority over user-level directories.

    If the Python site.ENABLE_USER_SITE variable is True, we also add the
    appropriate Python user site subdirectory to the user-level directories.


    If ``*subdirs`` are given, that subdirectory will be added to each element.

    Examples:

    >>> jupyter_path()
    ['~/.local/jupyter', '/usr/local/share/jupyter']
    >>> jupyter_path('kernels')
    ['~/.local/jupyter/kernels', '/usr/local/share/jupyter/kernels']
    """

    paths: list[str] = []

    # highest priority is explicit environment variable
    if os.environ.get("JUPYTER_PATH"):
        paths.extend(
            p.rstrip(os.sep) for p in os.environ["JUPYTER_PATH"].split(os.pathsep)
        )

    # Next is environment or user, depending on the JUPYTER_PREFER_ENV_PATH flag
    user = [jupyter_data_dir()]
    if site.ENABLE_USER_SITE:
        # Check if site.getuserbase() exists to be compatible with virtualenv,
        # which often does not have this method.
        userbase: Optional[str]
        userbase = (
            site.getuserbase() if hasattr(site, "getuserbase") else site.USER_BASE
        )

        if userbase:
            userdir = str(Path(userbase, "share", "jupyter"))
            if userdir not in user:
                user.append(userdir)

    env = [p for p in ENV_JUPYTER_PATH if p not in SYSTEM_JUPYTER_PATH]

    if prefer_environment_over_user():
        paths.extend(env)
        paths.extend(user)
    else:
        paths.extend(user)
        paths.extend(env)

    # finally, system
    paths.extend(SYSTEM_JUPYTER_PATH)

    # add subdir, if requested
    if subdirs:
        paths = [pjoin(p, *subdirs) for p in paths]
    return paths


if use_platform_dirs():
    SYSTEM_CONFIG_PATH = platformdirs.site_config_dir(
        APPNAME, appauthor=False, multipath=True
    ).split(os.pathsep)
else:
    if os.name == "nt":
        programdata = os.environ.get("PROGRAMDATA", None)
        if programdata:  # noqa: SIM108
            SYSTEM_CONFIG_PATH = [str(Path(programdata, "jupyter"))]
        else:  # PROGRAMDATA is not defined by default on XP.
            SYSTEM_CONFIG_PATH = []
    else:
        SYSTEM_CONFIG_PATH = [
            "/usr/local/etc/jupyter",
            "/etc/jupyter",
        ]
ENV_CONFIG_PATH: list[str] = [str(Path(sys.prefix, "etc", "jupyter"))]


def jupyter_config_path() -> list[str]:
    """Return the search path for Jupyter config files as a list.

    If the JUPYTER_PREFER_ENV_PATH environment variable is set, the
    environment-level directories will have priority over user-level
    directories.

    If the Python site.ENABLE_USER_SITE variable is True, we also add the
    appropriate Python user site subdirectory to the user-level directories.
    """
    if os.environ.get("JUPYTER_NO_CONFIG"):
        # jupyter_config_dir makes a blank config when JUPYTER_NO_CONFIG is set.
        return [jupyter_config_dir()]

    paths: list[str] = []

    # highest priority is explicit environment variable
    if os.environ.get("JUPYTER_CONFIG_PATH"):
        paths.extend(
            p.rstrip(os.sep)
            for p in os.environ["JUPYTER_CONFIG_PATH"].split(os.pathsep)
        )

    # Next is environment or user, depending on the JUPYTER_PREFER_ENV_PATH flag
    user = [jupyter_config_dir()]
    if site.ENABLE_USER_SITE:
        userbase: Optional[str]
        # Check if site.getuserbase() exists to be compatible with virtualenv,
        # which often does not have this method.
        userbase = (
            site.getuserbase() if hasattr(site, "getuserbase") else site.USER_BASE
        )

        if userbase:
            userdir = str(Path(userbase, "etc", "jupyter"))
            if userdir not in user:
                user.append(userdir)

    env = [p for p in ENV_CONFIG_PATH if p not in SYSTEM_CONFIG_PATH]

    if prefer_environment_over_user():
        paths.extend(env)
        paths.extend(user)
    else:
        paths.extend(user)
        paths.extend(env)

    # Finally, system path
    paths.extend(SYSTEM_CONFIG_PATH)
    return paths


def is_hidden(abs_path: str, abs_root: str = "") -> bool:
    """Is a file hidden or contained in a hidden directory?

    This will start with the rightmost path element and work backwards to the
    given root to see if a path is hidden or in a hidden directory. Hidden is
    determined by either name starting with '.' or the UF_HIDDEN flag as
    reported by stat.

    If abs_path is the same directory as abs_root, it will be visible even if
    that is a hidden folder. This only checks the visibility of files
    and directories *within* abs_root.

    Parameters
    ----------
    abs_path : unicode
        The absolute path to check for hidden directories.
    abs_root : unicode
        The absolute path of the root directory in which hidden directories
        should be checked for.
    """
    abs_path = os.path.normpath(abs_path)
    abs_root = os.path.normpath(abs_root)

    if abs_path == abs_root:
        return False

    if is_file_hidden(abs_path):
        return True

    if not abs_root:
        abs_root = abs_path.split(os.sep, 1)[0] + os.sep
    inside_root = abs_path[len(abs_root) :]
    if any(part.startswith(".") for part in Path(inside_root).parts):
        return True

    # check UF_HIDDEN on any location up to root.
    # is_file_hidden() already checked the file, so start from its parent dir
    path = str(Path(abs_path).parent)
    while path and path.startswith(abs_root) and path != abs_root:
        if not Path(path).exists():
            path = str(Path(path).parent)
            continue
        try:
            # may fail on Windows junctions
            st = os.lstat(path)
        except OSError:
            return True
        if getattr(st, "st_flags", 0) & UF_HIDDEN:
            return True
        path = str(Path(path).parent)

    return False


def is_file_hidden_win(abs_path: str, stat_res: Optional[Any] = None) -> bool:
    """Is a file hidden?

    This only checks the file itself; it should be called in combination with
    checking the directory containing the file.

    Use is_hidden() instead to check the file and its parent directories.

    Parameters
    ----------
    abs_path : unicode
        The absolute path to check.
    stat_res : os.stat_result, optional
        The result of calling stat() on abs_path. If not passed, this function
        will call stat() internally.
    """
    if Path(abs_path).name.startswith("."):
        return True

    if stat_res is None:
        try:
            stat_res = Path(abs_path).stat()
        except OSError as e:
            if e.errno == errno.ENOENT:
                return False
            raise

    try:
        if (
            stat_res.st_file_attributes  # type:ignore[union-attr]
            & stat.FILE_ATTRIBUTE_HIDDEN  # type:ignore[attr-defined]
        ):
            return True
    except AttributeError:
        # allow AttributeError on PyPy for Windows
        # 'stat_result' object has no attribute 'st_file_attributes'
        # https://foss.heptapod.net/pypy/pypy/-/issues/3469
        warnings.warn(
            "hidden files are not detectable on this system, so no file will be marked as hidden.",
            stacklevel=2,
        )

    return False


def is_file_hidden_posix(abs_path: str, stat_res: Optional[Any] = None) -> bool:
    """Is a file hidden?

    This only checks the file itself; it should be called in combination with
    checking the directory containing the file.

    Use is_hidden() instead to check the file and its parent directories.

    Parameters
    ----------
    abs_path : unicode
        The absolute path to check.
    stat_res : os.stat_result, optional
        The result of calling stat() on abs_path. If not passed, this function
        will call stat() internally.
    """
    if Path(abs_path).name.startswith("."):
        return True

    if stat_res is None or stat.S_ISLNK(stat_res.st_mode):
        try:
            stat_res = Path(abs_path).stat()
        except OSError as e:
            if e.errno == errno.ENOENT:
                return False
            raise

    # check that dirs can be listed
    if stat.S_ISDIR(stat_res.st_mode):  # noqa: SIM102
        # use x-access, not actual listing, in case of slow/large listings
        if not os.access(abs_path, os.X_OK | os.R_OK):
            return True

    # check UF_HIDDEN
    if getattr(stat_res, "st_flags", 0) & UF_HIDDEN:
        return True

    return False


if sys.platform == "win32":
    is_file_hidden = is_file_hidden_win
else:
    is_file_hidden = is_file_hidden_posix


allow_insecure_writes = os.getenv("JUPYTER_ALLOW_INSECURE_WRITES", "false").lower() in (
    "true",
    "1",
)


@contextmanager
def secure_write(fname: str, binary: bool = False) -> Iterator[Any]:
    """Opens a file in the most restricted pattern available for
    writing content. This limits the file mode to `0o0600` and yields
    the resulting opened filed handle.

    Parameters
    ----------

    fname : unicode
        The path to the file to write

    binary: boolean
        Indicates that the file is binary
    """
    mode = "wb" if binary else "w"
    encoding = None if binary else "utf-8"
    open_flag = os.O_CREAT | os.O_WRONLY | os.O_TRUNC
    try:
        Path(fname).unlink()
    except OSError:
        # Skip any issues with the file not existing
        pass

    if os.name == "nt":
        if allow_insecure_writes:
            # Mounted file systems can have a number of failure modes inside this block.
            # For windows machines in insecure mode we simply skip this to avoid failures :/
            issue_insecure_write_warning()
        else:
            # Python on windows does not respect the group and public bits for chmod, so we need
            # to take additional steps to secure the contents.
            # Touch file pre-emptively to avoid editing permissions in open files in Windows
            fd = os.open(fname, open_flag, 0o0600)
            os.close(fd)
            open_flag = os.O_WRONLY | os.O_TRUNC
            win32_restrict_file_to_user(fname)

    with os.fdopen(os.open(fname, open_flag, 0o0600), mode, encoding=encoding) as f:
        if os.name != "nt":
            # Enforce that the file got the requested permissions before writing
            file_mode = get_file_mode(fname)
            if file_mode != 0o0600:
                if allow_insecure_writes:
                    issue_insecure_write_warning()
                else:
                    msg = (
                        f"Permissions assignment failed for secure file: '{fname}'."
                        f" Got '{oct(file_mode)}' instead of '0o0600'."
                    )
                    raise RuntimeError(msg)
        yield f


def get_file_mode(fname: str) -> int:
    """Retrieves the file mode corresponding to fname in a filesystem-tolerant manner.

    Parameters
    ----------

    fname : unicode
        The path to the file to get mode from

    """
    # Some filesystems (e.g., CIFS) auto-enable the execute bit on files.  As a result, we
    # should tolerate the execute bit on the file's owner when validating permissions - thus
    # the missing least significant bit on the third octal digit. In addition, we also tolerate
    # the sticky bit being set, so the lsb from the fourth octal digit is also removed.
    return (
        stat.S_IMODE(Path(fname).stat().st_mode) & 0o6677
    )  # Use 4 octal digits since S_IMODE does the same


def issue_insecure_write_warning() -> None:
    """Issue an insecure write warning."""

    def format_warning(msg: str, *args: Any, **kwargs: Any) -> str:  # noqa: ARG001
        return str(msg) + "\n"

    warnings.formatwarning = format_warning  # type:ignore[assignment]
    logger.info(
        "WARNING: Insecure writes have been enabled via environment variable "
        "'JUPYTER_ALLOW_INSECURE_WRITES'! If this is not intended, remove the "
        "variable or set its value to 'False'.",
        stacklevel=2,
    )
