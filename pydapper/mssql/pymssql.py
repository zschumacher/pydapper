from decimal import Decimal
from typing import TYPE_CHECKING

from pydapper import register
from pydapper.commands import BaseSqlParamHandler
from pydapper.commands import Commands

from ..utils import import_dbapi_module
from ..utils import safe_getattr

if TYPE_CHECKING:
    from ..dsn_parser import PydapperParseResult

_PARAM_TYPE_LOOKUP = {float: "%d", int: "%d", str: "%s", Decimal: "%d"}


@register("pymssql")
class PymssqlCommands(Commands):
    class SqlParamHandler(BaseSqlParamHandler):
        def get_param_placeholder(self, param_name) -> str:
            param_value = safe_getattr(self._param, param_name)
            return _PARAM_TYPE_LOOKUP.get(type(param_value), "%s")

    @classmethod
    def connect(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "Commands":
        pymssql = import_dbapi_module("pymssql")
        conn = pymssql.connect(
            server=parsed_dsn.host,
            port=parsed_dsn.port if parsed_dsn else 1433,
            user=parsed_dsn.user,
            password=parsed_dsn.password,
            database=parsed_dsn.dbname,
            **connect_kwargs,
        )
        return cls(conn)
