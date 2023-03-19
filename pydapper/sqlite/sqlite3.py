import sqlite3
from sqlite3 import Cursor
from typing import TYPE_CHECKING

from pydapper import register
from pydapper.commands import BaseSqlParamHandler
from pydapper.commands import Commands

if TYPE_CHECKING:
    from ..dsn_parser import PydapperParseResult


@register("sqlite3")
class Sqlite3Commands(Commands):
    class SqlParamHandler(BaseSqlParamHandler):
        def get_param_placeholder(self, param_name) -> str:
            return "?"

    @classmethod
    def connect(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "Commands":
        conn = sqlite3.connect(parsed_dsn.host, **connect_kwargs)
        return cls(conn)  # type: ignore
