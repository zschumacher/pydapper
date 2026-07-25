from typing import TYPE_CHECKING
from typing import ClassVar

from pydapper.capabilities import AdapterCapability
from pydapper.commands import Commands
from pydapper.commands import CommandsAsync

from .._context import _AwaitableAsyncContextManager
from ..utils import import_dbapi_module

if TYPE_CHECKING:
    from ..dsn_parser import PydapperParseResult
    from ..types import AsyncCursorType


class Psycopg3Commands(Commands):
    capabilities: ClassVar[frozenset[AdapterCapability]] = frozenset({AdapterCapability.TRANSACTIONS})

    @classmethod
    def connect(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "Commands":
        psycopg = import_dbapi_module("psycopg")
        conn = psycopg.connect(
            dbname=parsed_dsn.dbname,
            user=parsed_dsn.username,
            password=parsed_dsn.password,
            host=parsed_dsn.host,
            port=parsed_dsn.port if parsed_dsn.port is not None else "5432",
            **connect_kwargs,
        )
        return cls(conn)


class Psycopg3CommandsAsync(CommandsAsync):
    capabilities: ClassVar[frozenset[AdapterCapability]] = frozenset()

    @classmethod
    async def connect_async(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "CommandsAsync":
        psycopg = import_dbapi_module("psycopg")
        conn = await psycopg.AsyncConnection.connect(
            dbname=parsed_dsn.dbname,
            user=parsed_dsn.username,
            password=parsed_dsn.password,
            host=parsed_dsn.host,
            port=parsed_dsn.port if parsed_dsn.port is not None else "5432",
            **connect_kwargs,
        )
        return cls(conn)

    def cursor(self, *args, **kwargs) -> "_AwaitableAsyncContextManager[AsyncCursorType, AsyncCursorType]":
        async def cursor_proxy():
            return self.connection.cursor(*args, **kwargs)

        return _AwaitableAsyncContextManager(cursor_proxy(), preserve_active_error=True)
