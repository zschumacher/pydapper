from abc import abstractmethod
from types import SimpleNamespace
from typing import Any
from typing import ClassVar
from typing import List
from typing import Mapping
from typing import MutableMapping
from typing import Optional
from typing import Protocol
from typing import TypeAlias
from typing import Union


class SupportsDataclassFields(Protocol):
    __dataclass_fields__: ClassVar[dict[str, Any]]


class SupportsAttrAccess(Protocol):
    def __getattr__(self, item: str) -> Any: ...


ParamType: TypeAlias = Union[
    Mapping[str, Any],
    MutableMapping[str, Any],
    SimpleNamespace,
    SupportsDataclassFields,
    SupportsAttrAccess,
]
ListParamType: TypeAlias = List[Any]


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
