import sqlite3
from sqlite3 import Cursor
from typing import TYPE_CHECKING
from typing import ClassVar

from pydapper.capabilities import AdapterCapability
from pydapper.commands import BaseSqlParamHandler
from pydapper.commands import Commands

if TYPE_CHECKING:
    from ..dsn_parser import PydapperParseResult


class Sqlite3Commands(Commands):
    capabilities: ClassVar[frozenset[AdapterCapability]] = frozenset()

    class SqlParamHandler(BaseSqlParamHandler):
        def get_param_placeholder(self, param_name) -> str:
            return "?"

    @classmethod
    def connect(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "Commands":
        conn = sqlite3.connect(parsed_dsn.database, **connect_kwargs)
        return cls(conn)  # type: ignore
