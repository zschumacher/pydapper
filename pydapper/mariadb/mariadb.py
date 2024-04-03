from typing import TYPE_CHECKING

from pydapper import register
from pydapper.commands import Commands
from ..utils import import_dbapi_module

if TYPE_CHECKING:
    from ..dsn_parser import PydapperParseResult


@register("mariadb")
class MariaDbCommands(Commands):
    @classmethod
    def connect(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "Commands":
        mysql = import_dbapi_module("mariadb")
        conn = mysql.connect(
            host=parsed_dsn.host,
            port=parsed_dsn.port if parsed_dsn else 3306,
            user=parsed_dsn.user,
            password=parsed_dsn.password,
            database=parsed_dsn.dbname,
            **connect_kwargs,
        )
        return cls(conn)
