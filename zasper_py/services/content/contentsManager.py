import errno
import itertools
import json
import logging
import mimetypes
import os
import shutil
import stat
import sys
from contextlib import contextmanager
import typing as t
from datetime import datetime
from nbformat import ValidationError, sign
from nbformat.v4 import new_notebook
from nbformat import validate as validate_nb
import nbformat
from send2trash import send2trash
from os.path import samefile

from tornado import web
from tornado.web import HTTPError

from zasper_py.models.contentModel import ContentModel
from zasper_py.utils import ApiPath, to_os_path, run_sync

logger = logging.getLogger(__name__)


class ContentsManager:
    def __init__(self):
        self.root_dir = self._default_root_dir()
        self.allow_hidden = False
        self.untitled_directory = "Untitled Folder"
        self.untitled_file = "untitled"
        self.untitled_notebook = "Untitled"
        self._pre_save_hooks = []
        self._post_save_hooks = []
        self.pre_save_hook = None
        self._post_save_hooks = None
        self.use_atomic_writing = True
        self.always_delete_dir = False
        self.delete_to_trash = True
        self.notary = sign.NotebookNotary()
        print("Content Manager is initialized")

    def _default_root_dir(self):
        return os.getcwd()
        # if not self.parent:
        #     return os.getcwd()
        # return self.parent.root_dir

    def exists(self, path):
        """Does a file or directory exist at the given path?

        Like os.path.exists

        Parameters
        ----------
        path : str
            The API path of a file or directory to check for.

        Returns
        -------
        exists : bool
            Whether the target exists.
        """
        return self.file_exists(path) or self.dir_exists(path)

    def is_hidden(self, path):
        """Does the API style path correspond to a hidden directory or file?

        Parameters
        ----------
        path : str
            The path to check. This is an API path (`/` separated,
            relative to root_dir).

        Returns
        -------
        hidden : bool
            Whether the path exists and is hidden.
        """
        path = path.strip("/")
        os_path = self._get_os_path(path=path)
        return is_hidden(os_path, self.root_dir)

    def is_writable(self, path):
        """Does the API style path correspond to a writable directory or file?

        Parameters
        ----------
        path : str
            The path to check. This is an API path (`/` separated,
            relative to root_dir).

        Returns
        -------
        hidden : bool
            Whether the path exists and is writable.
        """
        path = path.strip("/")
        os_path = self._get_os_path(path=path)
        try:
            return os.access(os_path, os.W_OK)
        except OSError:
            logger.error("Failed to check write permissions on %s", os_path)
            return False

    def file_exists(self, path):
        """Returns True if the file exists, else returns False.

        API-style wrapper for os.path.isfile

        Parameters
        ----------
        path : str
            The relative path to the file (with '/' as separator)

        Returns
        -------
        exists : bool
            Whether the file exists.
        """
        path = path.strip("/")
        os_path = self._get_os_path(path)
        return os.path.isfile(os_path)

    def dir_exists(self, path):
        """Does the API-style path refer to an extant directory?

        API-style wrapper for os.path.isdir

        Parameters
        ----------
        path : str
            The path to check. This is an API path (`/` separated,
            relative to root_dir).

        Returns
        -------
        exists : bool
            Whether the path is indeed a directory.
        """
        path = path.strip("/")
        os_path = self._get_os_path(path=path)
        return os.path.isdir(os_path)

    def get(self, path, content=True, type=None, format=None, require_hash=False):
        """Takes a path for an entity and returns its model

        Parameters
        ----------
        path : str
            the API path that describes the relative path for the target
        content : bool
            Whether to include the contents in the reply
        type : str, optional
            The requested type - 'file', 'notebook', or 'directory'.
            Will raise HTTPError 400 if the content doesn't match.
        format : str, optional
            The requested format for file contents. 'text' or 'base64'.
            Ignored if this returns a notebook or directory model.
        require_hash: bool, optional
            Whether to include the hash of the file contents.

        Returns
        -------
        model : dict
            the contents model. If content=True, returns the contents
            of the file or directory as well.
        """
        path = path.strip("/")
        os_path = self._get_os_path(path)
        four_o_four = "file or directory does not exist: %r" % path

        if not self.exists(path):
            raise web.HTTPError(404, four_o_four)

        # if not self.allow_hidden and is_hidden(os_path, self.root_dir):
        #     self.log.info("Refusing to serve hidden file or directory %r, via 404 Error", os_path)
        #     raise web.HTTPError(404, four_o_four)

        if os.path.isdir(os_path):
            if type not in (None, "directory"):
                raise web.HTTPError(
                    400,
                    f"{path} is a directory, not a {type}",
                    reason="bad type",
                )
            model = self._dir_model(path, content=content)
        elif type == "notebook" or (type is None and path.endswith(".ipynb")):
            model = self._notebook_model(
                path, content=content, require_hash=require_hash
            )
        else:
            if type == "directory":
                raise web.HTTPError(
                    400, "%s is not a directory" % path, reason="bad type"
                )
            model = self._file_model(
                path, content=content, format=format, require_hash=require_hash
            )
        # self.emit(data={"action": "get", "path": path})
        return model

    def create_file(self, path):
        path = os.getcwd() + "/" + path
        with open(path, "a"):
            os.utime(path, None)

    def create_directory(self, path):
        basedir = os.path.dirname(path)
        if not os.path.exists(basedir):
            os.makedirs(basedir)

    def delete_file(self, path):
        """Delete file at path."""
        path = path.strip("/")
        os_path = self._get_os_path(path)
        rm = os.unlink

        if not self.allow_hidden and is_hidden(os_path, self.root_dir):
            raise web.HTTPError(400, f"Cannot delete file or directory {os_path!r}")

        four_o_four = "file or directory does not exist: %r" % path
        if not self.exists(path):
            raise web.HTTPError(404, four_o_four)

        def is_non_empty_dir(os_path):
            if os.path.isdir(os_path):
                # A directory containing only leftover checkpoints is
                # considered empty.
                cp_dir = getattr(self.checkpoints, "checkpoint_dir", None)
                if set(os.listdir(os_path)) - {cp_dir}:
                    return True

            return False

        if self.delete_to_trash:
            if not self.always_delete_dir and sys.platform == "win32" and is_non_empty_dir(os_path):
                # send2trash can really delete files on Windows, so disallow
                # deleting non-empty files. See Github issue 3631.
                raise web.HTTPError(400, "Directory %s not empty" % os_path)
            # send2trash now supports deleting directories. see #1290
            if not self.is_writable(path):
                raise web.HTTPError(403, "Permission denied: %s" % path) from None
            self.log.debug("Sending %s to trash", os_path)
            try:
                send2trash(os_path)
            except OSError as e:
                raise web.HTTPError(400, "send2trash failed: %s" % e) from e
            return

        if os.path.isdir(os_path):
            # Don't permanently delete non-empty directories.
            if not self.always_delete_dir and is_non_empty_dir(os_path):
                raise web.HTTPError(400, "Directory %s not empty" % os_path)
            self.log.debug("Removing directory %s", os_path)
            with self.perm_to_403():
                shutil.rmtree(os_path)
        else:
            self.log.debug("Unlinking file %s", os_path)
            with self.perm_to_403():
                rm(os_path)

    async def delete_file(self, path):
        """Delete file at path."""
        path = path.strip("/")
        os_path = self._get_os_path(path)
        rm = os.unlink

        # if not self.allow_hidden and is_hidden(os_path, self.root_dir):
        #     raise web.HTTPError(400, f"Cannot delete file or directory {os_path!r}")

        if not os.path.exists(os_path):
            raise web.HTTPError(404, "File or directory does not exist: %s" % os_path)

        async def is_non_empty_dir(os_path):
            if os.path.isdir(os_path):
                # A directory containing only leftover checkpoints is
                # considered empty.
                cp_dir = getattr(self.checkpoints, "checkpoint_dir", None)
                dir_contents = set(await run_sync(os.listdir, os_path))
                if dir_contents - {cp_dir}:
                    return True

            return False

        if self.delete_to_trash:
            if (
                    not self.always_delete_dir
                    and sys.platform == "win32"
                    and await is_non_empty_dir(os_path)
            ):
                # send2trash can really delete files on Windows, so disallow
                # deleting non-empty files. See Github issue 3631.
                raise web.HTTPError(400, "Directory %s not empty" % os_path)
            # send2trash now supports deleting directories. see #1290
            if not self.is_writable(path):
                raise web.HTTPError(403, "Permission denied: %s" % path) from None
            logger.debug("Sending %s to trash", os_path)
            try:
                send2trash(os_path)
            except OSError as e:
                raise web.HTTPError(400, "send2trash failed: %s" % e) from e
            return

        if os.path.isdir(os_path):
            # Don't permanently delete non-empty directories.
            if not self.always_delete_dir and await is_non_empty_dir(os_path):
                raise web.HTTPError(400, "Directory %s not empty" % os_path)
            self.log.debug("Removing directory %s", os_path)
            with self.perm_to_403():
                await run_sync(shutil.rmtree, os_path)
        else:
            self.log.debug("Unlinking file %s", os_path)
            with self.perm_to_403():
                await run_sync(rm, os_path)

    def rename_file(self, old_path, new_path):
        """Rename a file."""
        old_path = old_path.strip("/")
        new_path = new_path.strip("/")
        if new_path == old_path:
            return

        new_os_path = self._get_os_path(new_path)
        old_os_path = self._get_os_path(old_path)

        # if not self.allow_hidden and (
        #     is_hidden(old_os_path, self.root_dir) or is_hidden(new_os_path, self.root_dir)
        # ):
        #     raise web.HTTPError(400, f"Cannot rename file or directory {old_os_path!r}")

        # Should we proceed with the move?
        if os.path.exists(new_os_path) and not samefile(old_os_path, new_os_path):
            raise web.HTTPError(409, "File already exists: %s" % new_path)

        # Move the file
        try:
            with self.perm_to_403():
                shutil.move(old_os_path, new_os_path)
        except web.HTTPError:
            raise
        except Exception as e:
            raise web.HTTPError(500, f"Unknown error renaming file: {old_path} {e}") from e

    def dir_exists(self, path):
        """Does the API-style path refer to an extant directory?

        API-style wrapper for os.path.isdir

        Parameters
        ----------
        path : str
            The path to check. This is an API path (`/` separated,
            relative to root_dir).

        Returns
        -------
        exists : bool
            Whether the path is indeed a directory.
        """
        print(path)
        path = path.strip("/")
        os_path = self._get_os_path(path=path)
        return os.path.isdir(os_path)

    async def get_kernel_path(self, path, model=None):
        """Return the API path for the kernel

        KernelManagers can turn this value into a filesystem path,
        or ignore it altogether.

        The default value here will start kernels in the directory of the
        notebook server. FileContentsManager overrides this to use the
        directory containing the notebook.
        """
        if self.dir_exists(path):
            return path
        parent_dir = path.rsplit("/", 1)[0] if "/" in path else ""
        return parent_dir

    def _get_os_path(self, path):
        """Given an API path, return its file system path.

        Parameters
        ----------
        path : str
            The relative API path to the named file.

        Returns
        -------
        path : str
            Native, absolute OS path to for a file.

        Raises
        ------
        404: if path is outside root
        """
        # This statement can cause excessive logging, uncomment if necessary when troubleshooting.
        # self.log.debug("Reading path from disk: %s", path)
        root = os.path.abspath(self.root_dir)  # type:ignore[attr-defined]
        # to_os_path is not safe if path starts with a drive, since os.path.join discards first part
        if os.path.splitdrive(path)[0]:
            raise HTTPError(404, "%s is not a relative API path" % path)
        os_path = to_os_path(ApiPath(path), root)
        # validate os path
        # e.g. "foo\0" raises ValueError: embedded null byte
        try:
            os.lstat(os_path)
        except OSError:
            # OSError could be FileNotFound, PermissionError, etc.
            # those should raise (or not) elsewhere
            pass
        except ValueError:
            raise HTTPError(404, f"{path} is not a valid path") from None

        if not (os.path.abspath(os_path) + os.path.sep).startswith(root):
            raise HTTPError(404, "%s is outside root contents directory" % path)
        return os_path

    @contextmanager
    def perm_to_403(self, os_path=""):
        """context manager for turning permission errors into 403."""
        try:
            yield
        except OSError as e:
            if e.errno in {errno.EPERM, errno.EACCES}:
                # make 403 error message without root prefix
                # this may not work perfectly on unicode paths on Python 2,
                # but nobody should be doing that anyway.
                if not os_path:
                    os_path = e.filename or "unknown file"
                path = to_api_path(
                    os_path, root=self.root_dir
                )  # type:ignore[attr-defined]
                raise HTTPError(403, "Permission denied: %s" % path) from e
            else:
                raise

    @contextmanager
    def open(self, os_path, *args, **kwargs):
        """wrapper around io.open that turns permission errors into 403"""
        with self.perm_to_403(os_path), open(os_path, *args, **kwargs) as f:
            yield f

    @contextmanager
    def atomic_writing(self, os_path, *args, **kwargs):
        """wrapper around atomic_writing that turns permission errors to 403.
        Depending on flag 'use_atomic_writing', the wrapper perform an actual atomic writing or
        simply writes the file (whatever an old exists or not)"""
        with self.perm_to_403(os_path):
            # kwargs["log"] = self.log
            if self.use_atomic_writing:
                with atomic_writing(os_path, *args, **kwargs) as f:
                    yield f
            else:
                with _simple_writing(os_path, *args, **kwargs) as f:
                    yield f

    def _read_file(
            self, os_path: str, format: str | None, raw: bool = False
    ) -> tuple[str | bytes, str] | tuple[str | bytes, str, bytes]:
        """Read a non-notebook file.

        Parameters
        ----------
        os_path: str
            The path to be read.
        format: str
            If 'text', the contents will be decoded as UTF-8.
            If 'base64', the raw bytes contents will be encoded as base64.
            If 'byte', the raw bytes contents will be returned.
            If not specified, try to decode as UTF-8, and fall back to base64
        raw: bool
            [Optional] If True, will return as third argument the raw bytes content

        Returns
        -------
        (content, format, byte_content) It returns the content in the given format
        as well as the raw byte content.
        """
        if not os.path.isfile(os_path):
            raise HTTPError(400, "Cannot read non-file %s" % os_path)

        with self.open(os_path, "rb") as f:
            bcontent = f.read()

        if format == "byte":
            # Not for http response but internal use
            return (bcontent, "byte", bcontent) if raw else (bcontent, "byte")

        if format is None or format == "text":
            # Try to interpret as unicode if format is unknown or if unicode
            # was explicitly requested.
            try:
                return (
                    (bcontent.decode("utf8"), "text", bcontent)
                    if raw
                    else (
                        bcontent.decode("utf8"),
                        "text",
                    )
                )
            except UnicodeError as e:
                if format == "text":
                    raise HTTPError(
                        400,
                        "%s is not UTF-8 encoded" % os_path,
                        reason="bad format",
                    ) from e
        return (
            (encodebytes(bcontent).decode("ascii"), "base64", bcontent)
            if raw
            else (
                encodebytes(bcontent).decode("ascii"),
                "base64",
            )
        )

    def new(self, model=None, path=""):
        """Create a new file or directory and return its model with no content.

        To create a new untitled entity in a directory, use `new_untitled`.
        """
        path = path.strip("/")
        if model is None:
            model = {}

        if path.endswith(".ipynb"):
            model.setdefault("type", "notebook")
        else:
            model.setdefault("type", "file")

        # no content, not a directory, so fill out new-file model
        if "content" not in model and model["type"] != "directory":
            if model["type"] == "notebook":
                model["content"] = new_notebook()
                model["format"] = "json"
            else:
                model["content"] = ""
                model["type"] = "file"
                model["format"] = "text"

        model = self.save(model, path)
        return model

    def _save_directory(self, os_path, model, path=""):
        """create a directory"""
        if not self.allow_hidden and is_hidden(os_path, self.root_dir):
            raise web.HTTPError(400, "Cannot create directory %r" % os_path)
        if not os.path.exists(os_path):
            with self.perm_to_403():
                os.mkdir(os_path)
        elif not os.path.isdir(os_path):
            raise web.HTTPError(400, "Not a directory: %s" % (os_path))
        else:
            logger.debug("Directory %r already exists", os_path)

    def _save_file(self, os_path, content, format):
        """Save content of a generic file."""
        if format not in {"text", "base64"}:
            raise HTTPError(
                400,
                "Must specify format of file contents as 'text' or 'base64'",
            )
        try:
            if format == "text":
                bcontent = content.encode("utf8")
            else:
                b64_bytes = content.encode("ascii")
                bcontent = decodebytes(b64_bytes)
        except Exception as e:
            raise HTTPError(400, f"Encoding error saving {os_path}: {e}") from e

        with self.atomic_writing(os_path, text=False) as f:
            f.write(bcontent)

    def run_pre_save_hooks(self, model, path, **kwargs):
        """Run the pre-save hooks if any, and log errors"""
        pre_save_hooks = [self.pre_save_hook] if self.pre_save_hook is not None else []
        pre_save_hooks += self._pre_save_hooks
        for pre_save_hook in pre_save_hooks:
            try:
                self.log.debug("Running pre-save hook on %s", path)
                pre_save_hook(model=model, path=path, contents_manager=self, **kwargs)
            except HTTPError:
                # allow custom HTTPErrors to raise,
                # rejecting the save with a message.
                raise
            except Exception:
                # unhandled errors don't prevent saving,
                # which could cause frustrating data loss
                self.log.error(
                    "Pre-save hook %s failed on %s",
                    pre_save_hook.__name__,
                    path,
                    exc_info=True,
                )
    def check_and_sign(self, nb, path=""):
        """Check for trusted cells, and sign the notebook.

        Called as a part of saving notebooks.

        Parameters
        ----------
        nb : dict
            The notebook dict
        path : str
            The notebook's path (for logging)
        """
        if self.notary.check_cells(nb):
            self.notary.sign(nb)
        else:
            self.log.warning("Notebook %s is not trusted", path)

    def save(self, model, path=""):
        """Save the file model and return the model with no content."""
        path = path.strip("/")

        self.run_pre_save_hooks(model=model, path=path)

        if "type" not in model:
            raise web.HTTPError(400, "No file type provided")
        if "content" not in model and model["type"] != "directory":
            raise web.HTTPError(400, "No file content provided")
        os_path = self._get_os_path(path)

        # if not self.allow_hidden and is_hidden(os_path, self.root_dir):
        #     raise web.HTTPError(400, f"Cannot create file or directory {os_path!r}")

        logger.debug("Saving %s", os_path)

        validation_error: dict[str, t.Any] = {}
        print("model is => ", model['content'])
        try:
            if model["type"] == "notebook":
                nb = nbformat.from_dict(model["content"])
                self.check_and_sign(nb, path)
                self._save_notebook(
                    os_path, nb, capture_validation_error=validation_error
                )
                # One checkpoint should always exist for notebooks.
                # if not self.checkpoints.list_checkpoints(path):
                #     self.create_checkpoint(path)
            elif model["type"] == "file":
                # Missing format will be handled internally by _save_file.
                self._save_file(os_path, model["content"], model.get("format"))
            elif model["type"] == "directory":
                self._save_directory(os_path, model, path)
            else:
                raise web.HTTPError(400, "Unhandled contents type: %s" % model["type"])
        except web.HTTPError:
            raise
        except Exception as e:
            logger.error("Error while saving file: %s %s", path, e, exc_info=True)
            raise web.HTTPError(
                500, f"Unexpected error while saving file: {path} {e}"
            ) from e

        validation_message = None
        if model["type"] == "notebook":
            self.validate_notebook_model(model, validation_error=validation_error)
            validation_message = model.get("message", None)

        model = self.get(path, content=False)
        if validation_message:
            model["message"] = validation_message

        # self.run_post_save_hooks(model=model, os_path=os_path)
        # self.emit(data={"action": "save", "path": path})
        return model


    def validate_notebook_model(self, model, validation_error=None):
        """Add failed-validation message to model"""
        try:
            # If we're given a validation_error dictionary, extract the exception
            # from it and raise the exception, else call nbformat's validate method
            # to determine if the notebook is valid.  This 'else' condition may
            # pertain to server extension not using the server's notebook read/write
            # functions.
            if validation_error is not None:
                e = validation_error.get("ValidationError")
                if isinstance(e, ValidationError):
                    raise e
            else:
                validate_nb(model["content"])
        except ValidationError as e:
            model["message"] = "Notebook validation failed: {}:\n{}".format(
                str(e),
                json.dumps(e.instance, indent=1, default=lambda obj: "<UNKNOWN>"),
            )
        return model

    def new_untitled(self, path="", type="", ext=""):
        """Create a new untitled file or directory in path

        path must be a directory

        File extension can be specified.

        Use `new` to create files with a fully specified path (including filename).
        """
        path = path.strip("/")

        if not self.dir_exists(path):
            raise HTTPError(404, "No such directory: %s" % path)

        model = {}
        if type:
            model["type"] = type

        if ext == ".ipynb":
            model.setdefault("type", "notebook")
        else:
            model.setdefault("type", "file")

        insert = ""
        if model["type"] == "directory":
            untitled = self.untitled_directory
            insert = " "
        elif model["type"] == "notebook":
            untitled = self.untitled_notebook
            ext = ".ipynb"
        elif model["type"] == "file":
            untitled = self.untitled_file
        else:
            raise HTTPError(400, "Unexpected model type: %r" % model["type"])

        name = self.increment_filename(untitled + ext, path, insert=insert)
        path = f"{path}/{name}"
        return self.new(model, path)

    def increment_filename(self, filename, path="", insert=""):
        """Increment a filename until it is unique.

        Parameters
        ----------
        filename : unicode
            The name of a file, including extension
        path : unicode
            The API path of the target's directory
        insert : unicode
            The characters to insert after the base filename

        Returns
        -------
        name : unicode
            A filename that is unique, based on the input filename.
        """
        # Extract the full suffix from the filename (e.g. .tar.gz)
        path = path.strip("/")
        basename, dot, ext = filename.rpartition(".")
        if ext != "ipynb":
            basename, dot, ext = filename.partition(".")

        suffix = dot + ext

        for i in itertools.count():
            insert_i = f"{insert}{i}" if i else ""
            name = f"{basename}{insert_i}{suffix}"
            if not self.exists(f"{path}/{name}"):
                break
        return name

    def rename(self, old_path, new_path):
        """Rename a file and any checkpoints associated with that file."""
        self.rename_file(old_path, new_path)
        # self.checkpoints.rename_all_checkpoints(old_path, new_path)
        # self.emit(data={"action": "rename", "path": new_path, "source_path": old_path})

    async def delete(self, path):
        """Delete a file/directory and any associated checkpoints."""
        path = path.strip("/")
        if not path:
            raise HTTPError(400, "Can't delete root")
        await self.delete_file(path)
        # self.checkpoints.delete_all_checkpoints(path)
        # self.emit(data={"action": "delete", "path": path})

    def update(self, model, path):
        """Update the file's path

        For use in PATCH requests, to enable renaming a file without
        re-uploading its contents. Only used for renaming at the moment.
        """
        path = path.strip("/")
        new_path = model.get("path", path).strip("/")
        if path != new_path:
            self.rename(path, new_path)
        model = self.get(new_path, content=False)
        return model

    def create_checkpoint(self, path):
        pass

    def _base_model(self, path):
        """Build the common base of a contents model"""
        os_path = self._get_os_path(path)
        info = os.lstat(os_path)

        four_o_four = "file or directory does not exist: %r" % path

        # if not self.allow_hidden and is_hidden(os_path, self.root_dir):
        #     self.log.info("Refusing to serve hidden file or directory %r, via 404 Error", os_path)
        #     raise web.HTTPError(404, four_o_four)

        try:
            # size of file
            size = info.st_size
        except (ValueError, OSError):
            logger.warning("Unable to get size.")
            size = None

        # try:
        #     last_modified = tz.utcfromtimestamp(info.st_mtime)
        # except (ValueError, OSError):
        #     # Files can rarely have an invalid timestamp
        #     # https://github.com/jupyter/notebook/issues/2539
        #     # https://github.com/jupyter/notebook/issues/2757
        #     # Use the Unix epoch as a fallback so we don't crash.
        #     logger.warning("Invalid mtime %s for %s", info.st_mtime, os_path)
        #     last_modified = datetime(1970, 1, 1, 0, 0, tzinfo=tz.UTC)

        # try:
        #     created = tz.utcfromtimestamp(info.st_ctime)
        # except (ValueError, OSError):  # See above
        #     logger.warning("Invalid ctime %s for %s", info.st_ctime, os_path)
        #     # created = datetime(1970, 1, 1, 0, 0, tzinfo=tz.UTC)

        # Create the base model.
        model = {}
        model["name"] = path.rsplit("/", 1)[-1]
        model["path"] = path
        model["last_modified"] = ""  # last_modified
        model["created"] = ""  # created
        model["content"] = None
        model["format"] = None
        model["mimetype"] = None
        model["size"] = size
        model["writable"] = self.is_writable(path)
        model["hash"] = None
        model["hash_algorithm"] = None

        return model

    def _dir_model(self, path, content=True):
        """Build a model for a directory

        if content is requested, will include a listing of the directory
        """
        os_path = self._get_os_path(path)

        four_o_four = "directory does not exist: %r" % path

        if not os.path.isdir(os_path):
            raise web.HTTPError(404, four_o_four)
        # elif not self.allow_hidden and is_hidden(os_path, self.root_dir):
        #     self.log.info("Refusing to serve hidden directory %r, via 404 Error", os_path)
        #     raise web.HTTPError(404, four_o_four)

        model = self._base_model(path)
        model["type"] = "directory"
        model["size"] = None
        if content:
            model["content"] = contents = []
            os_dir = self._get_os_path(path)
            print(os_dir)
            for name in os.listdir(os_dir):
                try:
                    os_path = os.path.join(os_dir, name)
                except UnicodeDecodeError as e:
                    logger.warning("failed to decode filename '%s': %r", name, e)
                    continue

                try:
                    st = os.lstat(os_path)
                except OSError as e:
                    # skip over broken symlinks in listing
                    if e.errno == errno.ENOENT:
                        logger.warning("%s doesn't exist", os_path)
                    elif (
                            e.errno != errno.EACCES
                    ):  # Don't provide clues about protected files
                        logger.warning("Error stat-ing %s: %r", os_path, e)
                    continue

                if (
                        not stat.S_ISLNK(st.st_mode)
                        and not stat.S_ISREG(st.st_mode)
                        and not stat.S_ISDIR(st.st_mode)
                ):
                    logger.debug("%s not a regular file", os_path)
                    continue
                contents.append(self.get(path=f"{path}/{name}", content=False))
                # try:
                #     if self.should_list(name) and (
                #             self.allow_hidden or not is_file_hidden(os_path, stat_res=st)
                #     ):
                #         contents.append(self.get(path=f"{path}/{name}", content=False))
                # except OSError as e:
                #     # ELOOP: recursive symlink, also don't show failure due to permissions
                #     if e.errno not in [errno.ELOOP, errno.EACCES]:
                #         self.log.warning(
                #             "Unknown error checking if file %r is hidden",
                #             os_path,
                #             exc_info=True,
                #         )

            model["format"] = "json"

        return model

    def _file_model(self, path, content=True, format=None, require_hash=False):
        """Build a model for a file

        if content is requested, include the file contents.

        format:
          If 'text', the contents will be decoded as UTF-8.
          If 'base64', the raw bytes contents will be encoded as base64.
          If not specified, try to decode as UTF-8, and fall back to base64

        if require_hash is true, the model will include 'hash'
        """
        model = self._base_model(path)
        model["type"] = "file"

        os_path = self._get_os_path(path)
        model["mimetype"] = mimetypes.guess_type(os_path)[0]

        bytes_content = None
        if content:
            content, format, bytes_content = self._read_file(os_path, format, raw=True)  # type: ignore[misc]
            if model["mimetype"] is None:
                default_mime = {
                    "text": "text/plain",
                    "base64": "application/octet-stream",
                }[format]
                model["mimetype"] = default_mime

            model.update(
                content=content,
                format=format,
            )

        if require_hash:
            if bytes_content is None:
                bytes_content, _ = self._read_file(os_path, "byte")  # type: ignore[assignment,misc]
            model.update(**self._get_hash(bytes_content))  # type: ignore[arg-type]

        return model

    def _notebook_model(self, path, content=True, require_hash=False):
        """Build a notebook model

        if content is requested, the notebook content will be populated
        as a JSON structure (not double-serialized)

        if require_hash is true, the model will include 'hash'
        """
        model = self._base_model(path)
        model["type"] = "notebook"
        os_path = self._get_os_path(path)

        bytes_content = None
        if content:
            validation_error: dict[str, t.Any] = {}
            nb, bytes_content = self._read_notebook(
                os_path,
                as_version=4,
                capture_validation_error=validation_error,
                raw=True,
            )
            self.mark_trusted_cells(nb, path)
            model["content"] = nb
            model["format"] = "json"
            self.validate_notebook_model(model, validation_error)

        if require_hash:
            if bytes_content is None:
                bytes_content, _ = self._read_file(os_path, "byte")  # type: ignore[misc]
            model.update(**self._get_hash(bytes_content))  # type: ignore[arg-type]

        return model

    def mark_trusted_cells(self, nb, path=""):
        """Mark cells as trusted if the notebook signature matches.

        Called as a part of loading notebooks.

        Parameters
        ----------
        nb : dict
            The notebook object (in current nbformat)
        path : str
            The notebook's path (for logging)
        """
        trusted = self.notary.check_signature(nb)
        if not trusted:
            logger.warning("Notebook %s is not trusted", path)
        self.notary.mark_cells(nb, trusted)

    def _save_directory(self, os_path, model, path=""):
        """create a directory"""
        if not self.allow_hidden and is_hidden(os_path, self.root_dir):
            raise web.HTTPError(400, "Cannot create directory %r" % os_path)
        if not os.path.exists(os_path):
            with self.perm_to_403():
                os.mkdir(os_path)
        elif not os.path.isdir(os_path):
            raise web.HTTPError(400, "Not a directory: %s" % (os_path))
        else:
            logger.debug("Directory %r already exists", os_path)

    def _read_notebook(
            self, os_path, as_version=4, capture_validation_error=None, raw: bool = False
    ):
        """Read a notebook from an os path."""
        answer = self._read_file(os_path, "text", raw=raw)

        try:
            nb = nbformat.reads(
                answer[0],
                as_version=as_version,
                capture_validation_error=capture_validation_error,
            )

            return (nb, answer[2]) if raw else nb  # type:ignore[misc]
        except Exception as e:
            e_orig = e

        # If use_atomic_writing is enabled, we'll guess that it was also
        # enabled when this notebook was written and look for a valid
        # atomic intermediate.
        tmp_path = path_to_intermediate(os_path)

        if not self.use_atomic_writing or not os.path.exists(tmp_path):
            raise HTTPError(
                400,
                f"Unreadable Notebook: {os_path} {e_orig!r}",
            )

        # Move the bad file aside, restore the intermediate, and try again.
        invalid_file = path_to_invalid(os_path)
        replace_file(os_path, invalid_file)
        replace_file(tmp_path, os_path)
        return self._read_notebook(
            os_path, as_version, capture_validation_error=capture_validation_error, raw=raw
        )

    def _save_notebook(self, os_path, nb, capture_validation_error=None):
        """Save a notebook to an os_path."""
        with self.atomic_writing(os_path, encoding="utf-8") as f:
            nbformat.write(
                nb,
                f,
                version=nbformat.NO_CONVERT,
                capture_validation_error=capture_validation_error,
            )

    def restore_checkpoint(self, path, checkpoint_id):
        pass

    def list_checkpoints(self, path):
        pass

    def delete_checkpoints(self, path, checkpoint_id):
        pass


@contextmanager
def atomic_writing(path, text=True, encoding="utf-8", log=None, **kwargs):
    """Context manager to write to a file only if the entire write is successful.

    This works by copying the previous file contents to a temporary file in the
    same directory, and renaming that file back to the target if the context
    exits with an error. If the context is successful, the new data is synced to
    disk and the temporary file is removed.

    Parameters
    ----------
    path : str
        The target file to write to.
    text : bool, optional
        Whether to open the file in text mode (i.e. to write unicode). Default is
        True.
    encoding : str, optional
        The encoding to use for files opened in text mode. Default is UTF-8.
    **kwargs
        Passed to :func:`io.open`.
    """
    # realpath doesn't work on Windows: https://bugs.python.org/issue9949
    # Luckily, we only need to resolve the file itself being a symlink, not
    # any of its directories, so this will suffice:
    if os.path.islink(path):
        path = os.path.join(os.path.dirname(path), os.readlink(path))

    tmp_path = path_to_intermediate(path)

    if os.path.isfile(path):
        copy2_safe(path, tmp_path, log=log)

    if text:
        # Make sure that text files have Unix linefeeds by default
        kwargs.setdefault("newline", "\n")
        fileobj = open(path, "w", encoding=encoding, **kwargs)  # noqa: SIM115
    else:
        fileobj = open(path, "wb", **kwargs)  # noqa: SIM115

    try:
        yield fileobj
    except BaseException:
        # Failed! Move the backup file back to the real path to avoid corruption
        fileobj.close()
        replace_file(tmp_path, path)
        raise

    # Flush to disk
    fileobj.flush()
    os.fsync(fileobj.fileno())
    fileobj.close()

    # Written successfully, now remove the backup copy
    if os.path.isfile(tmp_path):
        os.remove(tmp_path)


@contextmanager
def _simple_writing(path, text=True, encoding="utf-8", log=None, **kwargs):
    """Context manager to write file without doing atomic writing
    (for weird filesystem eg: nfs).

    Parameters
    ----------
    path : str
        The target file to write to.
    text : bool, optional
        Whether to open the file in text mode (i.e. to write unicode). Default is
        True.
    encoding : str, optional
        The encoding to use for files opened in text mode. Default is UTF-8.
    **kwargs
        Passed to :func:`io.open`.
    """
    # realpath doesn't work on Windows: https://bugs.python.org/issue9949
    # Luckily, we only need to resolve the file itself being a symlink, not
    # any of its directories, so this will suffice:
    if os.path.islink(path):
        path = os.path.join(os.path.dirname(path), os.readlink(path))

    if text:
        # Make sure that text files have Unix linefeeds by default
        kwargs.setdefault("newline", "\n")
        fileobj = open(path, "w", encoding=encoding, **kwargs)  # noqa: SIM115
    else:
        fileobj = open(path, "wb", **kwargs)  # noqa: SIM115

    try:
        yield fileobj
    except BaseException:
        fileobj.close()
        raise

    fileobj.close()


def path_to_intermediate(path):
    """Name of the intermediate file used in atomic writes.

    The .~ prefix will make Dropbox ignore the temporary file."""
    dirname, basename = os.path.split(path)
    return os.path.join(dirname, ".~" + basename)


def path_to_invalid(path):
    """Name of invalid file after a failed atomic write and subsequent read."""
    dirname, basename = os.path.split(path)
    return os.path.join(dirname, basename + ".invalid")


def replace_file(src, dst):
    """replace dst with src"""
    os.replace(src, dst)


async def async_replace_file(src, dst):
    """replace dst with src asynchronously"""
    await run_sync(os.replace, src, dst)
