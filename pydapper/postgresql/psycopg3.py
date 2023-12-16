from typing import TYPE_CHECKING

from pydapper.commands import Commands
from pydapper.commands import CommandsAsync

from ..main import register
from ..main import register_async
from ..utils import import_dbapi_module

if TYPE_CHECKING:
    from ..dsn_parser import PydapperParseResult
    from ..types import AsyncCursorType


@register("psycopg")
class Psycopg3Commands(Commands):
    @classmethod
    def connect(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "Commands":
        psycopg = import_dbapi_module("psycopg")
        conn = psycopg.connect(
            dbname=parsed_dsn.dbname,
            user=parsed_dsn.username,
            password=parsed_dsn.password,
            host=parsed_dsn.host,
            port=parsed_dsn.port if parsed_dsn.port else "5432",
            **connect_kwargs,
        )
        return cls(conn)


@register_async("psycopg")
class Psycopg3CommandsAsync(CommandsAsync):
    # https://www.psycopg.org/psycopg3/docs/api/connections.html#psycopg.AsyncConnection.cursor
    # AsyncConnection.cursor() function is not an async function (it never performs I/O) so we don't need CoroContextManager
    def cursor(self, *args, **kwargs) -> "AsyncCursorType":
        return self.connection.cursor(*args, **kwargs)

    @classmethod
    async def connect_async(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "CommandsAsync":
        psycopg = import_dbapi_module("psycopg")
        conn = await psycopg.AsyncConnection.connect(
            dbname=parsed_dsn.dbname,
            user=parsed_dsn.username,
            password=parsed_dsn.password,
            host=parsed_dsn.host,
            port=parsed_dsn.port if parsed_dsn.port else "5432",
            **connect_kwargs,
        )
        return cls(conn)
