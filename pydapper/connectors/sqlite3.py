import sqlite3
from ..dbapi.cursor import CursorProxy
from ..dbapi.connection import ConnectionProxy
from ..dbapi.pool import ConnectionPool
from ..commands import BaseCommands
from typing import Self
from ..dsn_parser import PydapperParseResult
from ..parameters.enums import ParamStyle


class Sqlite3CursorProxy(CursorProxy[sqlite3.Cursor]):
    supported_param_styles = [ParamStyle.NAMED]


class Sqlite3ConnectionProxy(ConnectionProxy[sqlite3.Connection, sqlite3.Cursor]):
    @classmethod
    def connect(cls, dsn: PydapperParseResult, **kwargs) -> Self:
        return cls(sqlite3.connect(dsn.host), **kwargs)


class Sqlite3ConnectionPool(ConnectionPool):
    ConnectionProxy = Sqlite3ConnectionProxy


class Sqlite3Commands(BaseCommands):
    CursorProxy = Sqlite3CursorProxy
    ConnectionProxy = Sqlite3ConnectionProxy
    ConnectionPool = Sqlite3ConnectionPool
