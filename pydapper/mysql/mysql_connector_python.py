from typing import TYPE_CHECKING
from typing import Any
from typing import ClassVar

from pydapper.capabilities import AdapterCapability
from pydapper.commands import _MAPPER_UNSET
from pydapper.commands import _MODEL_UNSET
from pydapper.commands import _PARAM_ALIAS_UNSET
from pydapper.commands import Commands
from pydapper.commands import _project_row
from pydapper.commands import _raise_if_list_params_for_read
from pydapper.commands import _resolve_row_projector

from ..exceptions import NoResultException
from ..utils import get_col_names
from ..utils import import_dbapi_module
from ..utils import validate_no_duplicate_columns

if TYPE_CHECKING:
    from ..dsn_parser import PydapperParseResult
    from ..types import CursorType


_UNSET = object()


def _resolve_client_flags(mysql: Any, caller_value: Any) -> Any:
    """Clear ``CLIENT_MULTI_STATEMENTS`` from the flags pydapper negotiates at connect time.

    pydapper refuses multi-statement SQL before the driver is reached, so the capability is denied on
    the wire too. The driver's setter treats a positive ``int`` as a wholesale replacement of its
    default and a ``list``/``tuple`` as an ordered sequence applied over the current value, so an
    ``int`` is masked rather than list-wrapped.

    The critical constraint is that the result must never be **falsy**. ``MySQLConnectionAbstract.config``
    resolves the option as ``config["client_flags"] or ClientFlag.get_default()``, and the default has
    ``MULTI_STATEMENTS`` set, so any falsy value silently re-enables the very capability this denies --
    and never reaches the setter that would otherwise have rejected it. The driver's own
    ``DEFAULT_CONFIGURATION["client_flags"]`` is ``0``, so falsy values are not hypothetical.
    """
    multi_statements = mysql.constants.ClientFlag.MULTI_STATEMENTS

    # `None` and `0` are both the driver's own spelling of "use the default"
    if caller_value is _UNSET or caller_value is None:
        return [-multi_statements]

    if isinstance(caller_value, (list, tuple)):
        return [*caller_value, -multi_statements]

    if isinstance(caller_value, int):
        if caller_value == 0:
            return [-multi_statements]

        if caller_value < 0:
            # truthy, so it reaches the driver's setter, which rejects it; that error is the driver's
            return caller_value

        resolved = caller_value & ~multi_statements
        if resolved == 0:
            raise ValueError(
                "client_flags requested CLIENT_MULTI_STATEMENTS and nothing else, which pydapper does "
                "not negotiate. Clearing it would leave no flags, and mysql-connector-python reads an "
                "empty client_flags as 'use the driver default', which enables it again. Pass other "
                "flags alongside it, or open the connection yourself and use pydapper.using()."
            )
        return resolved

    if not caller_value:
        raise ValueError(
            f"client_flags={caller_value!r} is not a supported value. mysql-connector-python reads a "
            "falsy client_flags as 'use the driver default', which enables CLIENT_MULTI_STATEMENTS; "
            "pydapper does not negotiate it. Pass an int, list, or tuple of ClientFlag values."
        )

    # truthy and unsupported: the driver raises its own ProgrammingError
    return caller_value


def _discard_unread_result(cursor: "CursorType") -> None:
    reset = getattr(cursor, "reset", None)
    if callable(reset):
        try:
            try:
                reset(free=True)
            except TypeError:
                reset()
        except Exception:
            pass

    connection = getattr(cursor, "_connection", None)
    has_unread_result = getattr(cursor, "unread_result", False) or (
        connection is not None and getattr(connection, "unread_result", False)
    )
    if not has_unread_result:
        return

    # Pure mysql-connector-python has no no-drain discard API. Once the second
    # row proves this is an error, drain the remainder so the connection stays usable.
    try:
        cursor.fetchall()
        return
    except Exception:
        pass

    consume_results = getattr(connection, "consume_results", None)
    if callable(consume_results):
        try:
            consume_results()
        except Exception:
            pass


class MySqlConnectorPythonCommands(Commands):
    capabilities: ClassVar[frozenset[AdapterCapability]] = frozenset({AdapterCapability.TRANSACTIONS})

    @classmethod
    def connect(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "Commands":
        mysql = import_dbapi_module("mysql.connector")
        connect_kwargs["client_flags"] = _resolve_client_flags(mysql, connect_kwargs.get("client_flags", _UNSET))
        conn = mysql.connect(
            host=parsed_dsn.host,
            port=parsed_dsn.port if parsed_dsn else 3306,
            user=parsed_dsn.user,
            password=parsed_dsn.password,
            database=parsed_dsn.dbname,
            **connect_kwargs,
        )
        return cls(conn)

    def query_first(
        self,
        sql,
        model=_MODEL_UNSET,
        param=_PARAM_ALIAS_UNSET,
        *,
        params=_PARAM_ALIAS_UNSET,
        mapper=_MAPPER_UNSET,
        options=None,
    ):
        """
        the mysql connector throws an exception if you only read one row from a cursor.  Unfortunately, we have to
        fetchall to make the lib happy.
        """
        resolved_options = self._resolve_options(options)
        resolved_params = self._resolve_params(param, params)
        _raise_if_list_params_for_read(resolved_params)
        projector, maps_raw_row = _resolve_row_projector(model, mapper)
        handler = self.SqlParamHandler(sql, resolved_params)

        with self._cursor_context_proxy() as cursor:
            self._prepare_cursor(cursor, options=resolved_options)
            self._prepare_command(cursor, handler, options=resolved_options)
            handler.execute(cursor)
            headers = get_col_names(cursor)
            row = cursor.fetchone()
            if row is None:
                raise NoResultException("Query returned no results")
            cursor.fetchall()
            if not maps_raw_row:
                validate_no_duplicate_columns(headers)
            return _project_row(projector, maps_raw_row, headers, row)

    def _on_duplicate_columns(self, cursor: "CursorType") -> None:
        _discard_unread_result(cursor)

    def _on_query_single_more_than_one_result(self, cursor: "CursorType") -> None:
        _discard_unread_result(cursor)
