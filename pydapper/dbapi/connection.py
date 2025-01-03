from typing import TypeVar, Generic, Sequence
from .cursor import CursorProxy, CursorType
from ..parameters.enums import ParamStyle
from typing_extensions import Self
from abc import abstractmethod

ConnectionType = TypeVar("ConnectionType")


class ConnectionProxy(Generic[ConnectionType, CursorType]):
    param_style: list[ParamStyle]

    def __init_subclass__(cls, **kwargs):
        assert hasattr(cls, "param_style"), "Must set param_style for concrete subclasses"

    def __init__(self, connection: ConnectionType):
        self.connection = connection

    def close(self):
        return self.connection.close()

    def commit(self):
        return self.connection.commit()

    def rollback(self):
        return self.connection.rollback()

    def cursor(self) -> CursorProxy[CursorType]:
        return CursorProxy(self.connection.cursor(), self.param_style)

    @classmethod
    @abstractmethod
    def connect(cls, **kwargs) -> Self:
        ...
