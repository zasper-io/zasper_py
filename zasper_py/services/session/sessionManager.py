# https://github.com/jupyter-server/jupyter_server/blob/main/jupyter_server/services/sessions/sessionmanager.py
import logging
import os
import sqlite3
import uuid
from dataclasses import dataclass, fields
from typing import Any, Dict, List, NewType, Optional, Union, cast

from pydantic import BaseModel
from tornado import web

from zasper_backend.models.sessionModel import SessionModel
from zasper_backend.services.content.contentsManager import ContentsManager
from zasper_backend.services.kernels.multiKernelManager import \
    MultiKernelManager
from zasper_backend.utils import ensure_async

KernelName = NewType("KernelName", str)
ModelName = NewType("ModelName", str)

logger = logging.getLogger(__name__)


class KernelSessionRecordConflict(Exception):
    """Exception class to use when two KernelSessionRecords cannot
    merge because of conflicting data.
    """


# class KernelSessionRecord(BaseModel):
#     """A record object for tracking a Jupyter Server Kernel Session.

#     Two records that share a session_id must also share a kernel_id, while
#     kernels can have multiple session (and thereby) session_ids
#     associated with them.
#     """


#     session_id: Optional[str] = None
#     kernel_id: Optional[str] = None
@dataclass
class KernelSessionRecord:
    """A record object for tracking a Jupyter Server Kernel Session.

    Two records that share a session_id must also share a kernel_id, while
    kernels can have multiple session (and thereby) session_ids
    associated with them.
    """

    session_id: Optional[str] = None
    kernel_id: Optional[str] = None

    def __eq__(self, other: object) -> bool:
        """Whether a record equals another."""
        if isinstance(other, KernelSessionRecord):
            condition1 = self.kernel_id and self.kernel_id == other.kernel_id
            condition2 = all(
                [
                    self.session_id == other.session_id,
                    self.kernel_id is None or other.kernel_id is None,
                ]
            )
            if any([condition1, condition2]):
                return True
            # If two records share session_id but have different kernels, this is
            # and ill-posed expression. This should never be true. Raise an exception
            # to inform the user.
            if all(
                [
                    self.session_id,
                    self.session_id == other.session_id,
                    self.kernel_id != other.kernel_id,
                ]
            ):
                msg = (
                    "A single session_id can only have one kernel_id "
                    "associated with. These two KernelSessionRecords share the same "
                    "session_id but have different kernel_ids. This should "
                    "not be possible and is likely an issue with the session "
                    "records."
                )
                raise KernelSessionRecordConflict(msg)
        return False

    def update(self, other: "KernelSessionRecord") -> None:
        """Updates in-place a kernel from other (only accepts positive updates"""
        if not isinstance(other, KernelSessionRecord):
            msg = (
                "'other' must be an instance of KernelSessionRecord."
            )  # type:ignore[unreachable]
            raise TypeError(msg)

        if other.kernel_id and self.kernel_id and other.kernel_id != self.kernel_id:
            msg = "Could not update the record from 'other' because the two records conflict."
            raise KernelSessionRecordConflict(msg)

        for field in fields(self):
            if hasattr(other, field.name) and getattr(other, field.name):
                setattr(self, field.name, getattr(other, field.name))


class KernelSessionRecordList:
    """An object for storing and managing a list of KernelSessionRecords.

    When adding a record to the list, the KernelSessionRecordList
    first checks if the record already exists in the list. If it does,
    the record will be updated with the new information; otherwise,
    it will be appended.
    """

    _records: List[KernelSessionRecord]

    def __init__(self, *records: KernelSessionRecord):
        """Initialize a record list."""
        self._records = []
        for record in records:
            self.update(record)

    def __str__(self):
        """The string representation of a record list."""
        return str(self._records)

    def __contains__(self, record: Union[KernelSessionRecord, str]) -> bool:
        """Search for records by kernel_id and session_id"""
        if isinstance(record, KernelSessionRecord) and record in self._records:
            return True

        if isinstance(record, str):
            for r in self._records:
                if record in [r.session_id, r.kernel_id]:
                    return True
        return False

    def __len__(self):
        """The length of the record list."""
        return len(self._records)

    def get(self, record: Union[KernelSessionRecord, str]) -> KernelSessionRecord:
        """Return a full KernelSessionRecord from a session_id, kernel_id, or
        incomplete KernelSessionRecord.
        """
        if isinstance(record, str):
            for r in self._records:
                if record in (r.kernel_id, r.session_id):
                    return r
        elif isinstance(record, KernelSessionRecord):
            for r in self._records:
                if record == r:
                    return record
        msg = f"{record} not found in KernelSessionRecordList."
        raise ValueError(msg)

    def update(self, record: KernelSessionRecord) -> None:
        """Update a record in-place or append it if not in the list."""
        try:
            idx = self._records.index(record)
            self._records[idx].update(record)
        except ValueError:
            self._records.append(record)

    def remove(self, record: KernelSessionRecord) -> None:
        """Remove a record if its found in the list. If it's not found,
        do nothing.
        """
        if record in self._records:
            self._records.remove(record)


class SessionManager:
    _cursor = None
    _connection = None
    database_filepath = "/home/prasun/dev/proj/data.sql"
    _columns = {"session_id", "path", "name", "type", "kernel_id"}

    def __init__(self):
        self._pending_sessions = KernelSessionRecordList()
        self.kernel_manager = MultiKernelManager()
        self.contents_manager = ContentsManager()
        print("session manager is initialized")

    async def list_sessions(self):
        """Returns a list of dictionaries containing all the information from
        the session database"""
        c = self.cursor.execute("SELECT * FROM session")
        result = []
        # We need to use fetchall() here, because row_to_model can delete rows,
        # which messes up the cursor if we're iterating over rows.
        for row in c.fetchall():
            try:
                model = await self.row_to_model(row)
                result.append(model)
            except KeyError:
                pass
        return result

    async def kernel_culled(self, kernel_id: str) -> bool:
        """Checks if the kernel is still considered alive and returns true if its not found."""
        return kernel_id not in self.kernel_manager

    async def row_to_model(self, row, tolerate_culled=False):
        """Takes sqlite database session row and turns it into a dictionary"""
        kernel_culled: bool = await self.kernel_culled(row["kernel_id"])
        if kernel_culled:
            # The kernel was culled or died without deleting the session.
            # We can't use delete_session here because that tries to find
            # and shut down the kernel - so we'll delete the row directly.
            #
            # If caller wishes to tolerate culled kernels, log a warning
            # and return None.  Otherwise, raise KeyError with a similar
            # message.
            self.cursor.execute(
                "DELETE FROM session WHERE session_id=?", (row["session_id"],)
            )
            msg = (
                "Kernel '{kernel_id}' appears to have been culled or died unexpectedly, "
                "invalidating session '{session_id}'. The session has been removed.".format(
                    kernel_id=row["kernel_id"], session_id=row["session_id"]
                )
            )
            if tolerate_culled:
                logger.log(f"{msg}  Continuing...")
                return None
            raise KeyError(msg)

        kernel_model = await ensure_async(self.kernel_manager.kernel_model(row["kernel_id"]))
        model = {
            "id": row["session_id"],
            "path": row["path"],
            "name": row["name"],
            "type": row["type"],
            "kernel": kernel_model,
        }
        if row["type"] == "notebook":
            # Provide the deprecated API.
            model["notebook"] = {"path": row["path"], "name": row["name"]}
        return model

    @property
    def cursor(self):
        """Start a cursor and create a database called 'session'"""
        if self._cursor is None:
            self._cursor = self.connection.cursor()
            self._cursor.execute(
                """CREATE TABLE IF NOT EXISTS session
                (session_id, path, name, type, kernel_id)"""
            )
        return self._cursor

    @property
    def connection(self):
        """Start a database connection"""
        if self._connection is None:
            # Set isolation level to None to autocommit all changes to the database.
            self._connection = sqlite3.connect(
                self.database_filepath, isolation_level=None
            )
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def close(self):
        """Close the sqlite connection"""
        if self._cursor is not None:
            self._cursor.close()
            self._cursor = None

    async def create_session(
        self,
        path: Optional[str] = None,
        name: Optional[ModelName] = None,
        type: Optional[str] = None,
        kernel_name: Optional[KernelName] = None,
        kernel_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates a session and returns its model

        Parameters
        ----------
        name: ModelName(str)
            Usually the model name, like the filename associated with current
            kernel.
        """
        session_id = str(uuid.uuid4())
        logger.info("Creating kernel record")
        record = KernelSessionRecord(session_id=session_id, kernel_id=None)

        self._pending_sessions.update(record)
        print("=============================================")
        print("self._pending_sessions =>", self._pending_sessions)
        print("=============================================")
        if kernel_id is not None and kernel_id in self.kernel_manager:
            pass
        else:
            kernel_id = await self.start_kernel_for_session(
                session_id, path, name, type, kernel_name
            )
        record.kernel_id = kernel_id
        self._pending_sessions.update(record)
        print("=============================================")
        print("kernel_id =>", kernel_id)
        print("=============================================")
        result = await self.save_session(
            session_id, path=path, name=name, type=type, kernel_id=kernel_id
        )
        self._pending_sessions.remove(record)
        print("=============================================")
        print("result =>", result)
        print("=============================================")
        return cast(Dict[str, Any], result)

    async def start_kernel_for_session(
        self,
        session_id: str,
        path: Optional[str],
        name: Optional[ModelName],
        type: Optional[str],
        kernel_name: Optional[KernelName],
    ) -> str:
        """Start a new kernel for a given session.

        Parameters
        ----------
        session_id : str
            uuid for the session; this method must be given a session_id
        path : str
            the path for the given session - seem to be a session id sometime.
        name : str
            Usually the model name, like the filename associated with current
            kernel.
        type : str
            the type of the session
        kernel_name : str
            the name of the kernel specification to use.  The default kernel name will be used if not provided.
        """
        # allow contents manager to specify kernels cwd
        kernel_path = await self.contents_manager.get_kernel_path(path=path)

        kernel_env = self.get_kernel_env(path, name)
        logger.info("starting kernel")
        kernel_id = await self.kernel_manager.start_kernel(
            path=kernel_path,
            kernel_name=kernel_name,
            env=kernel_env,
        )
        return cast(str, kernel_id)

    def get_kernel_env(
        self, path: Optional[str], name: Optional[ModelName] = None
    ) -> Dict[str, str]:
        """Return the environment variables that need to be set in the kernel

        Parameters
        ----------
        path : str
            the url path for the given session.
        name: ModelName(str), optional
            Here the name is likely to be the name of the associated file
            with the current kernel at startup time.
        """
        if name is not None:
            cwd = self.kernel_manager.cwd_for_path(path)
            path = os.path.join(cwd, name)
        assert isinstance(path, str)
        return {**os.environ, "JPY_SESSION_NAME": path}

    async def save_session(
        self, session_id, path=None, name=None, type=None, kernel_id=None
    ):
        """Saves the items for the session with the given session_id

        Given a session_id (and any other of the arguments), this method
        creates a row in the sqlite session database that holds the information
        for a session.

        Parameters
        ----------
        session_id : str
            uuid for the session; this method must be given a session_id
        path : str
            the path for the given session
        name : str
            the name of the session
        type : str
            the type of the session
        kernel_id : str
            a uuid for the kernel associated with this session

        Returns
        -------
        model : dict
            a dictionary of the session model
        """
        self.cursor.execute(
            "INSERT INTO session VALUES (?,?,?,?,?)",
            (session_id, path, name, type, kernel_id),
        )
        # logger.info("saving session")
        # data = {
        #     "session_id": session_id,
        #     "path": path,
        #     "name": name,
        #     "type": type,
        #     "kernel_id": kernel_id,
        # }
        # logger.info(data)
        result = await self.get_session(session_id=session_id)
        return result

    async def get_session(self, **kwargs):
        """Returns the model for a particular session.

        Takes a keyword argument and searches for the value in the session
        database, then returns the rest of the session's info.

        Parameters
        ----------
        **kwargs : dict
            must be given one of the keywords and values from the session database
            (i.e. session_id, path, name, type, kernel_id)

        Returns
        -------
        model : dict
            returns a dictionary that includes all the information from the
            session described by the kwarg.
        """
        if not kwargs:
            msg = "must specify a column to query"
            raise TypeError(msg)
        print("kwards =>", kwargs)
        conditions = []
        for column in kwargs:
            if column not in self._columns:
                msg = f"No such column: {column}"
                raise TypeError(msg)
            conditions.append("%s=?" % column)

        query = "SELECT * FROM session WHERE %s" % (
            " AND ".join(conditions)
        )  # noqa: S608

        self.cursor.execute(query, list(kwargs.values()))
        try:
            row = self.cursor.fetchone()
        except KeyError:
            # The kernel is missing, so the session just got deleted.
            row = None
        print("row", row)

        if row is None:
            q = []
            for key, value in kwargs.items():
                q.append(f"{key}={value!r}")

            raise web.HTTPError(404, "Session not found: %s" % (", ".join(q)))


        try:
            model = await self.row_to_model(row)
        except KeyError as e:
            raise web.HTTPError(404, "Session not found: %s" % str(e)) from e
        print("model=>", model)
        return model
