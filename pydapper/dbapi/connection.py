from typing import TypeVar, Generic
from .cursor import CursorProxy, CursorType
from typing import Self
from abc import abstractmethod
from ..dsn_parser import PydapperParseResult

ConnectionType = TypeVar("ConnectionType")


class ConnectionProxy(Generic[ConnectionType, CursorType]):
    def __init__(self, connection: ConnectionType):
        self.connection = connection

    def close(self):
        return self.connection.close()

    def commit(self):
        return self.connection.commit()

    def rollback(self):
        return self.connection.rollback()

    def cursor(self) -> CursorProxy[CursorType]:
        return CursorProxy(self.connection.cursor())

    @classmethod
    @abstractmethod
    def connect(cls, dsn: PydapperParseResult, **kwargs) -> Self: ...
