from typing import TYPE_CHECKING

from pydapper.commands import CommandsAsync

from pydapper.main import register_async
from pydapper.utils import import_dbapi_module

if TYPE_CHECKING:
    from pydapper.dsn_parser import PydapperParseResult

@register_async("aiomysql")
class AiomysqlCommands(CommandsAsync):

    @classmethod
    async def connect_async(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "CommandsAsync":
        aiomysql = import_dbapi_module("aiomysql")
        conn = await aiomysql.connect(
            host=parsed_dsn.host,
            port=parsed_dsn.port if parsed_dsn else 3306,
            user=parsed_dsn.user,
            password=parsed_dsn.password,
            database=parsed_dsn.dbname,
            **connect_kwargs,
        )
        commands = cls(conn)
        return commands
