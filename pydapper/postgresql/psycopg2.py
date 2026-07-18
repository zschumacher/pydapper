from typing import TYPE_CHECKING
from typing import ClassVar

from pydapper.capabilities import AdapterCapability
from pydapper.commands import Commands

from ..utils import import_dbapi_module

if TYPE_CHECKING:
    from ..dsn_parser import PydapperParseResult


class Psycopg2Commands(Commands):
    capabilities: ClassVar[frozenset[AdapterCapability]] = frozenset()

    @classmethod
    def connect(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "Commands":
        psycopg2 = import_dbapi_module("psycopg2")
        conn = psycopg2.connect(
            dbname=parsed_dsn.dbname,
            user=parsed_dsn.username,
            password=parsed_dsn.password,
            host=parsed_dsn.host,
            port=parsed_dsn.port if parsed_dsn.port is not None else "5432",
            **connect_kwargs,
        )
        return cls(conn)
