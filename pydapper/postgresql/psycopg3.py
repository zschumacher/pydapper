from typing import TYPE_CHECKING

from pydapper.commands import Commands
from pydapper.commands import CommandsAsync

from .._context import CoroContextManager
from ..utils import import_dbapi_module

if TYPE_CHECKING:
    from ..dsn_parser import PydapperParseResult


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


class Psycopg3CommandsAsync(CommandsAsync):
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

    def cursor(self, *args, **kwargs):
        async def cursor_proxy():
            return self.connection.cursor(*args, **kwargs)

        return CoroContextManager(cursor_proxy(), preserve_active_error=True)
