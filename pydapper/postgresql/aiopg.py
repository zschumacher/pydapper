from typing import TYPE_CHECKING

from pydapper.commands import CommandsAsync
from pydapper.commands import DefaultSqlParamHandler

from ..main import register_async
from ..utils import import_dbapi_module

if TYPE_CHECKING:
    from ..dsn_parser import PydapperParseResult
    from ..types import AsyncCursorType


@register_async("aiopg")
class AiopgCommands(CommandsAsync):
    class SqlParamHandler(DefaultSqlParamHandler):
        async def execute_async(self, cursor: "AsyncCursorType"):
            if isinstance(self.ordered_param_values, list):
                # unfortunately aiopg does not implement execute many
                rowcount = 0
                for param_values in self.ordered_param_values:
                    await cursor.execute(self.prepared_sql, param_values)
                    rowcount += cursor.rowcount
            else:
                await cursor.execute(self.prepared_sql, self.ordered_param_values)
                rowcount = cursor.rowcount

            return rowcount

    @classmethod
    async def connect_async(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "CommandsAsync":
        aiopg = import_dbapi_module("aiopg")
        conn = await aiopg.connect(
            dbname=parsed_dsn.dbname,
            user=parsed_dsn.username,
            password=parsed_dsn.password,
            host=parsed_dsn.host,
            port=parsed_dsn.port if parsed_dsn.port else "5432",
            **connect_kwargs,
        )
        commands = cls(conn)
        return commands
