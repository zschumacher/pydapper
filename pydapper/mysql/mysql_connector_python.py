from typing import TYPE_CHECKING
from typing import Any

from pydapper import register
from pydapper.commands import Commands

from ..exceptions import NoResultException
from ..types import ParamType
from ..utils import database_row_to_dict
from ..utils import get_col_names
from ..utils import import_dbapi_module
from ..utils import serialize_dict_row

if TYPE_CHECKING:
    from ..dsn_parser import PydapperParseResult


@register("mysql")
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
        sql: str,
        model: Any = dict,
        param: "ParamType" = None,
    ) -> Any:
        """
        the mysql connector throws an exception if you only read one row from a cursor.  Unfortunately, we have to
        fetchall to make the lib happy.
        """
        handler = self.SqlParamHandler(sql, param)

        with self.cursor() as cursor:
            handler.execute(cursor)
            headers = get_col_names(cursor)
            row = cursor.fetchone()
            if not row:
                raise NoResultException("Query returned no results")
            cursor.fetchall()
        return serialize_dict_row(model, database_row_to_dict(headers, row))
