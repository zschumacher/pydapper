from typing import TYPE_CHECKING

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
    @classmethod
    def connect(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "Commands":
        mysql = import_dbapi_module("mysql.connector")
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
        self._resolve_options(options)
        resolved_params = self._resolve_params(param, params)
        _raise_if_list_params_for_read(resolved_params)
        projector, maps_raw_row = _resolve_row_projector(model, mapper)
        handler = self.SqlParamHandler(sql, resolved_params)

        with self.cursor() as cursor:
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
