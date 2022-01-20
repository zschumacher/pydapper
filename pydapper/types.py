import sys

if sys.version_info < (3, 8):
    from typing_extensions import Protocol
else:
    from typing import Protocol

from abc import abstractmethod
from typing import Any
from typing import List
from typing import Mapping
from typing import MutableMapping
from typing import Optional
from typing import Union


class SupportsAttrAccess(Protocol):
    def __getattribute__(self, item):
        ...


ParamType = Union[SupportsAttrAccess, Mapping, MutableMapping]
ListParamType = Union[List[SupportsAttrAccess], List[Mapping], List[MutableMapping]]


class ConnectionType(Protocol):
    @abstractmethod
    def __enter__(self):
        ...

    @abstractmethod
    def __exit__(self, exc_type, exc_val, exc_tb):
        ...

    @abstractmethod
    def cursor(self, *args: Optional[Any], **kwargs: Optional[Any]) -> "CursorType":
        ...

    @abstractmethod
    def commit(self):
        ...

    @abstractmethod
    def rollback(self):
        ...

    @abstractmethod
    def close(self):
        ...


class CursorType(Protocol):
    rowcount: int

    @abstractmethod
    def __enter__(self) -> "CursorType":
        ...

    @abstractmethod
    def __exit__(self, exc_type, exc_val, exc_tb):
        ...

    @abstractmethod
    def execute(self, sql: str, parameters: Any):
        ...

    @abstractmethod
    def fetchone(self):
        ...

    @abstractmethod
    def fetchall(self):
        ...

    @abstractmethod
    def executemany(self, sql, params):
        ...

    @abstractmethod
    def close(self):
        ...
