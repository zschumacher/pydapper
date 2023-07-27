from typing import TYPE_CHECKING

from pydapper.commands import CommandsAsync
from pydapper.commands import DefaultSqlParamHandler
from pydapper.main import register_async
from pydapper.types import AsyncCursorType
from pydapper.utils import import_dbapi_module

if TYPE_CHECKING:
    from ..dsn_parser import PydapperParseResult


_DRIVERS = {
    "mssql": "{ODBC Driver 17 for SQL Server}",
    "mysql": "{MySQL ODBC 8.0 Unicode Driver}",
    "postgresql": "{PostgreSQL Unicode}",
    "sqlite": "{SQLite3 ODBC Driver}",
}


def pydapper_dsn_to_odbc(parsed_dsn: "PydapperParseResult") -> str:
    server = parsed_dsn.host
    if parsed_dsn.port:
        server += f",{parsed_dsn.port}"
    chunks = {
        "server": server,
        "uid": parsed_dsn.username,
        "pwd": parsed_dsn.password,
        "database": parsed_dsn.dbname,
        "driver": _DRIVERS.get(parsed_dsn.dbms, ""),
        **parsed_dsn.query,
    }
    return ";".join([f"{k.upper()}={v}" for k, v in chunks.items()])


@register_async("aioodbc")
class AioodbcCommands(CommandsAsync):
    class SqlParamHandler(DefaultSqlParamHandler):
        def get_param_placeholder(self, param_name: str) -> str:
            return "(?)"

    @classmethod
    async def connect_async(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "CommandsAsync":
        aioodbc = import_dbapi_module("aioodbc")
        dsn = pydapper_dsn_to_odbc(parsed_dsn)
        conn = await aioodbc.connect(
            dsn=dsn,
            **connect_kwargs,
        )
        return cls(conn)
