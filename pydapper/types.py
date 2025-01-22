from abc import abstractmethod
from typing import Any
from typing import List
from typing import Mapping
from typing import MutableMapping
from typing import Optional
from typing import Protocol
from typing import Union


class SupportsAttrAccess(Protocol):
    def __getattribute__(self, item): ...


ParamType = Union[SupportsAttrAccess, Mapping, MutableMapping]
ListParamType = Union[List[SupportsAttrAccess], List[Mapping], List[MutableMapping]]


class ConnectionType(Protocol):
    @abstractmethod
    def __enter__(self): ...

    @abstractmethod
    def __exit__(self, exc_type, exc_val, exc_tb): ...

    @abstractmethod
    def cursor(self, *args: Optional[Any], **kwargs: Optional[Any]) -> "CursorType": ...


class AsyncConnectionType(Protocol):
    @abstractmethod
    def __await__(self): ...

    @abstractmethod
    async def __aenter__(self): ...

    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb): ...

    @abstractmethod
    async def cursor(self, *args: Optional[Any], **kwargs: Optional[Any]) -> "AsyncCursorType": ...


class CursorType(Protocol):
    rowcount: int

    @abstractmethod
    def execute(self, sql: str, parameters: Any = None): ...

    @abstractmethod
    def fetchone(self): ...

    @abstractmethod
    def fetchall(self): ...

    @abstractmethod
    def executemany(self, sql, params=None): ...


class AsyncCursorType(Protocol):
    rowcount: int

    @abstractmethod
    async def execute(self, sql: str, parameters: Any = None): ...

    @abstractmethod
    async def fetchone(self): ...

    @abstractmethod
    async def fetchall(self): ...

    @abstractmethod
    async def executemany(self, sql, params=None): ...
